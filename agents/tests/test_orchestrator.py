"""The study orchestrator: one Deep Agent runs the study, and code gates every phase."""

from __future__ import annotations

import json
from typing import Any

from helpers import (
    INVESTIGATOR_NAMES,
    PASSAGES,
    Harness,
    call,
    coordinator_responder,
    delegate,
    investigator_of,
    make_request,
    research_responder,
    tool_results,
    valid_draft,
)
from langchain_core.messages import AIMessage, HumanMessage

from horn_study.contracts import StudyState
from horn_study.orchestrator import ORCHESTRATOR_NAME, ORCHESTRATOR_PROMPT
from horn_study.workflow import run_study

ORCHESTRATOR_TOOLS = {
    "task",
    "submit_plan",
    "run_experiments",
    "write_report",
    "ls",
    "read_file",
    "glob",
    "grep",
    "write_file",
    "edit_file",
}
DONE = AIMessage(content="The study is complete.")


def load(outcome, name: str) -> Any:
    return json.loads((outcome.directory / name).read_text())


def count(outcome, event_type: str) -> int:
    return sum(1 for event in outcome.events.history if event.type == event_type)


def scripted(*turns: AIMessage, then=None):
    """Play fixed turns first, then hand over to `then` (default: the normal study script)."""
    rest = then or coordinator_responder(valid_draft())
    seen: dict[str, list[tuple[str, str]]] = {"results": []}

    def respond(messages, bound):
        seen["results"] = tool_results(messages)
        taken = sum(1 for m in messages if isinstance(m, AIMessage))
        if taken < len(turns):
            return turns[taken]
        return rest(messages, bound)

    respond.seen = seen  # type: ignore[attr-defined]
    return respond


def _starts(outcome) -> list[Any]:
    return [e for e in outcome.events.history if e.type == "research.agent_started"]


def answers(responder, name: str) -> list[str]:
    return [text for tool, text in responder.seen["results"] if tool == name]


async def test_the_orchestrator_is_the_one_deep_agent_and_holds_only_its_study_tools(tmp_path):
    harness = Harness(tmp_path)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    offered = harness.coordinator_model.log.bound_tool_sets
    assert offered
    assert all(set(tools) == ORCHESTRATOR_TOOLS for tools in offered)
    assert harness.interpreter_model.log.bound_tool_sets == [["ReportNarrative"]]
    assert "execute" not in ORCHESTRATOR_TOOLS


async def test_the_orchestrator_is_told_who_it_can_assign_and_what_code_decides(tmp_path):
    seen: dict[str, Any] = {}

    def capture(messages, bound):
        seen.setdefault("system", " ".join(str(messages[0].content).split()))
        seen.setdefault("brief", str(messages[1].content))
        return coordinator_responder(valid_draft())(messages, bound)

    await run_study(make_request(), Harness(tmp_path, coordinator=capture).deps)

    for name in INVESTIGATOR_NAMES:
        assert name in ORCHESTRATOR_PROMPT
    assert "general-purpose" not in ORCHESTRATOR_PROMPT
    assert "submit_plan" in seen["system"]
    assert "run_experiments" in seen["system"]
    assert "write_report" in seen["system"]
    assert '"study_id": "study_test_001"' in seen["brief"]


async def test_a_plan_is_refused_until_every_investigator_has_reported(tmp_path):
    lead = scripted(
        delegate("hearing_research", "acoustic_design_research"),
        call("submit_plan", valid_draft(), "early"),
        delegate("use_context_research"),
    )
    harness = Harness(tmp_path, coordinator=lead)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    early = answers(lead, "submit_plan")[0]
    assert early.startswith("Not accepted")
    assert "use_context_research" in early
    assert count(outcome, "plan.revision_requested") == 0
    assert count(outcome, "plan.frozen") == 1
    assert [b["investigator"] for b in load(outcome, "research.json")["branches"]] == list(INVESTIGATOR_NAMES)


async def test_research_is_closed_once_a_plan_has_been_submitted(tmp_path):
    over_budget = valid_draft()
    over_budget["seeds"] = [1, 2, 3]
    lead = scripted(
        delegate(*INVESTIGATOR_NAMES),
        call("submit_plan", over_budget, "first"),
        delegate("hearing_research", direction="Look again."),
    )
    harness = Harness(tmp_path, coordinator=lead)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    late = answers(lead, "task")[-1]
    assert late.startswith("Not assigned")
    assert "closed" in late
    assert count(outcome, "research.agent_started") == 3
    assert count(outcome, "plan.revision_requested") == 1


async def test_one_follow_up_assignment_is_allowed_and_its_direction_reaches_the_investigator(tmp_path):
    directions: list[str] = []

    def research(messages, bound):
        if investigator_of(messages) == "acoustic_design_research":
            told = str(next(m for m in messages if isinstance(m, HumanMessage)).content)
            if told not in directions:
                directions.append(told)
        return research_responder(messages, bound)

    lead = scripted(
        delegate(*INVESTIGATOR_NAMES, direction="First pass."),
        delegate("acoustic_design_research", direction="Find measured horn gain near 3 kHz."),
        delegate("hearing_research", direction="One more."),
    )
    harness = Harness(tmp_path, research=research, coordinator=lead)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert len(directions) == 2
    assert "First pass." in directions[0]
    assert "Find measured horn gain near 3 kHz." in directions[1]
    assert "follow-up" in directions[1]
    refused = answers(lead, "task")[-1]
    assert refused.startswith("Not assigned")
    assert "follow-up" in refused
    assigned = [e for e in outcome.events.history if e.type == "orchestrator.assigned"]
    assert [(e.data["investigator"], e.data["follow_up"]) for e in assigned] == [
        ("hearing_research", False),
        ("use_context_research", False),
        ("acoustic_design_research", False),
        ("acoustic_design_research", True),
    ]
    assert assigned[-1].data["direction"] == "Find measured horn gain near 3 kHz."
    assert assigned[-1].component == "study_orchestrator"
    assert all(e.sequence < s.sequence for e, s in zip(assigned, _starts(outcome), strict=True))
    research_record = load(outcome, "research.json")
    assert [b["investigator"] for b in research_record["branches"]] == [
        "hearing_research",
        "use_context_research",
        "acoustic_design_research",
        "acoustic_design_research",
    ]
    assert {f["finding_id"] for f in research_record["findings"]} == {
        "hearing-F1",
        "context-F1",
        "design-F1",
        "design-F2",
    }


async def test_two_assignments_of_one_investigator_in_one_turn_are_a_first_pass_and_a_follow_up(tmp_path):
    twice = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "task",
                "args": {"description": "First.", "subagent_type": "hearing_research"},
                "id": "a1",
            },
            {
                "name": "task",
                "args": {"description": "Second.", "subagent_type": "hearing_research"},
                "id": "a2",
            },
            {
                "name": "task",
                "args": {"description": "Third.", "subagent_type": "hearing_research"},
                "id": "a3",
            },
        ],
    )
    lead = scripted(twice, delegate("use_context_research", "acoustic_design_research"))
    outcome = await run_study(make_request(), Harness(tmp_path, coordinator=lead).deps)

    assert outcome.state is StudyState.COMPLETED
    assigned = [e for e in outcome.events.history if e.type == "orchestrator.assigned"]
    assert sorted((e.data["direction"], e.data["follow_up"]) for e in assigned[:2]) == [
        ("First.", False),
        ("Second.", True),
    ]
    assert (
        sum(1 for name, text in lead.seen["results"] if name == "task" and text.startswith("Not assigned"))
        == 1
    )


async def test_an_assignment_the_framework_rejects_is_not_counted(tmp_path):
    """A real model once added a stray argument to its first task call. The retry is the first pass."""
    malformed = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "task",
                "args": {
                    "description": "Profile first.",
                    "subagent_type": "hearing_research",
                    "subpath": "x",
                },
                "id": "bad",
            },
            {
                "name": "task",
                "args": {"description": "Needs.", "subagent_type": "use_context_research"},
                "id": "ok1",
            },
            {
                "name": "task",
                "args": {"description": "Shapes.", "subagent_type": "acoustic_design_research"},
                "id": "ok2",
            },
        ],
    )
    lead = scripted(
        malformed,
        delegate("hearing_research", direction="Profile, second try."),
        delegate("acoustic_design_research", direction="A real follow-up."),
    )
    outcome = await run_study(make_request(), Harness(tmp_path, coordinator=lead).deps)

    assert outcome.state is StudyState.COMPLETED
    assigned = [e for e in outcome.events.history if e.type == "orchestrator.assigned"]
    assert [(e.data["investigator"], e.data["follow_up"]) for e in assigned] == [
        ("use_context_research", False),
        ("acoustic_design_research", False),
        ("hearing_research", False),
        ("acoustic_design_research", True),
    ]
    assert not any(text.startswith("Not assigned") for name, text in lead.seen["results"] if name == "task")
    assert count(outcome, "research.agent_started") == 4


async def test_a_request_can_forbid_follow_up_assignments(tmp_path):
    lead = scripted(delegate(*INVESTIGATOR_NAMES), delegate("hearing_research", direction="Again."))
    request = make_request()
    request["budget"]["max_research_follow_ups"] = 0
    outcome = await run_study(request, Harness(tmp_path, coordinator=lead).deps)

    assert outcome.state is StudyState.COMPLETED
    assert answers(lead, "task")[-1].startswith("Not assigned")
    assert count(outcome, "research.agent_started") == 3


async def test_the_orchestrator_can_open_the_reports_and_the_papers_its_investigators_read(tmp_path):
    lead = scripted(
        delegate(*INVESTIGATOR_NAMES),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "grep",
                    "args": {"pattern": "path length", "path": "/sources", "output_mode": "content"},
                    "id": "g1",
                },
                {"name": "read_file", "args": {"file_path": "/research/hearing_research.json"}, "id": "r1"},
                {"name": "ls", "args": {"path": "/sources"}, "id": "l1"},
            ],
        ),
    )
    outcome = await run_study(make_request(), Harness(tmp_path, coordinator=lead).deps)

    assert outcome.state is StudyState.COMPLETED
    assert PASSAGES["acoustic_design_research"] in answers(lead, "grep")[0]
    assert "hearing-F1" in answers(lead, "read_file")[0]
    listing = answers(lead, "ls")[0]
    sources = load(outcome, "research.json")["sources"]
    assert sources
    assert all(f"/sources/{source['source_id']}.txt" in listing for source in sources)
    opened = [e for e in outcome.events.history if e.type == "orchestrator.evidence_opened"]
    assert [(e.data["tool"], e.data["path"]) for e in opened] == [
        ("grep", "/sources"),
        ("read_file", "/research/hearing_research.json"),
    ]
    by_id = {source["source_id"]: source for source in sources}
    assert opened[0].data["pattern"] == "path length"
    assert opened[0].data["sources"]
    for seen in opened[0].data["sources"]:
        assert seen["url"] == by_id[seen["source_id"]]["url"]
        assert seen["title"] == by_id[seen["source_id"]]["title"]
    assert opened[1].data["sources"] == []
    assignment = json.loads(answers(lead, "task")[0])
    assert assignment["investigator"] in INVESTIGATOR_NAMES
    assert assignment["status"] == "completed"
    assert assignment["findings"][0]["evidence_passage"]


async def test_the_orchestrator_keeps_notes_only_in_its_own_folder(tmp_path):
    lead = scripted(
        delegate(*INVESTIGATOR_NAMES),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/work/decisions.md", "content": "Vary length first."},
                    "id": "w1",
                },
                {
                    "name": "write_file",
                    "args": {"file_path": "/sources/S1.txt", "content": "Horns give 40 dB."},
                    "id": "w2",
                },
            ],
        ),
    )
    outcome = await run_study(make_request(), Harness(tmp_path, coordinator=lead).deps)

    assert outcome.state is StudyState.COMPLETED
    allowed, denied = answers(lead, "write_file")
    assert "permission denied" in denied
    assert "permission denied" not in allowed
    written = [e for e in outcome.events.history if e.type == "orchestrator.note_written"]
    assert [e.data["path"] for e in written] == ["/work/decisions.md"]
    recorded = load(outcome, "results.json")["orchestrator"]
    assert recorded["agent"] == ORCHESTRATOR_NAME
    assert recorded["notes"] == {"/work/decisions.md": "Vary length first."}
    assert recorded["phases_completed_by_workflow"] == []


async def test_the_orchestrator_cannot_reach_tools_or_helpers_outside_its_allowlist(tmp_path):
    lead = scripted(
        AIMessage(
            content="",
            tool_calls=[
                {"name": "execute", "args": {"command": "ls"}, "id": "x1"},
                {
                    "name": "task",
                    "args": {"description": "Do the study for me.", "subagent_type": "general-purpose"},
                    "id": "x2",
                },
            ],
        ),
    )
    harness = Harness(tmp_path, coordinator=lead)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert "not available to the study orchestrator" in answers(lead, "execute")[0]
    stray = answers(lead, "task")[0]
    assert stray.startswith("Not assigned")
    assert "general-purpose" in stray
    assert count(outcome, "research.agent_started") == 3


async def test_experiments_and_the_report_cannot_be_asked_for_before_a_plan_is_frozen(tmp_path):
    lead = scripted(
        AIMessage(
            content="",
            tool_calls=[
                {"name": "run_experiments", "args": {}, "id": "e1"},
                {"name": "write_report", "args": {}, "id": "w1"},
            ],
        ),
    )
    harness = Harness(tmp_path, coordinator=lead)
    calls_at_refusal: list[int] = []

    def watch(messages, bound):
        if not calls_at_refusal and any(name == "run_experiments" for name, _ in tool_results(messages)):
            calls_at_refusal.append(len(harness.evaluator.calls))
        return lead(messages, bound)

    harness.coordinator_model.responder = watch
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert calls_at_refusal == [0]
    assert answers(lead, "run_experiments")[0].startswith("Not run")
    assert answers(lead, "write_report")[0].startswith("Not written")
    assert len(harness.evaluator.calls) == 12


async def test_nothing_can_be_researched_planned_or_rerun_once_the_plan_is_frozen(tmp_path):
    def after_freeze(*extra: dict[str, Any]) -> AIMessage:
        return AIMessage(content="", tool_calls=list(extra))

    again = [
        {"name": "submit_plan", "args": valid_draft(), "id": "p-again"},
        {
            "name": "task",
            "args": {"description": "More.", "subagent_type": "hearing_research"},
            "id": "t-again",
        },
    ]
    lead = scripted(
        delegate(*INVESTIGATOR_NAMES),
        call("submit_plan", valid_draft(), "p1"),
        after_freeze(*again),
        call("run_experiments", {}, "r1"),
        after_freeze(
            {"name": "run_experiments", "args": {}, "id": "r2"},
            {"name": "submit_plan", "args": valid_draft(), "id": "p-after-results"},
        ),
        call("write_report", {}, "w1"),
        after_freeze(
            {"name": "write_report", "args": {}, "id": "w2"},
            {"name": "run_experiments", "args": {}, "id": "r3"},
            {"name": "submit_plan", "args": valid_draft(), "id": "p-after-report"},
        ),
        then=lambda messages, bound: DONE,
    )
    harness = Harness(tmp_path, coordinator=lead)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    plans = answers(lead, "submit_plan")
    assert plans[0].startswith("Plan frozen")
    assert all(text.startswith("Not accepted") for text in plans[1:])
    assert len(plans) == 4
    assert answers(lead, "task")[-1].startswith("Not assigned")
    runs = answers(lead, "run_experiments")
    assert [text.startswith("Not run") for text in runs] == [False, True, True]
    reports = answers(lead, "write_report")
    assert [text.startswith("Not written") for text in reports] == [False, True]
    assert len(harness.evaluator.calls) == 12
    assert len(set(harness.evaluator.calls)) == 12
    assert count(outcome, "plan.frozen") == 1
    assert count(outcome, "report.completed") == 1
    assert count(outcome, "research.agent_started") == 3
    assert harness.interpreter_model.log.calls == 1


async def test_the_workflow_finishes_the_phases_an_orchestrator_leaves_undone(tmp_path):
    lead = scripted(
        delegate(*INVESTIGATOR_NAMES),
        call("submit_plan", valid_draft(), "p1"),
        then=lambda messages, bound: AIMessage(content="I am stopping here."),
    )
    harness = Harness(tmp_path, coordinator=lead)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert outcome.report is not None
    assert outcome.report.selected_candidate_id
    assert len(harness.evaluator.calls) == 12
    recorded = load(outcome, "results.json")["orchestrator"]
    assert recorded["phases_completed_by_workflow"] == ["run_experiments", "write_report"]
    assert any("did not ask for" in text for text in outcome.report.limitations)


async def test_an_orchestrator_that_never_freezes_a_plan_fails_the_study(tmp_path):
    lead = scripted(delegate(*INVESTIGATOR_NAMES), then=lambda messages, bound: AIMessage(content="Done."))
    harness = Harness(tmp_path, coordinator=lead)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.FAILED
    assert outcome.failure["kind"] == "planning_failed"
    assert harness.evaluator.calls == []
    assert load(outcome, "results.json")["state"] == "FAILED"


async def test_an_orchestrator_that_assigns_nobody_fails_the_study_without_evaluating(tmp_path):
    lead = scripted(then=lambda messages, bound: AIMessage(content="Nothing to do."))
    harness = Harness(tmp_path, coordinator=lead)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.FAILED
    assert outcome.failure["kind"] == "planning_failed"
    assert harness.research_model.log.calls == 0
    assert harness.evaluator.calls == []
