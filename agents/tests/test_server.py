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
    (tmp_path / "patients" / "run1").mkdir(parents=True)
    (tmp_path / "patients" / "run1" / "job.json").write_text(json.dumps(ONE_EAR))
    started: list[dict[str, Any]] = []

    async def fake_run(raw: dict[str, Any]) -> None:
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
    assert len(request.hearing_profile.measurements) == 2


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
