"""The lead agent: the conversation in front of the study. Research must NEVER start from here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from helpers import ScriptedChatModel, call
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from horn_study.lead import build_lead_graph, lead_turn


def scripted(turns: list[dict[str, Any]], seen: list[list[BaseMessage]]) -> ScriptedChatModel:
    queue = list(turns)

    def respond(messages: list[BaseMessage], _bound: list[str]) -> AIMessage:
        seen.append(messages)
        turn = {"needs": {}, "ask_to_launch": False, "launch_confirmed": False} | queue.pop(0)
        return call("LeadTurn", turn)

    return ScriptedChatModel(responder=respond)


def patient(tmp_path: Path, run_id: str = "run1") -> Path:
    (tmp_path / run_id).mkdir()
    job = {"request": {"side": "left", "audiogram_db_hl": {"500": 20.0, "4000": 40.0}}}
    (tmp_path / run_id / "job.json").write_text(json.dumps(job))
    return tmp_path


async def test_opening_line_uses_patient_audiogram(tmp_path: Path) -> None:
    """Catches the lead opening blind: it must see this patient's hearing test, not talk generically."""
    seen: list[list[BaseMessage]] = []
    graph = build_lead_graph(scripted([{"reply": "Hi, your ear is ready."}], seen), patient(tmp_path))
    out = await lead_turn(graph, "run1", "")
    assert out["reply"] == "Hi, your ear is ready."
    assert not out["awaiting_launch"]
    assert not out["launch_requested"]
    system = next(m for m in seen[0] if isinstance(m, SystemMessage))
    assert "4000" in str(system.content)
    assert "left" in str(system.content)


async def test_ask_pauses_and_yes_requests_launch(tmp_path: Path) -> None:
    """Catches research launching without the patient's explicit yes, or a yes being lost."""
    seen: list[list[BaseMessage]] = []
    turns = [
        {"reply": "What do you do most days?"},
        {
            "reply": "Shall I launch the research agents?",
            "ask_to_launch": True,
            "needs": {"activities": ["running"]},
        },
        {"reply": "Launching.", "launch_confirmed": True, "needs": {"activities": ["running"]}},
    ]
    graph = build_lead_graph(scripted(turns, seen), patient(tmp_path))
    await lead_turn(graph, "run1", "")
    asked = await lead_turn(graph, "run1", "I run a lot")
    assert asked["awaiting_launch"]
    assert not asked["launch_requested"]
    done = await lead_turn(graph, "run1", "yes")
    assert done["launch_requested"]
    assert not done["awaiting_launch"]
    assert done["needs"]["activities"] == ["running"]
    assert "yes" in str(seen[-1][-1].content)


async def test_no_keeps_talking(tmp_path: Path) -> None:
    """Catches a "no" being treated as consent, or ending the conversation."""
    seen: list[list[BaseMessage]] = []
    turns = [
        {"reply": "Launch the research agents?", "ask_to_launch": True},
        {"reply": "No problem, ask me anything."},
        {"reply": "It is a horn-shaped aid."},
    ]
    graph = build_lead_graph(scripted(turns, seen), patient(tmp_path))
    await lead_turn(graph, "run1", "")
    out = await lead_turn(graph, "run1", "no")
    assert not out["launch_requested"]
    assert not out["awaiting_launch"]
    out = await lead_turn(graph, "run1", "what is it?")
    assert out["reply"] == "It is a horn-shaped aid."


async def test_missing_job_json_still_answers(tmp_path: Path) -> None:
    """Catches a crash when the run has no saved data (example run, wiped data dir)."""
    seen: list[list[BaseMessage]] = []
    graph = build_lead_graph(scripted([{"reply": "Hello."}], seen), tmp_path)
    assert (await lead_turn(graph, "ghost", ""))["reply"] == "Hello."
