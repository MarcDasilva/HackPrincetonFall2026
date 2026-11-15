"""The lead: the exchange in front of the study.

    lead:    Anything I should know before I launch research based on your audiogram?
    patient: no                 -> launch
    patient: <anything else>    -> "Noted. May I begin?"  (repeats for every further note)
               then yes -> launch, no -> wait, anything else -> noted again

Up to the launch the lines are fixed copy, so no model is called. Research starts ONLY from a
"launched" step; server.py owns that hand-off and the per-run session it is stored in. After launch
the coordinator model answers questions with the study's live progress as context (answer below).

After research the lead runs the rest, one stage at a time (flow below; server.py moves the stages
that wait on the dashboard or on background work):

    launched -> sim_ready     research finished: "Great, all done. Ready to run the simulation?"
    sim_ready -> sim_count    yes (anything else: answered, then asked again)
    sim_count -> sim_prep     a number 1-100; the scene picker runs in the background
    sim_prep -> sim_running   scenes saved; the dashboard runs them in the orb
    sim_running -> design_ready   the patient closed the finished simulations
    design_ready -> designing     yes; the dashboard asks the backend for four designs
    designing -> options      the four designs came back
    options -> validating     the patient picked one; the orb reopens and re-scores the scenes with it, the
                              earpiece voxelized into the 3D wave sim (backend wave_check)
    validating -> final       the patient closed the validation
    final -> done             "report": the final report and the print file
"""

from __future__ import annotations

import json
import os
import random
import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, BeforeValidator, Field

from horn_study.lead_tools import SESSION_TOOLS, session_tools

OPENING = "Anything I should know before I launch research based on your audiogram?"
NOTED = "Noted."
BEGIN = "May I begin?"
WAIT = "Okay, I'll wait. Tell me anything else, or say yes when you're ready."
LAUNCH = "Four agents are researching your aid. Ask me anything."

SIM_READY = "Great, all done. Ready to run the simulation?"
MOVE_ON = "Okay, moving on with what the research has found so far. Ready to run the simulation?"
ASK_SIM = "Ready to run the simulation?"
SIM_COUNT = "How many simulations should I run? Pick a number from 1 to 100."
COUNT_AGAIN = "I need a number from 1 to 100. How many simulations should I run?"
PREPARING = "Setting up {n} simulations from your profile and the research."
SIM_RUNNING = "The simulation is running. Click the orb to watch."
DESIGN_READY = "Great, I have enough data to develop a hearing aid. Ready to see it?"
ASK_DESIGN = "Ready to see it?"
DESIGNING = "Designing your hearing aid. Four options are on the way."
OPTIONS = "Here are four options, each with its reasoning. Pick the one you want."
VALIDATING = (
    "Let's check it really helps you: your simulations are running again with that earpiece in your ear."
)
FINAL = "Want your final report and the file to print?"
ASK_FINAL = FINAL
DONE = "Your report and the file to print are downloading now. 😊"
MAX_SIMS = 100

Stage = Literal[
    "new",
    "opening",
    "begin",
    "launched",
    "sim_ready",
    "sim_count",
    "sim_prep",
    "sim_running",
    "design_ready",
    "designing",
    "options",
    "validating",
    "final",
    "done",
]
# What the dashboard reports, and the ONE stage each is accepted in -> the stage it moves to.
EVENTS: dict[str, tuple[Stage, Stage]] = {
    "sims_done": ("sim_running", "design_ready"),
    "options": ("designing", "options"),
    "design_failed": ("designing", "design_ready"),
    "picked": ("options", "validating"),
    "validated": ("validating", "final"),
}

# ponytail: word lists, not a model. A reply like "no, but I have tinnitus" counts as a note (more
# than three words); a model classifier if patients phrase answers in ways these miss.
_NO = {"no", "nope", "nah", "nothing", "none"}
_YES = {"yes", "yeah", "yep", "sure", "ok", "okay", "go", "begin", "start"}


def _answer(text: str) -> Literal["yes", "no"] | None:
    words = re.findall(r"[a-z']+", text.lower())
    if not words or len(words) > 3:
        return None
    if words[0] in _NO:
        return "no"
    if words[0] in _YES:
        return "yes"
    return None


def step(stage: Stage, text: str) -> tuple[str, Stage, str | None]:
    """(reply, next stage, note to keep) for one patient message before launch."""
    if stage == "new":
        return OPENING, "opening", None
    answer = _answer(text)
    # "No" means "nothing to add" ONLY to the opening question; to "May I begin?" it means wait.
    if (stage == "opening" and answer == "no") or (stage == "begin" and answer == "yes"):
        return LAUNCH, "launched", None
    if stage == "begin" and answer == "no":
        return WAIT, "begin", None
    return f"{NOTED} {BEGIN}", "begin", text


def moving_on(text: str) -> bool:
    """A short "continue" / "move on" / "skip" during research: the patient wants the next step NOW."""
    words = re.findall(r"[a-z']+", text.lower())
    # "next" is left out: "what's next?" is a question, not a request to cut research short.
    said = re.search(r"\b(continue|move on|moving on|skip|go on)\b", " ".join(words))
    return 0 < len(words) <= 4 and said is not None


def count(text: str) -> int | None:
    """The simulation count in a reply ("40", "let's do 12"), or None when there is no number in range."""
    m = re.search(r"\d+", text)
    n = int(m.group()) if m else 0
    return n if 1 <= n <= MAX_SIMS else None


def flow(stage: Stage, text: str) -> tuple[str | None, Stage, str | None]:
    """(fixed reply or None for a model answer, next stage, question re-asked after a model answer)."""
    yes = _answer(text) == "yes"
    if stage == "sim_ready":
        return (SIM_COUNT, "sim_count", None) if yes else (None, stage, ASK_SIM)
    if stage == "sim_count":
        n = count(text)
        return (PREPARING.format(n=n), "sim_prep", None) if n else (COUNT_AGAIN, stage, None)
    if stage == "design_ready":
        return (DESIGNING, "designing", None) if yes else (None, stage, ASK_DESIGN)
    if stage == "final":
        # The report is a model call; server.py writes it when this returns "done".
        return (DONE, "done", None) if yes or "report" in text.lower() else (None, stage, ASK_FINAL)
    return None, stage, None


class PickedSource(BaseModel):
    role: Literal["talker", "babble"]
    # All round the head: the sims run on a head wearing BOTH ears (frontend app/sim/lib/twoEar.ts) and score each ear,
    # so a source past 180 is on the OTHER ear's side. 0–180 only held while the grid was one ear on a flat wall.
    az: int = Field(
        ge=0,
        le=359,
        description="Degrees: 0 in front, 90 straight out from the aided ear, 180 behind, 270 straight out from the other ear.",
    )
    el: int = Field(ge=-60, le=70, description="Degrees above the horizontal.")
    level_db: int = Field(ge=40, le=90, description="dB SPL at the head.")
    # Default "": a missing or unknown name is replaced from the bank (_fill_sounds), NEVER a reason to drop the scene set.
    sound: str = Field("", description="Exactly one name from the sound bank list; talkers should be voices.")


SOUND_CATALOG_ENV = "HORN_STUDY_SOUND_CATALOG"
# Clips a talker can fall back to: a talker playing a door slam would score speech the patient never heard.
_VOICES = ("speech", "conversation", "whisper", "shout", "yell", "chatter", "laughter", "singing")


def sound_bank() -> list[str]:
    """Names in the backend's sound bank (GET /api/sim/sounds/{name} serves ONLY these). Empty when this machine has no
    bank; the sims then play their built-in speech clips (frontend app/sim/lib/clip.ts clipNames)."""
    default = Path(__file__).resolve().parents[3] / "backend" / "data" / "sounds" / "catalog.json"
    try:
        return sorted(json.loads(Path(os.environ.get(SOUND_CATALOG_ENV) or default).read_text()))
    except (OSError, ValueError):
        return []


def _fill_sounds(scene: dict[str, Any], bank: list[str], rng: random.Random) -> None:
    """Every source ends with a sound the bank serves: the model's pick when it is a bank name, else a random one."""
    voices = [k for k in bank if any(v in k for v in _VOICES)] or bank
    for src in scene["sources"]:
        if not bank:
            src.pop("sound", None)
        elif src.get("sound") not in bank:
            src["sound"] = rng.choice(voices if src["role"] == "talker" else bank)


def _random_scene(i: int, rng: random.Random) -> dict[str, Any]:
    """A stand-in scene for when the picker call fails: the sims still run, on random directions and levels."""
    sources = [
        {"role": "talker", "az": rng.randrange(0, 360, 15), "el": 0, "level_db": rng.randrange(55, 76, 5)}
    ]
    if rng.random() < 0.5:
        sources.append(
            {"role": "babble", "az": rng.randrange(0, 360, 15), "el": 0, "level_db": rng.randrange(50, 71, 5)}
        )
    return {
        "name": f"Random scene {i}",
        "sound": "random sound",
        "weight": 3,
        "sources": sources,
        "why": "The scene picker failed, so this scene was chosen at random.",
    }


def _clip(n: int):
    """Trim to n characters at a word boundary. The limits below ride along in the model's schema, but a model can still
    overrun one; these are display labels, so one long label must NEVER throw away the whole scene set."""

    def f(v: Any) -> Any:
        if not isinstance(v, str) or len(v) <= n:
            return v
        cut = v[: n - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return (cut or v[: n - 1]) + "…"

    return BeforeValidator(f)


class PickedScene(BaseModel):
    name: Annotated[str, _clip(60)] = Field(max_length=60)
    sound: Annotated[str, _clip(60)] = Field(
        max_length=60, description="The everyday sound this stands for, e.g. 'grandchild talking'."
    )
    why: Annotated[str, _clip(200)] = Field(
        max_length=200, description="One sentence tying it to the patient's profile or the research."
    )
    weight: int = Field(ge=1, le=5, description="How much this situation matters to the patient.")
    sources: list[PickedSource] = Field(min_length=1, max_length=3)


class PickedScenes(BaseModel):
    scenes: list[PickedScene]


_PICKER = """You set up listening simulations for one patient's hearing aid. Each scene is a talker (and optional
babble noise) around the patient's aided ear; a wave simulation measures how much speech they miss in it.
Choose scenes that match this patient's life, using their audiogram, their notes, and the research findings.
Return exactly {n} scenes. Every scene needs at least one talker. Spread them across directions and levels;
do not repeat a scene already chosen. Give every source a `sound` copied exactly from this sound bank, the clip it
plays; a talker should be a voice:
{bank}

Patient: {patient}
Their notes: {notes}
Research findings:
{findings}
Already chosen: {chosen}"""

BATCH = 20


async def pick_scenes(
    model: BaseChatModel, n: int, *, patient: str, notes: list[str], findings: list[str]
) -> list[dict[str, Any]]:
    """n scenes for the dashboard's simulations, BATCH per model call (one call cannot spread 100 well)."""
    picker = model.with_structured_output(PickedScenes)
    bank, rng = sound_bank(), random.Random()
    scenes: list[dict[str, Any]] = []
    while len(scenes) < n:
        want = min(BATCH, n - len(scenes))
        prompt = _PICKER.format(
            n=want,
            patient=patient,
            notes="; ".join(notes) or "none",
            findings="\n".join(f"- {f}" for f in findings[-40:]) or "- none",
            chosen=", ".join(s["name"] for s in scenes) or "none",
            bank=", ".join(bank) or "(none on this machine; leave sound empty)",
        )
        try:
            out = await picker.ainvoke([HumanMessage(prompt)])
            got = [
                p.model_dump()
                for p in (
                    out.scenes if isinstance(out, PickedScenes) else PickedScenes.model_validate(out).scenes
                )
            ]
        except Exception:  # a failed call must NOT stop the sims: this batch is picked at random instead
            got = []
        got = got[:want] or [_random_scene(len(scenes) + k + 1, rng) for k in range(want)]
        for scene in got:
            if not any(src["role"] == "talker" for src in scene["sources"]):
                scene["sources"][0]["role"] = "talker"  # sceneDeficit scores nothing without a talker
            _fill_sounds(scene, bank, rng)
            scene["id"] = f"s{len(scenes) + 1}"
            scenes.append(scene)
    return scenes


_REPORT = """Write the final report for a patient whose passive, 3D-printed hearing aid was just designed. It is the
complete record of their session, so be thorough: 1500 to 2500 words, plain text, no markdown symbols. Put each section
title on its own line in capitals, then paragraphs; where you list scenes or numbers, one item per line starting "- ".
Write it as a professional design report addressed to the patient: precise, complete sentences, a measured tone, every
claim tied to a number below; no casual phrases, no exclamation marks. The dashboard lays these sections out beside its
own figures and tables, so do not describe charts; state the results.

Sections, in this order:
SUMMARY: the outcome in five sentences: their hearing, the design picked, how much it helped, the main caveat.
YOUR HEARING TEST: each ear, frequency by frequency, in words; which sounds that loss affects in daily life.
WHAT YOU TOLD US: their notes, and how they shaped the study.
WHAT THE RESEARCH FOUND: the findings that mattered for this design, each with its source, in plain words.
THE LISTENING SIMULATIONS: what was simulated and how (each scene a real recorded sound played from a direction round
a model of their own head and ears; speech audibility measured per ear). The overall unaided result, then the scenes
that were hardest and easiest, with their numbers, and patterns by direction, distance and background noise.
THE FOUR DESIGNS: each option, what it does, its average gain by frequency, why it ranked where it did.
THE DESIGN YOU PICKED: why it suits them; its gain with the earpiece in the ear, described the way the numbers below say
it was obtained (3D wave simulation or the 1D acoustic model).
YOUR CUSTOM EARPIECE: only when the session below has a custom earpiece: how it was shaped for their ear (where it
aims, its collector or hood, its fit), its measurements, the S, M and L sizes to print and try, and any way it differs
from the design that was tested. Leave this section out when there is none.
HOW MUCH IT HELPS: the validation: before and after per scene for the most important scenes, the overall change, where
it helps most, and where it does not help or makes things worse, and why.
LIMITS OF THIS STUDY: simulations, not clinical measurements; a passive device cannot amplify; fit and canal shape vary.
NEXT STEPS: print the file, how to try it, what to listen for, and when to see an audiologist.

Use the numbers below; never invent one. Never diagnose; say these are simulations, not clinical results. Never mention
"key bands" or how many bands a design meets; talk about gain by frequency instead.

Patient: {patient}
Their notes: {notes}
Research findings:
{findings}
Session: {session}"""


_REPORT_FILES = """

Evidence files, readable with ls, read_file, glob and grep: /findings/<agent>/ each sourced finding with its source, URL
and verbatim passage, /board/<agent>/ every info-board post, /sources/ the full text of each paper read, /earpiece/ the
custom earpiece's record. The findings above are one-line summaries WITHOUT their sources: open the finding files
you cite and name each source (title and URL) in WHAT THE RESEARCH FOUND. Read only what the report needs, then
write it."""

# ONE Deep Agent per run does everything the lead does: answers the patient, shapes and builds the earpiece, writes the
# report. Same tools, same file system, same model; each job arrives as a message headed QUESTION, EARPIECE TASK or REPORT
# TASK. Its memory is two checkpointed threads: "chat" (the patient's questions) and "work" (earpiece, then report — so the
# report is written by the agent that built the earpiece). Chat is separate because a build takes minutes and a question
# must not wait behind it.
_LEAD_SYSTEM = """You are the lead of a team designing a passive, 3D-printed hearing aid shaped to one patient's ear.
Four research agents (hearing research, use context, acoustic design, ear fit) research the patient's needs. Then the
patient runs listening simulations on their own ear, sees four designs, picks one, and validates it in simulation. You
then shape and build the picked design's earpiece and write the patient's final report.

Each message names the job:

QUESTION: the patient asked something. Answer from the study progress in the message. Reply in plain words, at most 40
words: the reply shows as two or three short lines under an orb, with no room for lists or markdown. Never diagnose, and
never claim a result the progress does not show.

EARPIECE TASK: shape and build the picked design's earpiece with build_earpiece and finish, following the instructions
in the message. When you have finished, reply with one plain sentence.

REPORT TASK: write the final report exactly as the message instructs, and make it your final message, with no preamble.

You can read the study's evidence files (ls, read_file, glob, grep) when they exist. They are read-only; never try to
write one. You also have read-only tools for the patient's own data (get_hearing_profile, get_ear_measurements, get_scenes,
get_design_options, compare_designs, get_validation) and for the literature (search_literature, read_source). Use them
instead of guessing a number, and cite a URL for anything you take from a paper. In a QUESTION keep the 40-word limit
however much you read."""

# The live study state, sent with each QUESTION so every reply reads the latest board and progress.
_STATUS = """Patient: {patient}
Their notes before launch: {notes}
Research status: {status}
Session so far: {session}
Info board: what the research agents flagged as important, oldest first. Lean on it most:
{board}
{files}
Study progress, oldest first:
{progress}"""


# Read-only: the evidence tree is the research record, so the lead NEVER gets write_file or edit_file.
READ_TOOLS = frozenset({"ls", "read_file", "glob", "grep"})
LEAD_TOOLS = READ_TOOLS | {"build_earpiece", "finish"} | SESSION_TOOLS
_FILES = """Evidence files, sorted, readable with ls, read_file, glob and grep. Open them when the question needs more
than the board: /board/<agent>/ every info-board post, /findings/<agent>/ each sourced finding with its verbatim
passage, /sources/ the full text of every paper read, /photos/ the patient's ear and head photos, /earpiece/ the custom earpiece built for the picked design (record.md)."""


class _Verbatim(AgentMiddleware[Any, Any, Any]):
    """Sends the model EXACTLY answer()'s system prompt, with ONLY the read-only file tools.

    create_deep_agent adds its base prompt, file system and subagent instructions, and their tools;
    without this the lead's replies drift from the 40-word orb copy. The messages are left alone so
    tool results reach the next call.
    """

    def __init__(self, system: SystemMessage, tools: frozenset[str]) -> None:
        self._system = system
        self._tools = tools

    def _exact(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        tools = [
            t for t in request.tools if (t.get("name") if isinstance(t, dict) else t.name) in self._tools
        ]
        return request.override(system_message=self._system, tools=tools)

    def wrap_model_call(self, request: ModelRequest[Any], handler: Callable[..., Any]) -> Any:
        return handler(self._exact(request))

    async def awrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[..., Awaitable[Any]]
    ) -> Any:
        return await handler(self._exact(request))


class _KeepRefusals(AgentMiddleware[Any, Any, Any]):
    """Takes ModelRefusalMiddleware's place by name, so a refusal comes back as reply text, as before.

    Deep Agents raises on a refusal instead, and server.py would answer "I can't answer right now".
    """

    @property
    def name(self) -> str:
        return "ModelRefusalMiddleware"


class Lead:
    """The run's one Deep Agent (see _LEAD_SYSTEM). build_earpiece and finish are stable proxies: while an earpiece task runs,
    `desk` holds earpiece.produce_earpiece's live tools and the proxies call them; outside one they say there is nothing to build."""

    def __init__(self, model: BaseChatModel) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        self.model = model
        self.desk: dict[str, Any] = {}
        self.ctx: dict[str, Any] = {}   # the session and patient folder the data tools read (server.agent_ctx), set before each job
        self.memory = MemorySaver()
        self.chatted = False   # False until the chat thread holds a turn: the first QUESTION carries the session's recent messages
        self._agents: dict[bool, Any] = {}

    def _proxy(self, name: str, schema: type[BaseModel], description: str) -> Any:
        from langchain_core.tools import StructuredTool

        def run(**args: Any) -> Any:
            tool = self.desk.get(name)
            return tool.invoke(args) if tool else "No design is being built right now, so there is nothing to do."

        return StructuredTool.from_function(func=run, name=name, description=description, args_schema=schema)

    def agent(self, evidence: Path | None) -> Any:
        from horn_study.earpiece import BuildArgs, FinishArgs

        has_files = evidence is not None
        if has_files not in self._agents:   # the evidence folder appears only once research writes its first file
            system = SystemMessage(_LEAD_SYSTEM)
            self._agents[has_files] = create_deep_agent(
                model=self.model,
                system_prompt=_LEAD_SYSTEM,
                tools=[
                    self._proxy("build_earpiece", BuildArgs, BuildArgs.__doc__ or ""),
                    self._proxy("finish", FinishArgs, FinishArgs.__doc__ or ""),
                    *session_tools(lambda: self.ctx),
                ],
                middleware=[_Verbatim(system, LEAD_TOOLS if has_files else LEAD_TOOLS - READ_TOOLS), _KeepRefusals()],
                backend=FilesystemBackend(root_dir=evidence, virtual_mode=True) if has_files else None,
                checkpointer=self.memory,
                name="lead",
            )
        return self._agents[has_files]

    @staticmethod
    def _call(thread: str, limit: int) -> dict[str, Any]:
        return {"recursion_limit": limit, "configurable": {"thread_id": thread}}

    async def ask(self, thread: str, text: str, evidence: Path | None, limit: int) -> str:
        result = await self.agent(evidence).ainvoke({"messages": [HumanMessage(text)]}, config=self._call(thread, limit))  # pyright: ignore[reportArgumentType]
        return str(result["messages"][-1].text).strip()

    def ask_sync(self, thread: str, text: str, evidence: Path | None, limit: int) -> str:
        """For work in a thread (every build is a blocking backend subprocess)."""
        result = self.agent(evidence).invoke({"messages": [HumanMessage(text)]}, config=self._call(thread, limit))  # pyright: ignore[reportArgumentType]
        return str(result["messages"][-1].text).strip()


_LEADS: dict[str, Lead] = {}


def lead_for(run_id: str, model: BaseChatModel, ctx: dict[str, Any] | None = None) -> Lead:
    """The run's lead agent, created on first use. In memory ONLY: after a server restart it starts a fresh conversation,
    and the first QUESTION then carries the session's recent messages."""
    if run_id not in _LEADS:
        _LEADS[run_id] = Lead(model)
    if ctx is not None:
        _LEADS[run_id].ctx = ctx
    return _LEADS[run_id]


async def answer(
    model: BaseChatModel,
    history: Iterable[dict[str, str]],
    *,
    run_id: str,
    ctx: dict[str, Any] | None = None,
    evidence: Path | None = None,
    patient: str,
    notes: list[str],
    status: str,
    events: list[dict[str, Any]],
    board: Sequence[dict[str, Any]] = (),
    session: str = "research only",
) -> str:
    """One reply after launch, from the run's lead agent. history is the session's messages, the question last.

    evidence is the study's sorted evidence tree (server.evidence_dir); ABSENT or not yet written, the lead answers from the
    status alone."""
    lead = lead_for(run_id, model, ctx)
    turns = list(history)
    # ponytail: the last 60 event summaries, not the artifacts; the lead reads /board and /findings when it needs more.
    progress = "\n".join(f"- [{e.get('component')}] {e.get('summary')}" for e in events[-60:]) or "- nothing yet"
    posts = "\n".join(f"- [{p.get('investigator')}] {p.get('headline')}: {p.get('detail')}" for p in board)
    text = "QUESTION\n" + _STATUS.format(
        patient=patient,
        notes="; ".join(notes) or "none",
        status=status,
        board=posts or "- nothing posted yet",
        progress=progress,
        session=session,
        files=_FILES if evidence is not None else "",
    )
    if not lead.chatted and len(turns) > 1:
        text += "\n\nThe conversation so far:\n" + "\n".join(f"{m['role']}: {m['text']}" for m in turns[-7:-1])
    text += f"\n\nThe patient asks: {turns[-1]['text']}"
    reply = await lead.ask("chat", text, evidence, 25)
    lead.chatted = True
    return reply


async def write_report(
    model: BaseChatModel,
    *,
    run_id: str,
    patient: str,
    notes: list[str],
    findings: list[str],
    session: str,
    evidence: Path | None = None,
    ctx: dict[str, Any] | None = None,
) -> str:
    """The final report, written by the run's lead agent in its work thread — the same agent that built the earpiece, with
    the evidence folder to name each finding's source."""
    prompt = _REPORT.format(
        patient=patient,
        notes="; ".join(notes) or "none",
        findings="\n".join(f"- {f}" for f in findings[-40:]) or "- none",
        session=session,
    )
    # ponytail: 60 model calls covers a few dozen file reads, then the writing turn; raise if reports end mid-read.
    return await lead_for(run_id, model, ctx).ask("work", "REPORT TASK\n" + prompt + (_REPORT_FILES if evidence else ""), evidence, 60)


async def custom_earpiece(
    model: BaseChatModel,
    *,
    run_id: str,
    study_dir: Path,
    ear_dir: Path,
    picked: str,
    context: dict[str, Any],
    evidence: Path | None = None,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The picked design, shaped for this patient by the run's lead agent and built in the backend (S, M and L sizes).

    The picked option's numbers are what the session scored, so earpiece.produce_earpiece LOCKS them (throat, mouth, stem,
    flare, collector reach and opening) and the agent only sets the aim, the rim and the fit. Builds land in
    <ear_dir>/aid/custom-e<N>[-S|-L]/. Returns earpiece.json's record; raises EarpieceError when it already exists."""
    import asyncio

    from horn_study.earpiece import COLLECTOR_OPENING, COLLECTOR_REACH, PROTRUSION, produce_earpiece

    result = json.loads((ear_dir / "scene_design" / "result.json").read_text(encoding="utf-8"))
    option = next(o for o in result["options"] if o["id"] == picked)
    geo = option.get("geometry") or {}
    reach = float(option.get("collector_reach_mm") or 0.0)
    params = {k: v for k, v in option["params"].items() if k != "collector"}
    params[COLLECTOR_REACH] = reach
    params[COLLECTOR_OPENING] = float(geo.get("collector_mouth_mm2") or 0.0) if reach > 0 else 0.0
    proud = geo.get("proud_of_concha_mm")
    results = {
        "study_id": "custom",   # the builds' ids: custom-e1, custom-e1-S ... (backend app/sim_api.py DESIGN_RE serves them)
        "selected_candidate_id": picked,
        "selected_candidate": {"kind": "design", "candidate_id": picked, "label": picked, "rationale": option.get("reason", ""), "parameters": params},
        "report": {"candidates": [{"candidate_id": picked, "metrics": [{"name": PROTRUSION, "mean": proud}]}]} if proud is not None else {},
        "study_context": context,
    }
    lead = lead_for(run_id, model, ctx)

    def run(tools: list[Any], system_text: str, brief_text: str) -> None:
        lead.desk = {t.name: t for t in tools}
        try:
            lead.ask_sync("work", "EARPIECE TASK\n" + system_text + "\n\nBrief:\n" + brief_text, evidence, 40)
        finally:
            lead.desk = {}

    return await asyncio.to_thread(produce_earpiece, study_dir, ear_dir, model, results=results, runner=run)
