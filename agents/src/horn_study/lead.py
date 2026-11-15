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
    options -> validating     the patient picked one; the orb re-scores the scenes with it
    validating -> final       the patient closed the validation
    final -> done             "report": the final report and the print file
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

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
VALIDATING = "Let's check it really helps you. Click the orb to watch."
FINAL = 'Ask me anything, or say "report" for your final report and the file to print.'
ASK_FINAL = 'Say "report" when you want the final report.'
DONE = "Your report is ready, with the file to print."
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
    # The live grid holds speakers on the aided half only: the flat head plane cannot pass sound to the far side.
    az: int = Field(
        ge=0, le=180, description="Degrees: 0 in front, 90 straight out from the aided ear, 180 behind."
    )
    el: int = Field(ge=-60, le=70, description="Degrees above the horizontal.")
    level_db: int = Field(ge=40, le=90, description="dB SPL at the head.")


class PickedScene(BaseModel):
    name: str = Field(max_length=60)
    sound: str = Field(
        max_length=60, description="The everyday sound this stands for, e.g. 'grandchild talking'."
    )
    why: str = Field(
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
do not repeat a scene already chosen.

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
    scenes: list[dict[str, Any]] = []
    while len(scenes) < n:
        want = min(BATCH, n - len(scenes))
        prompt = _PICKER.format(
            n=want,
            patient=patient,
            notes="; ".join(notes) or "none",
            findings="\n".join(f"- {f}" for f in findings[-40:]) or "- none",
            chosen=", ".join(s["name"] for s in scenes) or "none",
        )
        out = await picker.ainvoke([HumanMessage(prompt)])
        got = out.scenes if isinstance(out, PickedScenes) else PickedScenes.model_validate(out).scenes
        if not got:
            raise ValueError("the scene picker returned no scenes")
        for p in got[:want]:
            scene = p.model_dump()
            if not any(src["role"] == "talker" for src in scene["sources"]):
                scene["sources"][0]["role"] = "talker"  # sceneDeficit scores nothing without a talker
            scene["id"] = f"s{len(scenes) + 1}"
            scenes.append(scene)
    return scenes


_REPORT = """Write the final report for a patient whose passive, 3D-printed hearing aid was just designed.
Plain words, no markdown symbols, at most 300 words in short paragraphs: what their hearing test shows, what the
research found that mattered, what the simulations measured, which design they picked and why, how much it helped
in the validation, and what to do next (print the file, try it, see an audiologist for anything worse). Never
diagnose; say these are simulations, not clinical results.

Patient: {patient}
Their notes: {notes}
Research findings:
{findings}
Session: {session}"""


async def write_report(
    model: BaseChatModel, *, patient: str, notes: list[str], findings: list[str], session: str
) -> str:
    prompt = _REPORT.format(
        patient=patient,
        notes="; ".join(notes) or "none",
        findings="\n".join(f"- {f}" for f in findings[-40:]) or "- none",
        session=session,
    )
    out = await model.ainvoke([HumanMessage(prompt)])
    return str(out.text).strip()


_SYSTEM = """You are the lead of a team designing a passive, 3D-printed hearing aid shaped to one patient's ear.
Four research agents (hearing research, use context, acoustic design, ear fit) research the patient's needs. Then the
patient runs listening simulations on their own ear, sees four designs, picks one, and validates it in simulation.

Answer the patient's question from the study progress below. Reply in plain words, at most 40 words: the reply
shows as two or three short lines under an orb, with no room for lists or markdown. Never diagnose, and never
claim a result the progress does not show.

Patient: {patient}
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
_FILES = """Evidence files, sorted, readable with ls, read_file, glob and grep. Open them when the question needs more
than the board: /board/<agent>/ every info-board post, /findings/<agent>/ each sourced finding with its verbatim
passage, /sources/ the full text of every paper read, /photos/ the patient's ear and head photos."""


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


def _messages(
    history: Iterable[dict[str, str]],
    *,
    patient: str,
    notes: list[str],
    status: str,
    events: list[dict[str, Any]],
    board: Sequence[dict[str, Any]] = (),
    session: str = "research only",
    files: bool = False,
) -> list[AnyMessage]:
    """The system prompt with the study's live progress, then the session's messages."""
    # ponytail: the last 60 event summaries, not the artifacts; read research.json if answers need the findings in full.
    progress = (
        "\n".join(f"- [{e.get('component')}] {e.get('summary')}" for e in events[-60:]) or "- nothing yet"
    )
    posts = "\n".join(f"- [{p.get('investigator')}] {p.get('headline')}: {p.get('detail')}" for p in board)
    system = _SYSTEM.format(
        patient=patient,
        notes="; ".join(notes) or "none",
        status=status,
        board=posts or "- nothing posted yet",
        progress=progress,
        session=session,
        files=_FILES if files else "",
    )
    turns: list[AnyMessage] = [
        HumanMessage(m["text"]) if m["role"] == "patient" else AIMessage(m["text"]) for m in history
    ]
    return [SystemMessage(system), *turns]


async def answer(
    model: BaseChatModel, history: Iterable[dict[str, str]], *, evidence: Path | None = None, **context: Any
) -> str:
    """One reply after launch, from the lead Deep Agent. history is the session's messages, the question last.

    evidence is the study's sorted evidence tree (server.evidence_dir); ABSENT or not yet
    written, the lead answers from the prompt alone with no tools.
    """
    has_files = evidence is not None
    system, *turns = _messages(history, files=has_files, **context)
    assert isinstance(system, SystemMessage)
    agent = create_deep_agent(
        model=model,
        system_prompt=str(system.content),
        middleware=[_Verbatim(system, READ_TOOLS if has_files else frozenset()), _KeepRefusals()],
        backend=FilesystemBackend(root_dir=evidence, virtual_mode=True) if has_files else None,
        name="lead",
    )
    # ponytail: 12 model calls is plenty of file reads for a 40-word answer; raise if answers run out mid-read.
    result = await agent.ainvoke({"messages": turns}, config={"recursion_limit": 25})  # pyright: ignore[reportArgumentType]
    return str(result["messages"][-1].text).strip()
