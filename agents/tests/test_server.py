"""The lead's HTTP route, as the dashboard calls it."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from helpers import ScriptedChatModel, call
from langchain_core.messages import AIMessage, BaseMessage

from horn_study import server
from horn_study.lead import build_lead_graph


def client(tmp_path: Path) -> TestClient:
    def respond(_m: list[BaseMessage], _b: list[str]) -> AIMessage:
        return call(
            "LeadTurn", {"reply": "Hello.", "needs": {}, "ask_to_launch": False, "launch_confirmed": False}
        )

    server.state.graph = build_lead_graph(ScriptedChatModel(responder=respond), tmp_path)
    return TestClient(server.app)


def test_lead_route_round_trip(tmp_path: Path) -> None:
    """Catches the route shape drifting from what frontend/lib/lead.ts reads."""
    r = client(tmp_path).post("/lead/run1", json={"message": ""})
    assert r.status_code == 200
    assert r.json() == {"reply": "Hello.", "awaiting_launch": False, "launch_requested": False}


def test_bad_run_id_is_rejected(tmp_path: Path) -> None:
    """Catches a run ID walking out of the patients folder — it is joined onto a path."""
    assert client(tmp_path).post("/lead/..%2Fx", json={"message": ""}).status_code in (400, 404)
    assert client(tmp_path).post("/lead/a.b", json={"message": ""}).status_code == 400
