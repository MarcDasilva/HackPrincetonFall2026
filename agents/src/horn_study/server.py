"""HTTP front for the lead, for the dashboard (frontend/lib/lead.ts).

cd agents && uv run uvicorn horn_study.server:app --port 8010

One session per backend run ID, saved as <studies>/sessions/<run_id>.json, so a conversation and
its study survive a restart and the dashboard's session picker can switch between them. A "yes"
starts run_study (the four deep-agent investigators, then plan, experiments, report) in the
background; its events.jsonl is what GET /lead/{id}/events serves to the research boxes.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
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


def study_request(run_id: str, study_id: str, job: dict[str, Any], notes: list[str]) -> dict[str, Any]:
    ags = _audiograms(job)
    if not ags:
        raise ValueError("this patient has no audiogram numbers to study")
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
            "user_notes": "Example audiogram, not the patient's own test." if example else "",
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


async def run(raw: dict[str, Any]) -> None:
    """The study, as cli.py's run command builds it. Events land in <studies>/<study_id>/events.jsonl."""
    from horn_study.llm import load_model
    from horn_study.sources import HttpReader, default_search, make_http_client
    from horn_study.workflow import StudyDependencies, run_study

    async with make_http_client() as client:
        deps = StudyDependencies(
            evaluator=_evaluator(raw),
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
            await run(raw)
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
        out.append(f"option {i} ({o.get('id')}): {o.get('reason', '')}")
    if s.get("picked"):
        out.append(f"patient picked {s['picked']}")
    if s.get("validation"):
        out.append(f"validation: {s['validation'].get('summary', '')}")
    return "\n".join(out)


PHOTOS = (".jpg", ".jpeg", ".png", ".webp")


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
            load_model("coordinator"),
            s["messages"][-12:],
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

    async def pick() -> None:
        try:
            scenes = await lead.pick_scenes(
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
    return view(s)


@app.post("/lead/{run_id}")
async def post_lead(run_id: str, body: Message) -> dict[str, Any]:
    s = load(run_id) or fresh(run_id)
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
    if s["stage"] in ("new", "opening", "begin"):
        reply, s["stage"], note = lead.step(s["stage"], text)
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
        reply = fixed or await reply_after_launch(s)
        if fixed is None and ask:
            reply = f"{reply} {ask}"
    s["messages"].append({"role": "lead", "text": reply})
    save(s)
    return view(s)


async def final_report(s: dict[str, Any]) -> str:
    from horn_study.llm import load_model

    try:
        s["report"] = await lead.write_report(
            load_model("interpreter"),
            patient=patient_line(s),
            notes=s["notes"],
            findings=findings(s),
            session=session_line(s),
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
