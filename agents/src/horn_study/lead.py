"""The lead: the scripted exchange in front of the study.

    lead:    Anything I should know before I launch research based on your audiogram?
    patient: no                 -> launch
    patient: <anything else>    -> "Noted. May I begin?"  (repeats for every further note)
               then yes -> launch, no -> wait, anything else -> noted again

The lines are fixed copy, so no model is called. Research NEVER starts here: this module does not
import the study workflow. A launch only sets launch_requested and keeps the notes; the hand-off to
workflow.py is the next step.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

OPENING = "Anything I should know before I launch research based on your audiogram?"
NOTED = "Noted."
BEGIN = "May I begin?"
WAIT = "Okay, I'll wait. Tell me anything else, or say yes when you're ready."
LAUNCH = "Thanks. This is where the research agents would begin; that step isn't connected yet."
AFTER = "Research would be underway now; that step isn't connected yet."

Stage = Literal["new", "opening", "begin", "launched"]

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


class LeadState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    stage: Stage
    notes: list[str]
    launch_requested: bool


def _step(stage: Stage, text: str) -> tuple[str, Stage, str | None]:
    """(reply, next stage, note to keep) for one patient message."""
    if stage == "new":
        return OPENING, "opening", None
    if stage == "launched":
        return AFTER, "launched", None
    answer = _answer(text)
    # "No" means "nothing to add" ONLY to the opening question; to "May I begin?" it means wait.
    if (stage == "opening" and answer == "no") or (stage == "begin" and answer == "yes"):
        return LAUNCH, "launched", None
    if stage == "begin" and answer == "no":
        return WAIT, "begin", None
    return f"{NOTED} {BEGIN}", "begin", text


def build_lead_graph() -> CompiledStateGraph:
    def lead(state: LeadState) -> dict[str, Any]:
        messages = state.get("messages", [])
        last = messages[-1].content if messages else ""
        reply, stage, note = _step(state.get("stage", "new"), str(last))
        return {
            "messages": [AIMessage(reply)],
            "stage": stage,
            "notes": [*state.get("notes", []), *([note] if note else [])],
            "launch_requested": stage == "launched",
        }

    builder: StateGraph[LeadState, Any, Any, Any] = StateGraph(LeadState)
    builder.add_node("lead", lead)
    builder.add_edge(START, "lead")
    builder.add_edge("lead", END)
    # ponytail: in-memory; conversations end with the process. A saver on disk when they must survive restarts.
    return builder.compile(checkpointer=MemorySaver())


async def lead_turn(graph: CompiledStateGraph, run_id: str, message: str) -> dict[str, Any]:
    """One patient message in, one reply out. The run ID is the conversation; "" opens it."""
    config: Any = {"configurable": {"thread_id": run_id}}
    out = await graph.ainvoke({"messages": [HumanMessage(message)]}, config)
    return {
        "reply": str(out["messages"][-1].content),
        "awaiting_launch": out["stage"] in ("opening", "begin"),
        "launch_requested": out["launch_requested"],
        "notes": out["notes"],
    }
