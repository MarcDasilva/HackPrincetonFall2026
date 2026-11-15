"""HTTP front for the lead, for the dashboard (frontend/lib/lead.ts).

cd agents && uv run uvicorn horn_study.server:app --port 8010

One session per backend run ID, saved as <studies>/sessions/<run_id>.json, so a conversation and
its study survive a restart and the dashboard's session picker can switch between them. A "yes"
starts run_study (the four deep-agent investigators, then plan, experiments, report) in the
background; its events.jsonl is what GET /lead/{id}/events serves to the research boxes.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import os
import random
import re
import shutil
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from horn_study import lead

RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REPO = Path(__file__).resolve().parents[3]
TERMINAL = {"study.completed": "completed", "study.failed": "failed", "study.cancelled": "cancelled"}


def studies_dir() -> Path:
    return Path(os.environ.get("HORN_STUDY_DIR") or "studies")


def patients_dir() -> Path:
    return Path(os.environ.get("HORN_STUDY_PATIENTS_DIR") or REPO / "backend" / "data" / "patients")


class State:
    # Study tasks by run ID. In memory ONLY: a study whose task died with the process reads as "stopped".
    tasks: dict[str, asyncio.Task[Any]] = {}  # noqa: RUF012
    # The custom-earpiece build per run (earpiece_job), started when the patient picks a design. In memory ONLY.
    earpieces: dict[str, asyncio.Task[Any]] = {}  # noqa: RUF012


state = State()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # At startup, NOT import: importing this module (tests do) must not switch on .env's LangSmith tracing process-wide.
    load_dotenv(find_dotenv(usecwd=True))
    yield


app = FastAPI(title="horn-study lead", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Message(BaseModel):
    message: str = ""
    # A dashboard step instead of a typed message: one of lead.EVENTS, with what it produced.
    event: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


# -- sessions ---------------------------------------------------------------------------------------


def _path(run_id: str) -> Path:
    # The run ID is joined onto a path, so anything but the backend's plain IDs is a bad request.
    if not RUN_ID.match(run_id):
        raise HTTPException(400, "bad run id")
    return studies_dir() / "sessions" / f"{run_id}.json"


def load(run_id: str) -> dict[str, Any] | None:
    p = _path(run_id)
    return json.loads(p.read_text()) if p.exists() else None


def save(s: dict[str, Any]) -> None:
    p = _path(s["run_id"])
    # earpiece_job writes s["earpiece"] from a background task: a request that loaded the session BEFORE it finished must
    # not save the old "building" (or nothing) over the result.
    on_disk = ((load(s["run_id"]) or {}).get("earpiece")) if p.exists() else None
    mine = s.get("earpiece")
    if on_disk and (not mine or (mine.get("status") == "building" and on_disk.get("status") != "building")):
        s["earpiece"] = on_disk
    p.parent.mkdir(parents=True, exist_ok=True)
    s["updated_at"] = time.time()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1))
    tmp.replace(p)


def events(s: dict[str, Any]) -> list[dict[str, Any]]:
    if not s.get("study_id"):
        return []
    p = studies_dir() / s["study_id"] / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def board(evs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The info board, live: the research agents' submit_finding posts. board.json holds the same once research ends."""
    return [e["data"] for e in evs if e["type"] == "research.board_posted"]


def status(s: dict[str, Any], evs: list[dict[str, Any]] | None = None) -> str:
    """none | starting | running | completed | failed | cancelled | stopped | error."""
    if s.get("error"):
        return "error"
    if not s.get("study_id"):
        return "none"
    task = state.tasks.get(s["run_id"])
    if task and not task.done():
        return "running"
    for e in reversed(evs if evs is not None else events(s)):
        if e["type"] in TERMINAL:
            return TERMINAL[e["type"]]
    return "stopped"


def view(s: dict[str, Any]) -> dict[str, Any]:
    line = next((m["text"] for m in reversed(s["messages"]) if m["role"] == "lead"), "")
    # A study that fails AFTER the launch reply went out (guarded() in launch) left "Four agents are researching" on screen
    # with the boxes stuck on "Waiting to start". The failure replaces that line.
    if s.get("error") and s["stage"] == "launched":
        line = f"Research could not start: {s['error']}"
    return {
        "run_id": s["run_id"],
        # "new" = the run is still processing (or its ear cards have not cleared): the lead has not spoken yet.
        "stage": s["stage"],
        "reply": line,
        "awaiting_launch": s["stage"] in ("opening", "begin"),
        "launch_requested": s["stage"] not in ("new", "opening", "begin"),
        "study_id": s.get("study_id"),
        "status": status(s),
        "updated_at": s.get("updated_at", 0),
        # The simulation half, for the dashboard; each ABSENT until its stage has produced it.
        "ear": s.get("ear"),
        "scenes": s.get("scenes"),
        "sims": s.get("sims"),
        "options": s.get("options"),
        "picked": s.get("picked"),
        "validation": s.get("validation"),
        "report": s.get("report"),
        "earpiece": s.get("earpiece"),
    }


# -- study hand-off ---------------------------------------------------------------------------------


def _patient(run_id: str) -> dict[str, Any]:
    p = patients_dir() / run_id / "job.json"
    if not p.exists():
        raise ValueError(f"no finished patient {run_id} in {patients_dir()}")
    return json.loads(p.read_text())


def _audiograms(job: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Per-ear dB HL from either job.json layout: one ear {side, audiogram_db_hl} or {left: {...}, right: {...}}."""
    r = job.get("request", {})
    if r.get("audiogram_db_hl"):
        return {r["side"]: r["audiogram_db_hl"]}
    return {e: r[e]["audiogram_db_hl"] for e in ("left", "right") if (r.get(e) or {}).get("audiogram_db_hl")}


# The real evaluator's HASPI v2 needs these six; the in-app hearing test measures 500-4000 Hz only.
HASPI_HZ = (250.0, 500.0, 1000.0, 2000.0, 4000.0, 6000.0)


def _extend_flat(ag: dict[str, float]) -> tuple[dict[str, float], list[float]]:
    """Fills HASPI frequencies BELOW and ABOVE the measured range with the nearest measured threshold — the SAME flat rule
    hornsim's scoring.hearing_level applies — and returns which were filled. Gaps INSIDE the range are left for intake to
    reject: those are a test that skipped a frequency, not one that never covered it."""
    got = {float(k): float(v) for k, v in ag.items()}
    lo, hi = min(got), max(got)
    filled = [f for f in HASPI_HZ if f not in got and (f < lo or f > hi)]
    for f in filled:
        got[f] = got[lo] if f < lo else got[hi]
    return {f"{k:g}": v for k, v in got.items()}, filled


def study_request(run_id: str, study_id: str, job: dict[str, Any], notes: list[str]) -> dict[str, Any]:
    ags = _audiograms(job)
    if not ags:
        raise ValueError("this patient has no audiogram numbers to study")
    # Without this, a patient from the in-app test is rejected at intake ("Missing ... at 250 Hz") and research never starts.
    filled = {}
    for ear in list(ags):
        ags[ear], f = _extend_flat(ags[ear])
        if f:
            filled[ear] = f
    # Two ears: the study targets the one with the worse average threshold — it needs the aid most.
    target = max(ags, key=lambda e: sum(ags[e].values()) / len(ags[e]))
    example = job.get("request", {}).get("audiogram_is_example", False)
    # ponytail: the development fixture unless a real evaluator is configured; _evaluator gives hornsim the patient's ear.
    real = bool(os.environ.get("HORN_STUDY_REAL_EVALUATOR"))
    return {
        "study_id": study_id,
        "mode": "personalized",
        "evaluation_mode": "real" if real else "development_fixture",
        "start": {"initiated_by": "user", "action": "start_study"},
        "hearing_profile": {
            "profile_id": f"patient_{run_id}",
            "source": "user_entered_test_results",
            "target_ear": target,
            "measurements": [
                {"ear": ear, "frequency_hz": float(hz), "threshold_db_hl": float(db)}
                for ear, ag in ags.items()
                for hz, db in sorted(ag.items(), key=lambda kv: float(kv[0]))
            ],
            "user_notes": " ".join(
                (["Example audiogram, not the patient's own test."] if example else [])
                + [f"{ear.capitalize()} ear thresholds at {', '.join(f'{f:g} Hz' for f in fs)} were not measured; "
                   "they repeat the nearest measured value." for ear, fs in filled.items()]
            ),
        },
        "needs_profile": {"free_text": "\n".join(notes)},
    }


def _evaluator(raw: dict[str, Any]) -> Any:
    """The study's evaluator. hornsim gets THIS patient's ear mesh — .env's HORNSIM_EAR_MESH is only the fallback."""
    from horn_study.evaluator_adapter import CallableEvaluator, evaluator_for

    if (
        raw["evaluation_mode"] != "real"
        or os.environ.get("HORN_STUDY_REAL_EVALUATOR") != "horn_study.hornsim_evaluator"
    ):
        return evaluator_for(raw["evaluation_mode"])
    from horn_study.hornsim_evaluator import HornsimConfig, HornsimEvaluator

    profile = raw["hearing_profile"]
    run_dir = patients_dir() / profile["profile_id"].removeprefix("patient_")
    # Per-ear layout (<run>/<side>/ear) first, then the older one-ear layout (<run>/ear).
    meshes = [run_dir / profile["target_ear"] / "ear" / "ear.ply", run_dir / "ear" / "ear.ply"]
    env = dict(os.environ)
    if mesh := next((m for m in meshes if m.is_file()), None):
        env["HORNSIM_EAR_MESH"] = str(mesh)
    hornsim = HornsimEvaluator(HornsimConfig.from_env(env))
    return CallableEvaluator(hornsim.get_evaluator_capabilities, hornsim.evaluate_experiment)


_warmed: set[str] = set()
# What prewarm built for each run: the evaluator and its capabilities (the hornsim describe, ~50 s on a busy machine).
# launch REUSES them: built again there, they sat between the patient's "yes" and the first research event, with the
# synchronous capability call blocking the whole server meanwhile.
_ready: dict[str, concurrent.futures.Future[tuple[Any, dict[str, Any]]]] = {}
MESH_WAIT_S = 600   # the ear mesh lands seconds after upload; a run that never makes one gives up here


def prewarm(run_id: str) -> None:
    """Does launch's slow first steps from the moment the run is created, so research starts on "yes": the model imports
    (~10 s cold) at once, then — as soon as the backend has written the target ear's mesh — that ear's earpiece limits (two
    probe builds, ~30 s on a busy machine, then cached on disk by the hornsim bridge). ONCE per run. Fire and forget: a
    failure here is reported by launch, where it matters."""
    if run_id in _warmed:
        return
    _warmed.add(run_id)
    ready: concurrent.futures.Future[tuple[Any, dict[str, Any]]] = concurrent.futures.Future()
    _ready[run_id] = ready

    def warm() -> None:
        try:
            from horn_study.llm import load_model

            for role in ("research", "coordinator", "interpreter"):
                load_model(role)
            # The job and its audiogram exist at create time; the mesh does NOT yet. Building the evaluator without it
            # falls back to .env's HORNSIM_EAR_MESH — someone else's ear, warmed for nothing.
            raw = study_request(run_id, f"{run_id}-warm", _patient(run_id), [])
            mesh = patients_dir() / run_id / raw["hearing_profile"]["target_ear"] / "ear" / "ear.ply"
            deadline = time.time() + MESH_WAIT_S
            while not mesh.is_file():
                if time.time() > deadline or _patient(run_id).get("status") == "error":
                    raise TimeoutError("no ear mesh for this run")
                time.sleep(0.5)
            evaluator = _evaluator(raw)
            ready.set_result((evaluator, evaluator.get_evaluator_capabilities()))
        except Exception as error:  # noqa: BLE001 — launch builds its own and reports a failure to the patient
            ready.set_exception(error)

    threading.Thread(target=warm, name=f"prewarm-{run_id}", daemon=True).start()


class _Known:
    """An evaluator whose capabilities are already in hand: run_study asks for them synchronously, on the event loop."""

    def __init__(self, inner: Any, capabilities: dict[str, Any]) -> None:
        self._inner, self._capabilities = inner, capabilities

    def get_evaluator_capabilities(self) -> dict[str, Any]:
        return self._capabilities

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def _ready_evaluator(raw: dict[str, Any], run_id: str | None) -> Any:
    """prewarm's evaluator when it built one (waiting for it WITHOUT blocking the loop if it is still building),
    otherwise a fresh one whose capability check runs in a thread."""
    ready = _ready.get(run_id or "")
    if ready is not None:
        try:
            return _Known(*await asyncio.wrap_future(ready))
        except Exception:  # noqa: BLE001 — the warm-up failed: build it here, where a failure reaches the patient
            pass
    evaluator = _evaluator(raw)
    return _Known(evaluator, await asyncio.to_thread(evaluator.get_evaluator_capabilities))


async def run(raw: dict[str, Any], run_id: str | None = None) -> None:
    """The study, as cli.py's run command builds it. Events land in <studies>/<study_id>/events.jsonl."""
    from horn_study.llm import load_model
    from horn_study.sources import HttpReader, default_search, make_http_client
    from horn_study.workflow import StudyDependencies, run_study

    evaluator = await _ready_evaluator(raw, run_id)
    async with make_http_client() as client:
        deps = StudyDependencies(
            evaluator=evaluator,
            research_model=load_model("research"),
            coordinator_model=load_model("coordinator"),
            interpreter_model=load_model("interpreter"),
            search=default_search(client),
            reader=HttpReader(client),
            studies_root=studies_dir(),
            research_only=True,
        )
        await run_study(raw, deps)


def launch(s: dict[str, Any]) -> None:
    """Starts the study for a session that just said yes. A failure to START is kept on the session."""
    study_id = f"{s['run_id']}-{int(time.time())}"
    try:
        raw = study_request(s["run_id"], study_id, _patient(s["run_id"]), s["notes"])
    except (ValueError, KeyError, OSError) as error:
        s["error"] = str(error)
        return
    s["study_id"] = study_id
    s["ear"] = raw["hearing_profile"]["target_ear"]
    run_id = s["run_id"]

    async def guarded() -> None:
        try:
            await run(raw, run_id)
        except Exception as error:
            # run_study records failures inside the study; this catches what happens before it starts (models, input).
            later = load(run_id)
            if later is not None:
                later["error"] = f"{type(error).__name__}: {error}"[:300]
                save(later)

    state.tasks[run_id] = asyncio.get_running_loop().create_task(guarded())


def findings(s: dict[str, Any]) -> list[str]:
    return [
        e["summary"] for e in events(s) if e["type"] in ("research.finding_added", "research.board_posted")
    ]


def patient_line(s: dict[str, Any]) -> str:
    return (
        json.dumps(_audiograms(_patient(s["run_id"])))
        + f" dB HL by ear and frequency (Hz); aid for the {s.get('ear')} ear"
    )


def report_facts(s: dict[str, Any]) -> str:
    """EVERYTHING the session measured, for the final report: session_line's summary plus every scene's numbers, every
    option's per-band gain and the picked earpiece's measured gain."""
    out = [session_line(s)]
    res = (s.get("sims") or {}).get("results") or []
    aided = (s.get("validation") or {}).get("aided") or []
    by = {x["id"]: x for x in s.get("scenes") or []}
    pct = lambda v: f"{round(100 * v)}%" if isinstance(v, (int, float)) else "n/a"  # noqa: E731
    if res:
        out.append("Every scene (speech or target sound audible: normal hearing / this ear / with the picked aid):")
        for i, r in enumerate(res):
            sc = by.get(r["id"], {})
            src = "; ".join(f"{x['role']} '{x.get('sound', 'speech')}' at {x['az']}° {x['level_db']} dB" + (f" touching the ear ({x['dist_mm']} mm)" if x.get("dist_mm") else "") for x in sc.get("sources", []))
            out.append(f"- {r['name']} (weight {r['weight']}; {src}): {pct(r['sii_healthy'])} / {pct(r['sii_unaided'])} / {pct(aided[i] if i < len(aided) else None)}")
    hz = (160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000)
    band = lambda g: ", ".join(f"{f} Hz {v:+.1f}" for f, v in zip(hz, g))  # noqa: E731
    for i, o in enumerate(s.get("options") or [], 1):
        if o.get("gain_mean_db"):
            out.append(f"option {i} ({o['id']}) mean gain dB: {band(o['gain_mean_db'])}")
    if (s.get("validation") or {}).get("gain_db"):
        out.append(f"picked earpiece, 3D wave simulation gain over the open ear, dB: {band(s['validation']['gain_db'])}")
    out.extend(earpiece_facts(s.get("earpiece")))
    return "\n".join(out)


_KEY_BANDS = re.compile(r"(:\s*)?\b[Mm]eets \d+ of \d+ key bands,?\s*")


def no_key_bands(text: str) -> str:
    """An option's reason without "meets N of M key bands": sessions saved before scene_design stopped writing it still
    carry it, and the patient never sees that jargon (frontend components/AidOptions.tsx strips it the SAME way)."""
    return _KEY_BANDS.sub(lambda m: ", " if m.group(1) else "", text)


def session_line(s: dict[str, Any]) -> str:
    """The simulation half so far, in a few lines, for the model's answers and the report."""
    out = [f"stage {s['stage']}"]
    if s.get("scenes"):
        out.append(
            f"{len(s['scenes'])} scenes: " + "; ".join(f"{x['name']} ({x['why']})" for x in s["scenes"][:12])
        )
    if s.get("sims"):
        out.append(f"unaided simulations: {s['sims'].get('summary', '')}")
    for i, o in enumerate(s.get("options") or [], 1):
        out.append(f"option {i} ({o.get('id')}): {no_key_bands(o.get('reason', ''))}")
    if s.get("picked"):
        o = next((o for o in s.get("options") or [] if o.get("id") == s["picked"]), {})
        out.append(f"patient picked {s['picked']}: {no_key_bands(o.get('reason', ''))}")
    if s.get("validation"):
        out.append(f"validation: {s['validation'].get('summary', '')}")
    return "\n".join(out)


PHOTOS = (".jpg", ".jpeg", ".png", ".webp")


def agent_ctx(s: dict[str, Any]) -> dict[str, Any]:
    """What the lead agent's data tools (lead_tools.session_tools) read: the live session and the patient's backend folder.
    The session is re-read from disk on each call, so a tool sees what the dashboard has saved since the job began."""
    run_id = s["run_id"]
    return {"run_id": run_id, "ear": s.get("ear"), "patient_dir": patients_dir() / run_id, "session": lambda: load(run_id)}


def evidence_dir(s: dict[str, Any]) -> Path | None:
    """The study's evidence tree for the lead, with the patient's photos copied into photos/ (once each).

    ABSENT until research writes its first file: ArtifactStore.create refuses a study folder that already exists.
    """
    if not s.get("study_id"):
        return None
    root = studies_dir() / s["study_id"] / "evidence"
    if not root.is_dir():
        return None
    patient = patients_dir() / s["run_id"]
    for src in patient.rglob("*"):
        # waves/ holds hundreds of simulation frames, not evidence — NEVER copied.
        if src.suffix.lower() in PHOTOS and "waves" not in src.parts and src.is_file():
            dst = root / "photos" / src.relative_to(patient)
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
    return root


async def reply_after_launch(s: dict[str, Any]) -> str:
    from horn_study.llm import load_model

    evs = events(s)
    st = status(s, evs)
    if st == "error":
        return f"Research could not start: {s['error']}"
    try:
        return await lead.answer(
            load_model("interpreter"),
            s["messages"][-12:],
            run_id=s["run_id"],
            ctx=agent_ctx(s),
            patient=patient_line(s),
            notes=s["notes"],
            status=st,
            events=[{"component": e["component"], "summary": e["summary"]} for e in evs],
            board=board(evs),
            session=session_line(s),
            evidence=evidence_dir(s),
        )
    except Exception as error:
        return f"I can't answer right now ({type(error).__name__}). The study is {st}."


def _scenes_path(run_id: str) -> Path:
    return _path(run_id).with_suffix(".scenes.json")


def start_picking(s: dict[str, Any], n: int) -> None:
    """The scene picker in the background: its result goes to its OWN file (advance() reads it), so it never
    races post_lead saving the session."""
    from horn_study.llm import load_model

    out = _scenes_path(s["run_id"])
    out.unlink(missing_ok=True)
    patient, notes, found = patient_line(s), list(s["notes"]), findings(s)
    picker = lead.pick_scenes

    async def pick() -> None:
        try:
            scenes = await picker(
                load_model("coordinator"), n, patient=patient, notes=notes, findings=found
            )
            out.write_text(json.dumps({"scenes": scenes}))
        except Exception as error:
            out.write_text(json.dumps({"error": f"{type(error).__name__}: {error}"[:300]}))

    state.tasks[f"{s['run_id']}:scenes"] = asyncio.get_running_loop().create_task(pick())


def advance(s: dict[str, Any]) -> bool:
    """Moves a stage that waits on background work: research finishing, or the scene picker. True if it moved."""
    if s["stage"] == "launched" and status(s) == "completed":
        s["stage"] = "sim_ready"
        s["messages"].append({"role": "lead", "text": lead.SIM_READY})
        return True
    p = _scenes_path(s["run_id"])
    if s["stage"] == "sim_prep" and p.exists():
        got = json.loads(p.read_text())
        if "scenes" in got:
            s["stage"], s["scenes"] = "sim_running", got["scenes"]
            s["messages"].append({"role": "lead", "text": lead.SIM_RUNNING})
        else:
            s["stage"] = "sim_count"
            s["messages"].append(
                {
                    "role": "lead",
                    "text": f"I couldn't set up the simulations ({got['error']}). {lead.SIM_COUNT}",
                }
            )
        p.unlink()
        return True
    if s["stage"] == "sim_prep" and not state.tasks.get(f"{s['run_id']}:scenes"):
        # The picker died with a server restart: ask again rather than wait forever.
        s["stage"] = "sim_count"
        s["messages"].append({"role": "lead", "text": f"The setup was interrupted. {lead.SIM_COUNT}"})
        return True
    return False


def on_event(s: dict[str, Any], event: str, data: dict[str, Any]) -> str:
    """Applies one dashboard step; returns the lead's line for it."""
    if event not in lead.EVENTS:
        raise HTTPException(400, f"unknown event {event}")
    want, then = lead.EVENTS[event]
    if s["stage"] != want:
        raise HTTPException(409, f"{event} arrives in stage {want}, not {s['stage']}")
    s["stage"] = then
    if event == "sims_done":
        s["sims"] = data
        return lead.DESIGN_READY
    if event == "options":
        s["options"] = data.get("options") or []
        return lead.OPTIONS
    if event == "design_failed":
        return f"The design failed ({str(data.get('error', 'unknown error'))[:200]}). {lead.ASK_DESIGN}"
    if event == "picked":
        s["picked"] = data.get("design_id")
        start_earpiece(s)
        return lead.VALIDATING
    s["validation"] = data
    return f"{data.get('summary', 'Validation finished.')} {lead.FINAL}"


# -- routes -----------------------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/sessions")
def sessions() -> list[dict[str, Any]]:
    d = studies_dir() / "sessions"
    found = [json.loads(p.read_text()) for p in d.glob("*.json")] if d.exists() else []
    return sorted((view(s) for s in found), key=lambda v: -v["updated_at"])


@app.get("/lead/{run_id}")
def get_lead(run_id: str) -> dict[str, Any]:
    s = load(run_id)
    if s is None:
        raise HTTPException(404, "no session")
    if advance(s):
        save(s)
    return view(s)


def fresh(run_id: str) -> dict[str, Any]:
    return {"run_id": run_id, "created_at": time.time(), "stage": "new", "notes": [], "messages": []}


@app.post("/sessions/{run_id}")
def create_session(run_id: str) -> dict[str, Any]:
    """Called when a run starts, so the session exists (and is listed) before the lead speaks. Idempotent."""
    s = load(run_id)
    if s is None:
        s = fresh(run_id)
        save(s)
    # The run was JUST created: start launch's slow setup now, minutes before the patient says yes.
    prewarm(run_id)
    return view(s)


REPLY_DELAY_S = (1.0, 3.0)


async def _hold(since: float) -> None:
    """Holds a model's reply until a random 1-3 s have passed since `since`, so the "…" always shows: a fast error line would
    otherwise land instantly. Only the time its own call has not already taken."""
    await asyncio.sleep(max(0.0, random.uniform(*REPLY_DELAY_S) - (time.monotonic() - since)))


@app.post("/lead/{run_id}")
async def post_lead(run_id: str, body: Message) -> dict[str, Any]:
    s = load(run_id) or fresh(run_id)
    t0 = time.monotonic()
    advance(s)
    if body.event:
        s["messages"].append({"role": "lead", "text": on_event(s, body.event, body.data)})
        save(s)
        return view(s)
    text = body.message[:2000].strip()
    # "" opens a NEW session and only re-reads an existing one — a reload must never count as a note.
    if not text and s["stage"] != "new":
        save(s)
        return view(s)
    if text:
        s["messages"].append({"role": "patient", "text": text})
    model = False   # True once a model writes the reply (reply_after_launch, final_report)
    if s["stage"] in ("new", "opening", "begin"):
        was = s["stage"]
        reply, s["stage"], note = lead.step(s["stage"], text)
        if was == "new":
            prewarm(s["run_id"])
        if note:
            s["notes"].append(note)
        if s["stage"] == "launched":
            launch(s)
            if s.get("error"):
                reply = f"Research could not start: {s['error']}"
    elif s["stage"] == "launched" and s.get("study_id") and lead.moving_on(text):
        # The investigators wrap up in the background; the scene picker reads whatever they posted by then.
        from horn_study.research import stop_research

        stop_research(s["study_id"])
        s["stage"], reply = "sim_ready", lead.MOVE_ON
    else:
        fixed, s["stage"], ask = lead.flow(s["stage"], text)
        if s["stage"] == "sim_prep":
            start_picking(s, lead.count(text) or 1)
        if s["stage"] == "done":
            fixed = await final_report(s)
            model = True
        reply = fixed or await reply_after_launch(s)
        model = model or not fixed
        if fixed is None and ask:
            reply = f"{reply} {ask}"
    if model:
        await _hold(t0)
    s["messages"].append({"role": "lead", "text": reply})
    save(s)
    return view(s)


def earpiece_summary(record: dict[str, Any]) -> dict[str, Any]:
    """What the session keeps of earpiece.json: the chosen build, its sizes and where it departs from the tested design."""
    chosen = record.get("chosen") or {}
    build = next((b for b in record.get("builds", []) if b["design_id"] == chosen.get("design_id")), {})
    scalar = lambda d: {k: v for k, v in (d or {}).items() if isinstance(v, (int, float, str)) and not isinstance(v, bool)}  # noqa: E731
    return {
        "status": record.get("status"),
        "design_id": chosen.get("design_id"),
        "explanation": chosen.get("explanation") or "",
        "chosen_by": chosen.get("chosen_by"),
        "sizes": {k: {"design_id": v["design_id"], "ok": v["ok"], "fit_offset_mm": v.get("fit_offset_mm")} for k, v in (record.get("sizes") or {}).items()},
        "shaping": scalar(build.get("shaping")),
        "geometry": scalar((build.get("report") or {}).get("geometry")),
        "locked": record.get("locked"),
        "departures": record.get("departures_from_study") or [],
    }


def earpiece_facts(e: dict[str, Any] | None) -> list[str]:
    """The custom earpiece, as report_facts lines. Nothing while it is building or when it failed (the report says so)."""
    if not e:
        return []
    if e.get("status") != "built":
        return [f"custom earpiece: not built ({e.get('status')}{': ' + e['error'] if e.get('error') else ''}); the printable file is the picked design as the designer made it"]
    sizes = ", ".join(f"{k} {'built' if v['ok'] else 'FAILED'}" for k, v in e["sizes"].items())
    return [
        f"custom earpiece {e['design_id']} (the picked design shaped for this ear; sizes {sizes}): {e.get('explanation') or 'no explanation given'}",
        f"custom earpiece shaping dials: {json.dumps(e.get('shaping'))}",
        f"custom earpiece geometry, mm and mm2: {json.dumps(e.get('geometry'))}",
        f"numbers fixed from the tested design: {json.dumps(e.get('locked'))}; departures from it: {'; '.join(e.get('departures') or []) or 'none'}",
    ]


def start_earpiece(s: dict[str, Any]) -> None:
    """The picked design goes to the lead Deep Agent to be shaped and built, in the background while the patient validates."""
    if not s.get("study_id") or not s.get("picked"):
        return
    s["earpiece"] = {"status": "building"}
    state.earpieces[s["run_id"]] = asyncio.get_running_loop().create_task(earpiece_job(s["run_id"]))


async def earpiece_job(run_id: str) -> None:
    """lead.custom_earpiece for the session's picked design; the outcome (or the failure) lands in s["earpiece"]."""
    from horn_study.llm import load_model

    s = load(run_id)
    if s is None:
        return
    try:
        run_dir = patients_dir() / run_id
        ear_dir = run_dir / s["ear"] if s.get("ear") and (run_dir / s["ear"]).is_dir() else run_dir
        evidence = evidence_dir(s)
        record = await lead.custom_earpiece(
            load_model("interpreter"),
            run_id=run_id,
            ctx=agent_ctx(s),
            study_dir=studies_dir() / s["study_id"],
            ear_dir=ear_dir,
            picked=s["picked"],
            context={"patient": patient_line(s), "notes": s["notes"]},
            evidence=evidence,
        )
        summary = earpiece_summary(record)
        if evidence is not None:   # the lead and the report read it from their file system
            (evidence / "earpiece").mkdir(exist_ok=True)
            (evidence / "earpiece" / "record.md").write_text(
                "# Custom earpiece\n\n" + "\n".join(earpiece_facts(summary)) + "\n", encoding="utf-8")
    except Exception as error:  # the patient keeps the picked design's own print file
        summary = {"status": "failed", "error": f"{type(error).__name__}: {error}"[:300]}
    later = load(run_id)
    if later is not None:
        later["earpiece"] = summary
        save(later)


EARPIECE_WAIT_S = 600   # the report waits this long for a build still running when the patient asks for it


async def final_report(s: dict[str, Any]) -> str:
    from horn_study.llm import load_model

    task = state.earpieces.get(s["run_id"])
    if task is not None and not task.done():
        with contextlib.suppress(Exception):   # a slow or failed build must not cost the patient the report
            await asyncio.wait_for(asyncio.shield(task), EARPIECE_WAIT_S)
    if (later := load(s["run_id"])) is not None and later.get("earpiece"):
        s["earpiece"] = later["earpiece"]
    try:
        s["report"] = await lead.write_report(
            load_model("interpreter"),
            run_id=s["run_id"],
            ctx=agent_ctx(s),
            patient=patient_line(s),
            notes=s["notes"],
            findings=findings(s),
            session=report_facts(s),
            evidence=evidence_dir(s),
        )
        return lead.DONE
    except Exception as error:
        s["stage"] = "final"
        return f"I couldn't write the report ({type(error).__name__}). {lead.ASK_FINAL}"


UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@app.get("/langsmith/search")
def langsmith_search(trace_id: str, query: str) -> dict[str, Any]:
    """What one search actually returned, read back from its LangSmith tool run — for studies whose events
    predate saving the hits. `query` may be the event summary's 120-character prefix."""
    if not UUID.match(trace_id) or not query.strip():
        raise HTTPException(422, "trace_id is a UUID and query is required")
    try:
        found = _search_run(trace_id, query.strip(), os.environ.get("LANGSMITH_PROJECT") or "default")
    except Exception as e:
        raise HTTPException(502, f"LangSmith is unreachable: {type(e).__name__}") from e
    if found is None:
        raise HTTPException(404, "no search_literature run with that query in this trace")
    return found


@app.get("/langsmith/{ls_run_id}")
def langsmith_run(ls_run_id: str, trace_id: str | None = None) -> RedirectResponse:
    """Redirect to a run in the LangSmith UI. The URL needs the org and project ids, which only the API key can
    look up — so the browser comes here instead of building it."""
    if not UUID.match(ls_run_id) or (trace_id and not UUID.match(trace_id)):
        raise HTTPException(422, "run and trace ids are UUIDs")
    project = os.environ.get("LANGSMITH_PROJECT") or "default"
    try:
        url = _run_url(ls_run_id, project)
    except Exception as e:
        raise HTTPException(502, f"LangSmith is unreachable: {type(e).__name__}") from e
    return RedirectResponse(url + (f"&trace_id={trace_id}" if trace_id else ""))


def _run_url(run_id: str, project: str) -> str:
    import warnings
    from types import SimpleNamespace

    from langsmith import Client

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Client().get_run_url(run=SimpleNamespace(id=run_id), project_name=project)


HIT = re.compile(r"^\d+\. (?P<title>.*) \((?P<year>[^()]*)\) - (?P<rest>.*)$")


def parse_search(text: str) -> dict[str, Any]:
    """The search_literature tool's reply (research.py ResearchSession.search_literature) back into hits.
    Tied to THAT format: change one and the other, or old studies' search modals come back empty."""
    query, hits, notes = "", [], []
    for line in text.splitlines():
        if line.startswith("Results for: "):
            query = line.removeprefix("Results for: ")
        elif m := HIT.match(line):
            authors, _, venue = m["rest"].partition(" - ")
            year = m["year"]
            hits.append(
                {
                    "title": m["title"],
                    "year": None if year == "n.d." else year,
                    "authors": None if authors == "unknown authors" else authors,
                    "venue": venue or None,
                }
            )
        elif hits and line.startswith("   url: "):
            url, _, access = line.removeprefix("   url: ").rpartition(" (")
            hits[-1].update(url=url, open_access=access.startswith("open access"))
        elif hits and line.startswith("   snippet: "):
            snip = line.removeprefix("   snippet: ")
            hits[-1]["snippet"] = None if snip == "no abstract available" else snip
        elif line.startswith("Note: "):
            notes.append(line.removeprefix("Note: "))
    return {"query": query, "results": hits, "notes": notes}


def _search_run(trace_id: str, query: str, project: str) -> dict[str, Any] | None:
    import warnings

    from langsmith import Client

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        runs = Client().list_runs(
            project_name=project, trace_id=trace_id, filter='eq(name, "search_literature")'
        )
        for run in runs:
            if not str((run.inputs or {}).get("query", "")).startswith(query):
                continue
            out = (run.outputs or {}).get("output")
            text = out.get("content", "") if isinstance(out, dict) else str(out or "")
            return {**parse_search(text), "langsmith": {"run_id": str(run.id), "trace_id": str(run.trace_id)}}
    return None


@app.get("/lead/{run_id}/events")
def get_events(run_id: str) -> dict[str, Any]:
    s = load(run_id)
    if s is None:
        raise HTTPException(404, "no session")
    evs = events(s)
    return {"status": status(s, evs), "study_id": s.get("study_id"), "events": evs}


@app.get("/lead/{run_id}/board")
def get_board(run_id: str) -> dict[str, Any]:
    s = load(run_id)
    if s is None:
        raise HTTPException(404, "no session")
    evs = events(s)
    return {"status": status(s, evs), "posts": board(evs)}
