"""The lead: the conversation in front of the study.

It answers the patient's questions about their run, learns what they need the aid for (the
study's NeedsProfile), and asks before launching research. The graph is

    START -> lead -> END                  an ordinary reply
                  -> confirm -> lead      it asked to launch; confirm PAUSES until the patient answers
                  -> END (launch_requested)

Research NEVER starts here: this module does not import the study workflow. A yes only sets
launch_requested; the hand-off to workflow.py is the next step (docs/superpowers/specs/
2026-11-14-lead-agent-design.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from horn_study.contracts import NeedsProfile

# Anthropic needs a user turn first; this stands in for "the ear views just finished".
OPENING = "(The patient's ear views just finished. Open the conversation.)"

PROMPT = """You are the lead of Auris, an app that designs a 3D-printed horn hearing aid from a photo \
of the patient's ear and their hearing test. The ear has just been reconstructed; the aid is being \
built in the background.

Your replies show as one short caption under an animated orb, so write 1-3 short sentences, plain \
words, no lists, no markdown.

Your job:
1. Answer the patient's questions about their ear, hearing test and the process.
2. Learn what they need the aid for: activities, goals, priorities, hard requirements. Ask one \
question at a time. Record everything you learn in `needs`, keeping what you already had.
3. Once you know at least their activities and goals, ask whether to launch the research agents \
(they study hearing research and the patient's situation to choose the aid design), and set \
ask_to_launch true on THAT reply only.
4. Set launch_confirmed true ONLY when your previous reply asked to launch and the patient's latest \
message clearly agrees. Otherwise keep talking. Never say research is running unless you set it.

Patient data:
{context}"""


class LeadTurn(BaseModel):
    """One reply from the lead."""

    reply: str = Field(description="What the patient sees: 1-3 short sentences.")
    needs: NeedsProfile = Field(description="Everything learned so far about the patient's needs.")
    ask_to_launch: bool = Field(description="This reply asks whether to launch the research agents.")
    launch_confirmed: bool = Field(description="The patient just agreed to a launch you asked about.")


class LeadState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    needs: dict[str, Any]
    ask: bool
    launch_requested: bool


def patient_context(patients_dir: Path, run_id: str) -> str:
    """What the backend knows about this run, from its job.json. Missing data is said, not guessed."""
    try:
        job = json.loads((patients_dir / run_id / "job.json").read_text())
    except (OSError, ValueError):
        return "No saved data for this run; do not invent any."
    req = job.get("request", {})
    lines = [
        f"Ear: {req.get('side', 'unknown')}",
        f"Audiogram, dB HL by Hz: {json.dumps(req.get('audiogram_db_hl'))}"
        + (" (an EXAMPLE, not this patient's)" if req.get("audiogram_is_example") else ""),
        f"Pipeline: {job.get('status')}, step {job.get('step')}, done: {', '.join(job.get('results', {}))}",
    ]
    return "\n".join(lines)


def build_lead_graph(model: BaseChatModel, patients_dir: Path) -> CompiledStateGraph:
    structured = model.with_structured_output(LeadTurn)

    async def lead(state: LeadState, config: RunnableConfig) -> dict[str, Any]:
        run_id = config.get("configurable", {})["thread_id"]
        system = SystemMessage(PROMPT.format(context=patient_context(patients_dir, run_id)))
        turn = await structured.ainvoke([system, *state.get("messages", [])])
        assert isinstance(turn, LeadTurn)
        update: dict[str, Any] = {
            "messages": [AIMessage(turn.reply)],
            "needs": turn.needs.model_dump(mode="json"),
            # A confirmation counts ONLY right after the lead asked — the model cannot self-approve.
            "launch_requested": state.get("launch_requested", False)
            or (turn.launch_confirmed and state.get("ask", False)),
            "ask": turn.ask_to_launch,
        }
        return update

    def confirm(state: LeadState) -> dict[str, Any]:
        answer = interrupt({"awaiting": "launch"})
        return {"messages": [HumanMessage(str(answer))]}

    def route(state: LeadState) -> str:
        return "confirm" if state.get("ask") and not state.get("launch_requested") else END

    builder: StateGraph[LeadState, Any, Any, Any] = StateGraph(LeadState)
    builder.add_node("lead", lead)
    builder.add_node("confirm", confirm)
    builder.add_edge(START, "lead")
    builder.add_conditional_edges("lead", route, ["confirm", END])
    builder.add_edge("confirm", "lead")
    # ponytail: in-memory; conversations end with the process. A saver on disk when they must survive restarts.
    return builder.compile(checkpointer=MemorySaver())


async def lead_turn(graph: CompiledStateGraph, run_id: str, message: str) -> dict[str, Any]:
    """One patient message in, one reply out. The run ID is the conversation; "" opens it."""
    config: Any = {"configurable": {"thread_id": run_id}}
    paused = (await graph.aget_state(config)).next
    if paused:
        await graph.ainvoke(Command(resume=message), config)
    else:
        await graph.ainvoke({"messages": [HumanMessage(message or OPENING)], "ask": False}, config)
    snap = await graph.aget_state(config)
    values = snap.values
    reply = next((m.content for m in reversed(values["messages"]) if isinstance(m, AIMessage)), "")
    return {
        "reply": str(reply),
        "awaiting_launch": bool(snap.next),
        "launch_requested": bool(values.get("launch_requested")),
        "needs": values.get("needs", {}),
    }
