"""The lead's HTTP routes, as the dashboard calls them (frontend/lib/lead.ts)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from horn_study import lead, server
from horn_study.contracts import StudyRequest
from horn_study.lead import LAUNCH, OPENING

ONE_EAR = {
    "request": {"side": "left", "audiogram_db_hl": {"500": 20, "4000": 55}, "audiogram_is_example": False}
}
TWO_EARS = {"request": {"left": {"audiogram_db_hl": {"500": 10}}, "right": {"audiogram_db_hl": {"500": 40}}}}


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[dict[str, Any]]]:
    monkeypatch.setenv("HORN_STUDY_DIR", str(tmp_path / "studies"))
    monkeypatch.setenv("HORN_STUDY_PATIENTS_DIR", str(tmp_path / "patients"))
    monkeypatch.delenv("HORN_STUDY_REAL_EVALUATOR", raising=False)
    # A real warm-up loads the models and builds the ear's limits in a thread: slow, and nothing here checks it.
    monkeypatch.setattr(server, "prewarm", lambda run_id: None)
    monkeypatch.setattr(server, "REPLY_DELAY_S", (0.0, 0.0))   # a model reply's "..." hold: only its own test waits
    (tmp_path / "patients" / "run1").mkdir(parents=True)
    (tmp_path / "patients" / "run1" / "job.json").write_text(json.dumps(ONE_EAR))
    started: list[dict[str, Any]] = []

    async def fake_run(raw: dict[str, Any], run_id: str | None = None) -> None:
        started.append(raw)
        d = tmp_path / "studies" / raw["study_id"]
        d.mkdir(parents=True)
        lines = [
            {"type": "research.agent_started", "component": "hearing_research", "summary": "started"},
            {
                "type": "research.board_posted",
                "component": "hearing_research",
                "summary": "Gain at 2-4 kHz",
                "data": {"investigator": "hearing_research", "headline": "Gain at 2-4 kHz", "detail": "d"},
            },
            {"type": "study.completed", "component": "workflow", "summary": "done"},
        ]
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines))

    monkeypatch.setattr(server, "run", fake_run)
    server.state.tasks.clear()
    return TestClient(server.app), started


def test_lead_route_round_trip(api: tuple[TestClient, list[dict[str, Any]]]) -> None:
    """Catches the route shape drifting from what frontend/lib/lead.ts reads."""
    r = api[0].post("/lead/run1", json={"message": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == OPENING
    assert body["awaiting_launch"]
    assert not body["launch_requested"]
    assert body["status"] == "none"


def test_bad_run_id_is_rejected(api: tuple[TestClient, list[dict[str, Any]]]) -> None:
    """Catches a run ID walking out of the sessions folder — it is joined onto a path."""
    c = api[0]
    assert c.post("/lead/..%2Fx", json={"message": ""}).status_code in (400, 404)
    assert c.post("/lead/a.b", json={"message": ""}).status_code == 400


def test_reopening_a_session_is_not_a_note(api: tuple[TestClient, list[dict[str, Any]]]) -> None:
    """Catches a page reload (the dashboard posts "" again) being stored as a patient note or advancing the script."""
    c = api[0]
    c.post("/lead/run1", json={"message": ""})
    c.post("/lead/run1", json={"message": "I run a lot"})
    again = c.post("/lead/run1", json={"message": ""}).json()
    assert again["reply"] == "Noted. May I begin?"
    assert server.load("run1")["notes"] == ["I run a lot"]


def test_yes_starts_the_study_and_events_are_served(api: tuple[TestClient, list[dict[str, Any]]]) -> None:
    """Catches a yes that never reaches run_study, a request run_study would reject, or events the boxes cannot read."""
    c, started = api
    c.post("/lead/run1", json={"message": ""})
    c.post("/lead/run1", json={"message": "I run a lot"})
    out = c.post("/lead/run1", json={"message": "yes"}).json()
    assert out["reply"] == LAUNCH
    assert out["launch_requested"]
    assert len(started) == 1
    request = StudyRequest.model_validate(started[0])
    assert request.hearing_profile
    assert request.hearing_profile.target_ear == "left"
    assert request.needs_profile
    assert request.needs_profile.free_text == "I run a lot"
    evs = c.get("/lead/run1/events").json()
    assert evs["status"] == "completed"
    assert [e["component"] for e in evs["events"]] == ["hearing_research", "hearing_research", "workflow"]
    # The info board the lead reads: the agents' submit_finding posts, served on their own.
    assert [p["headline"] for p in c.get("/lead/run1/board").json()["posts"]] == ["Gain at 2-4 kHz"]


def test_sessions_survive_a_restart(api: tuple[TestClient, list[dict[str, Any]]]) -> None:
    """Catches sessions living only in memory — the session picker must list and reopen them after a restart."""
    c = api[0]
    c.post("/lead/run1", json={"message": ""})
    server.state.tasks.clear()
    listed = c.get("/sessions").json()
    assert [s["run_id"] for s in listed] == ["run1"]
    assert c.get("/lead/run1").json()["reply"] == OPENING
    assert c.get("/lead/nope").status_code == 404


def test_two_ears_target_the_worse_one() -> None:
    """Catches a two-ear patient (the current job.json layout) failing to build a request."""
    raw = server.study_request("p", "p-1", TWO_EARS, [])
    request = StudyRequest.model_validate(raw)
    assert request.hearing_profile
    assert request.hearing_profile.target_ear == "right"
    # One measured point per ear: every HASPI frequency repeats it.
    assert len(request.hearing_profile.measurements) == 2 * len(server.HASPI_HZ)


def test_in_app_hearing_test_covers_every_haspi_frequency() -> None:
    """Catches research never starting for a patient from the in-app test (500-4000 Hz): the real evaluator rejected
    the request for missing 250 Hz and 6 kHz, and the dashboard sat on "Waiting to start"."""
    job = {"request": {"left": {"audiogram_db_hl": {"500": 20, "1000": 20, "2000": 30, "4000": 40}},
                       "right": {"audiogram_db_hl": {"500": 10, "1000": 20, "2000": 30, "4000": 40}}}}
    hp = StudyRequest.model_validate(server.study_request("p", "p-1", job, [])).hearing_profile
    assert hp
    got = {(m.ear, m.frequency_hz): m.threshold_db_hl for m in hp.measurements}
    assert {f for e, f in got if e == "left"} == set(server.HASPI_HZ)
    assert got[("left", 250.0)] == 20 and got[("left", 6000.0)] == 40 and got[("right", 250.0)] == 10
    assert "250 Hz, 6000 Hz were not measured" in hp.user_notes


def test_a_study_that_fails_after_launch_says_so() -> None:
    """Catches the launch line staying up after the study failed in the background: the patient waits forever."""
    s = {"run_id": "r", "stage": "launched", "messages": [{"role": "lead", "text": LAUNCH}], "error": "InputRejected: bad"}
    assert server.view(s)["reply"] == "Research could not start: InputRejected: bad"


def test_a_started_run_is_a_session_before_the_lead_speaks(
    api: tuple[TestClient, list[dict[str, Any]]],
) -> None:
    """Catches a new run missing from the session picker until its ear cards clear, or a repeat create wiping the chat."""
    c = api[0]
    created = c.post("/sessions/run1").json()
    assert created["stage"] == "new"
    assert created["reply"] == ""
    assert [x["run_id"] for x in c.get("/sessions").json()] == ["run1"]
    assert c.post("/lead/run1", json={"message": ""}).json()["reply"] == OPENING
    assert c.post("/sessions/run1").json()["reply"] == OPENING


def test_langsmith_link_redirects_and_refuses_non_uuids(api, monkeypatch):
    """Catches a trace row's link breaking or turning into an open redirect: only UUIDs are accepted, and the
    redirect carries the trace id so LangSmith opens the run inside its trace."""
    client, _ = api
    monkeypatch.setattr(
        server, "_run_url", lambda run_id, project: f"https://smith.example/r/{run_id}?poll=true"
    )
    rid, tid = "01a1dc4a-1130-7221-9b36-58c2fe56f16f", "01a1dc4b-1976-734a-b614-ac90df34531f"
    r = client.get(f"/langsmith/{rid}", params={"trace_id": tid}, follow_redirects=False)
    assert (
        r.status_code == 307
        and r.headers["location"] == f"https://smith.example/r/{rid}?poll=true&trace_id={tid}"
    )
    assert client.get("/langsmith/https:%2F%2Fevil.example", follow_redirects=False).status_code in (404, 422)
    assert (
        client.get(f"/langsmith/{rid}", params={"trace_id": "x"}, follow_redirects=False).status_code == 422
    )


def test_search_lookup_needs_a_trace_and_says_when_nothing_matches(api, monkeypatch):
    """Catches the search modal hanging on a bad lookup: a malformed trace id is refused, a query with no
    matching tool run is a 404 (the modal then says so), and a match comes back as-is."""
    client, _ = api
    tid = "01a1dc4a-1130-7221-9b36-58c2fe56f16f"
    monkeypatch.setattr(
        server,
        "_search_run",
        lambda t, q, p: {"query": q, "results": [], "notes": []} if q == "hit" else None,
    )
    assert client.get("/langsmith/search", params={"trace_id": "x", "query": "hit"}).status_code == 422
    assert client.get("/langsmith/search", params={"trace_id": tid, "query": "miss"}).status_code == 404
    assert client.get("/langsmith/search", params={"trace_id": tid, "query": "hit"}).json()["query"] == "hit"


def test_the_simulation_half_runs_in_order(
    api: tuple[TestClient, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches the lead skipping a gate the patient must pass: ready? -> how many -> watch -> design -> pick ->
    validate -> report, with each dashboard step accepted ONLY in its own stage."""
    c, _ = api
    picked: list[int] = []

    async def pick(_model: Any, n: int, **_: Any) -> list[dict[str, Any]]:
        picked.append(n)
        return [{"id": f"s{i}", "name": f"scene {i}", "why": "w", "sources": []} for i in range(n)]

    async def report(_model: Any, **_: Any) -> str:
        return "the report"

    monkeypatch.setattr(lead, "pick_scenes", pick)
    monkeypatch.setattr(lead, "write_report", report)
    monkeypatch.setattr("horn_study.llm.load_model", lambda role: None)
    c.post("/lead/run1", json={"message": ""})
    c.post("/lead/run1", json={"message": "no"})  # launches; the fake study is already completed
    out = c.get("/lead/run1").json()
    assert (out["stage"], out["reply"]) == ("sim_ready", lead.SIM_READY)
    assert c.post("/lead/run1", json={"message": "yes"}).json()["reply"] == lead.SIM_COUNT
    assert c.post("/lead/run1", json={"message": "a thousand"}).json()["reply"] == lead.COUNT_AGAIN
    assert c.post("/lead/run1", json={"message": "40"}).json()["stage"] == "sim_prep"
    # The picker runs on TestClient's portal loop, in the background like the real server.
    for _ in range(100):
        out = c.get("/lead/run1").json()
        if out["stage"] != "sim_prep":
            break
        time.sleep(0.01)
    assert (out["stage"], out["reply"], len(out["scenes"]), picked) == (
        "sim_running",
        lead.SIM_RUNNING,
        40,
        [40],
    )
    assert c.post("/lead/run1", json={"event": "picked"}).status_code == 409
    steps = [
        ("sims_done", {"summary": "s"}, "design_ready"),
        ("options", {"options": [{"id": "grid1", "reason": "r"}] * 4}, "options"),
        ("picked", {"design_id": "grid1"}, "validating"),
        ("validated", {"summary": "Helped in 30 of 40 scenes."}, "final"),
    ]
    for event, data, stage in steps:
        if event == "options":
            assert c.post("/lead/run1", json={"message": "yes"}).json()["stage"] == "designing"
        assert c.post("/lead/run1", json={"event": event, "data": data}).json()["stage"] == stage
    out = c.post("/lead/run1", json={"message": "report please"}).json()
    assert (out["stage"], out["report"], out["picked"]) == ("done", "the report", "grid1")


def test_hornsim_study_uses_the_target_ears_own_mesh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A study scored on the OTHER ear, or on .env's fallback mesh, designs an aid for an ear the patient doesn't have.
    from horn_study import hornsim_evaluator

    monkeypatch.setenv("HORN_STUDY_PATIENTS_DIR", str(tmp_path))
    monkeypatch.setenv("HORN_STUDY_REAL_EVALUATOR", "horn_study.hornsim_evaluator")
    monkeypatch.setenv("HORNSIM_EAR_MESH", "/fallback/ear.ply")
    for side in ("left", "right"):
        (tmp_path / "run1" / side / "ear").mkdir(parents=True)
        (tmp_path / "run1" / side / "ear" / "ear.ply").write_text("")
    seen: list[str] = []
    monkeypatch.setattr(
        hornsim_evaluator.HornsimConfig,
        "from_env",
        classmethod(lambda cls, env: seen.append(env["HORNSIM_EAR_MESH"])),
    )
    monkeypatch.setattr(hornsim_evaluator, "HornsimEvaluator", lambda config: hornsim_evaluator)
    raw = server.study_request("run1", "s1", TWO_EARS, [])
    server._evaluator(raw)
    assert seen == [str(tmp_path / "run1" / "right" / "ear" / "ear.ply")]


def test_the_opening_question_starts_the_slow_setup(
    api: tuple[TestClient, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches research starting late: the ear's earpiece limits and the model imports ran only after "yes", so the
    boxes sat on "Waiting to start" for 10-40 s. The lead's first line is the fallback trigger for a session made before
    create_session warmed it."""
    warmed: list[str] = []
    monkeypatch.setattr(server, "prewarm", warmed.append)
    c, _ = api
    c.post("/lead/run1", json={"message": ""})
    c.post("/lead/run1", json={"message": ""})
    assert warmed == ["run1"]


def test_creating_the_run_starts_the_slow_setup(
    api: tuple[TestClient, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches the warm-up waiting for the lead's first line: the run's creation is the earliest point, so it starts there."""
    warmed: list[str] = []
    monkeypatch.setattr(server, "prewarm", warmed.append)
    api[0].post("/sessions/run1")
    assert warmed == ["run1"]


def test_prewarm_runs_once_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches every lead poll and session create starting another warm-up thread (each a subprocess plus probe builds)."""
    started: list[str] = []
    monkeypatch.setattr(server.threading, "Thread", lambda target, name, daemon: type("T", (), {"start": lambda self: started.append(name)})())
    monkeypatch.setattr(server, "_warmed", set())
    server.prewarm("r1")
    server.prewarm("r1")
    assert started == ["prewarm-r1"]


def test_move_on_cuts_research_short(api: tuple[TestClient, list[dict[str, Any]]]) -> None:
    """Catches "move on" going to the model as a question while the patient waits on research to finish."""
    from horn_study import research

    s = server.fresh("run1") | {"stage": "launched", "study_id": "run1-1"}
    server.save(s)
    out = api[0].post("/lead/run1", json={"message": "let's move on"}).json()
    assert out["reply"] == lead.MOVE_ON
    assert server.load("run1")["stage"] == "sim_ready"
    assert "run1-1" in research._STOPPED
    assert not lead.moving_on("what's next?")
    assert not lead.moving_on("should I continue wearing my old aid at the gym")


def test_a_model_turn_never_lands_instantly(api: tuple[TestClient, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches a model turn that finishes at once (a recorded report, a fast error) appearing with no "..." beat, in ANY mode."""
    c, _ = api
    pauses: list[float] = []

    async def fake_sleep(t: float) -> None:
        pauses.append(t)

    async def instant(*_: Any, **__: Any) -> str:
        return "answer"

    monkeypatch.setattr("horn_study.server.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(server, "REPLY_DELAY_S", (1.0, 3.0))
    monkeypatch.setattr(server, "reply_after_launch", instant)
    monkeypatch.setattr(lead, "flow", lambda stage, text: (None, stage, ""))
    server.save({**server.fresh("run1"), "stage": "launched"})   # past the canned opening, so the reply is a model's
    c.post("/lead/run1", json={"message": "hello"})
    assert pauses and 0.9 < pauses[-1] <= 3.0


def test_the_report_never_sees_key_bands() -> None:
    """Catches design jargon reaching the patient: options saved before scene_design dropped "meets N of M key bands"
    still carry it, and the report's inputs must not."""
    from horn_study.server import no_key_bands

    assert no_key_bands(
        "Recommended. The closest fit to the gain your scenes need: meets 0 of 3 key bands, -1.3 dB average gain where it matters most."
    ) == "Recommended. The closest fit to the gain your scenes need, -1.3 dB average gain where it matters most."
    assert no_key_bands("Preset 3, wide flush horn, fitted to your ear. Meets 0 of 4 key bands, -3.6 dB average gain.") == (
        "Preset 3, wide flush horn, fitted to your ear. -3.6 dB average gain."
    )


def test_launch_reuses_the_warm_up_evaluator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches the ~50 s capability check running AGAIN after the patient says yes: launch must take prewarm's
    evaluator and capabilities, waiting for a warm-up still in flight rather than starting a second one, and build its
    own (off the event loop) only when the warm-up failed."""
    import asyncio
    import concurrent.futures

    built: list[str] = []

    class Ev:
        def get_evaluator_capabilities(self) -> dict[str, Any]:
            built.append("caps")
            return {"fresh": True}

    monkeypatch.setattr(server, "_evaluator", lambda raw: Ev())
    warm: concurrent.futures.Future[Any] = concurrent.futures.Future()
    monkeypatch.setattr(server, "_ready", {"r1": warm})

    async def later() -> Any:
        task = asyncio.ensure_future(server._ready_evaluator({}, "r1"))
        await asyncio.sleep(0.05)
        assert not task.done()                                   # still waiting on the warm-up, not building its own
        warm.set_result((Ev(), {"warm": True}))
        return await task

    assert asyncio.run(later()).get_evaluator_capabilities() == {"warm": True} and built == []
    failed: concurrent.futures.Future[Any] = concurrent.futures.Future()
    failed.set_exception(RuntimeError("no mesh"))
    server._ready["r2"] = failed
    assert asyncio.run(server._ready_evaluator({}, "r2")).get_evaluator_capabilities() == {"fresh": True}
    assert built == ["caps"]
