"""The whole study: research, plan, freeze, evaluate once, report, stop."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from helpers import (
    CountingEvaluator,
    Harness,
    call,
    coordinator_responder,
    design,
    investigator_of,
    investigator_report,
    make_request,
    narrative,
    research_responder,
    tool_messages,
    valid_draft,
)
from langchain_core.messages import AIMessage
from langchain_core.tracers.base import BaseTracer
from langchain_core.tracers.schemas import Run

from horn_study.contracts import StudyState, allowed_transitions
from horn_study.evaluator_adapter import DevelopmentFixtureEvaluator, TransientEvaluatorError
from horn_study.events import ARTIFACT_NAMES, ArtifactStore, EventBus, StudyExists, read_events
from horn_study.followup import follow_up_request
from horn_study.intake import InputRejected
from horn_study.workflow import (
    NODE_EVALUATE,
    NODE_FREEZE,
    NODE_INTERPRET,
    NODE_PLAN,
    NODE_SYNTHESIZE,
    RESEARCH_NODES,
    IllegalTransition,
    StudyStateMachine,
    run_study,
)

EVIDENCE_TOOLS = {"search_literature", "read_source", "record_finding"}
READ_ONLY_FILE_TOOLS = {"ls", "read_file", "grep"}


def types(outcome) -> list[str]:
    return [event.type for event in outcome.events.history]


def first(outcome, event_type: str):
    return next(e for e in outcome.events.history if e.type == event_type)


def load(outcome, name: str) -> Any:
    return json.loads((outcome.directory / name).read_text())


def digest(directory: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir())}


# --------------------------------------------------------------------------
# One complete study
# --------------------------------------------------------------------------


async def test_a_study_runs_once_through_every_phase_and_stops(tmp_path):
    harness = Harness(tmp_path)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    phases = [e.data["to"] for e in outcome.events.history if e.type == "study.state_changed"]
    assert phases == [
        "RESEARCHING",
        "PLANNING",
        "PLAN_FROZEN",
        "EVALUATING",
        "INTERPRETING",
        "COMPLETED",
    ]
    assert [e.sequence for e in outcome.events.history] == list(range(1, len(outcome.events.history) + 1))
    assert types(outcome)[0] == "study.started"
    assert types(outcome)[-1] == "study.completed"
    assert sorted(p.name for p in outcome.directory.iterdir()) == sorted(ARTIFACT_NAMES)
    assert [e.model_dump() for e in read_events(ArtifactStore(tmp_path, outcome.study_id))] == [
        e.model_dump() for e in outcome.events.history
    ]


async def test_a_study_works_without_lifestyle_needs(tmp_path):
    harness = Harness(tmp_path, coordinator=coordinator_responder(valid_draft(needs=False)))
    outcome = await run_study(make_request(needs=False), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert outcome.report.study_context.is_default
    assert outcome.report.needs == ()
    assert any("default_everyday_listening" in text for text in outcome.report.limitations)
    assert len(outcome.report.hearing_input.measurements) == 6


async def test_invalid_input_is_rejected_before_anything_is_saved_or_evaluated(tmp_path):
    harness = Harness(tmp_path)
    request = make_request()
    request["hearing_profile"]["measurements"] = request["hearing_profile"]["measurements"][:2]
    with pytest.raises(InputRejected) as caught:
        await run_study(request, harness.deps)

    assert {issue.code for issue in caught.value.issues} == {"hearing.required_frequency_missing"}
    assert harness.evaluator.calls == []
    assert harness.research_model.log.calls == 0
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# Research
# --------------------------------------------------------------------------


async def test_three_research_branches_overlap_and_return_identifiable_evidence(tmp_path):
    harness = Harness(tmp_path)
    outcome = await run_study(make_request(), harness.deps)
    history = outcome.events.history

    started = [e.sequence for e in history if e.type == "research.agent_started"]
    finished = [e.sequence for e in history if e.type == "research.agent_completed"]
    assert len(started) == len(finished) == 3
    assert max(started) < min(finished)
    assert harness.research_model.log.max_active == 3

    research = load(outcome, "research.json")
    assert [b["investigator"] for b in research["branches"]] == list(RESEARCH_NODES)
    assert {f["finding_id"] for f in research["findings"]} == {"hearing-F1", "context-F1", "design-F1"}
    sources = {s["source_id"]: s for s in research["sources"]}
    for finding in research["findings"]:
        source = sources[finding["source_id"]]
        assert finding["source_url"] == source["url"]
        assert source["content_sha256"]
        assert finding["evidence_passage"]


async def test_investigators_hold_evidence_tools_only(tmp_path):
    harness = Harness(tmp_path)
    await run_study(make_request(), harness.deps)

    for offered in harness.research_model.log.bound_tool_sets:
        assert set(offered) == EVIDENCE_TOOLS | READ_ONLY_FILE_TOOLS | {"InvestigatorOutput"}
    assert harness.coordinator_model.log.bound_tool_sets == [["PlanDraft"]]
    assert harness.interpreter_model.log.bound_tool_sets == [["ReportNarrative"]]


async def test_an_investigator_cannot_reach_tools_outside_its_allowlist(tmp_path):
    forbidden = ("execute", "task", "write_file")
    refusals: dict[str, str] = {}

    def sneaky(messages, bound):
        if investigator_of(messages) != "hearing_research":
            return research_responder(messages, bound)
        if not any(isinstance(m, AIMessage) for m in messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "execute", "args": {"command": "ls"}, "id": "x1"},
                    {
                        "name": "task",
                        "args": {"description": "d", "subagent_type": "general-purpose"},
                        "id": "x2",
                    },
                    {"name": "write_file", "args": {"file_path": "/a", "content": "b"}, "id": "x3"},
                ],
            )
        for message in tool_messages(messages):
            if message.name in forbidden:
                refusals[message.name] = str(message.content)
        # Continue the normal script, ignoring the refused first turn.
        first_ai = next(i for i, m in enumerate(messages) if isinstance(m, AIMessage))
        rest = [
            m for i, m in enumerate(messages) if i != first_ai and getattr(m, "name", None) not in forbidden
        ]
        return research_responder(rest, bound)

    harness = Harness(tmp_path, research=sneaky)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert set(refusals) == set(forbidden)
    assert all("not available to this investigator" in text for text in refusals.values())
    assert len(load(outcome, "research.json")["findings"]) == 3


async def test_an_investigator_can_search_the_full_text_of_a_source_it_read(tmp_path):
    seen: dict[str, str] = {}

    def digs_deeper(messages, bound):
        if investigator_of(messages) != "acoustic_design_research":
            return research_responder(messages, bound)
        step = sum(1 for m in messages if isinstance(m, AIMessage))
        if step == 2:
            told = next(str(m.content) for m in tool_messages(messages) if m.name == "read_source")
            saved_at = re.search(r"Full text saved at (/sources/S\d+\.txt)", told).group(1)
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "grep",
                        "args": {"pattern": "path length", "path": "/sources", "output_mode": "content"},
                        "id": "g1",
                    },
                    {"name": "read_file", "args": {"file_path": saved_at}, "id": "r1"},
                ],
            )
        for message in tool_messages(messages):
            if message.name in {"grep", "read_file"}:
                seen[message.name] = str(message.content)
        if step > 2:
            keep = [m for m in messages if getattr(m, "name", None) not in {"grep", "read_file"}]
            ai_turns = [i for i, m in enumerate(keep) if isinstance(m, AIMessage)]
            keep.pop(ai_turns[2])
            return research_responder(keep, bound)
        return research_responder(messages, bound)

    harness = Harness(tmp_path, research=digs_deeper)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert "The acoustic path length of a horn shifts" in seen["grep"]
    assert "Abstract. This placeholder document" in seen["read_file"]


async def test_a_failed_branch_is_reported_and_the_study_continues_on_the_rest(tmp_path):
    def one_fails(messages, bound):
        if investigator_of(messages) == "use_context_research":
            raise RuntimeError("provider unavailable")
        return research_responder(messages, bound)

    draft = valid_draft()
    draft["hypotheses"][0]["supporting_finding_ids"] = ["design-F1"]
    harness = Harness(tmp_path, research=one_fails, coordinator=coordinator_responder(draft))
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    failed = first(outcome, "research.agent_failed")
    assert failed.component == "use_context_research"
    assert any("use context research branch ended as 'failed'" in text for text in outcome.report.limitations)


async def test_no_evidence_means_no_plan_and_no_evaluation(tmp_path):
    def reports_nothing(messages, bound):
        who = investigator_of(messages)
        return call(
            "InvestigatorOutput",
            investigator_report(who, summary="Found nothing usable.", candidate_hypotheses=[]),
        )

    harness = Harness(tmp_path, research=reports_nothing)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.FAILED
    assert outcome.failure["kind"] == "no_evidence"
    assert harness.evaluator.calls == []
    assert harness.coordinator_model.log.calls == 0
    assert load(outcome, "results.json")["state"] == "FAILED"


# --------------------------------------------------------------------------
# Plan, freeze, and bounded execution
# --------------------------------------------------------------------------


async def test_the_plan_is_frozen_before_any_result_and_only_its_cases_run(tmp_path):
    harness = Harness(tmp_path)
    outcome = await run_study(make_request(), harness.deps)

    frozen = first(outcome, "plan.frozen")
    assert frozen.sequence < first(outcome, "experiment.started").sequence
    plan = load(outcome, "plan.json")
    assert plan["plan_hash"] == frozen.data["plan_hash"]
    assert plan["frozen_at"]

    planned = [e["experiment_id"] for e in plan["experiments"]]
    assert sorted(harness.evaluator.calls) == sorted(planned)
    assert len(planned) == 12 <= make_request()["budget"]["max_evaluation_cases"]
    results = load(outcome, "experiment_results.json")
    assert results["plan_hash"] == plan["plan_hash"]
    spec_hashes = {
        e["experiment_id"]: r["spec_hash"]
        for e, r in zip(plan["experiments"], results["records"], strict=True)
    }
    assert all(r["result"]["spec_hash"] == spec_hashes[r["experiment_id"]] for r in results["records"])


async def test_a_draft_is_corrected_before_freezing_and_never_after(tmp_path):
    over_budget = valid_draft()
    over_budget["candidates"].append(design("len60", 60))
    harness = Harness(tmp_path, coordinator=coordinator_responder(over_budget, valid_draft()))
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    revision = first(outcome, "plan.revision_requested")
    assert "Over budget" in revision.data["errors"][0]
    assert revision.sequence < first(outcome, "plan.frozen").sequence
    assert harness.coordinator_model.log.calls == 2
    assert load(outcome, "plan.json")["plan_version"] == 2
    assert len(harness.evaluator.calls) == 12


async def test_a_plan_that_stays_invalid_fails_without_evaluating(tmp_path):
    over_budget = valid_draft()
    over_budget["candidates"].append(design("len60", 60))
    harness = Harness(tmp_path, coordinator=coordinator_responder(over_budget))
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.FAILED
    assert outcome.failure["kind"] == "plan_invalid"
    assert "Over budget" in outcome.failure["details"][0]
    assert harness.coordinator_model.log.calls == 1 + make_request().get("budget", {}).get(
        "max_plan_revisions", 2
    )
    assert harness.evaluator.calls == []
    assert "plan.frozen" not in types(outcome)


async def test_evaluation_concurrency_stays_within_the_budget(tmp_path):
    class Tracking(CountingEvaluator):
        active = 0
        peak = 0

        def evaluate_experiment(self, spec):
            import time

            with self._lock:
                Tracking.active += 1
                Tracking.peak = max(Tracking.peak, Tracking.active)
            time.sleep(0.02)
            try:
                return super().evaluate_experiment(spec)
            finally:
                with self._lock:
                    Tracking.active -= 1

        import threading as _threading

        _lock = _threading.Lock()

    harness = Harness(tmp_path, evaluator=Tracking())
    outcome = await run_study(make_request(), harness.deps)
    assert outcome.state is StudyState.COMPLETED
    assert Tracking.peak == 2


# --------------------------------------------------------------------------
# Honest results
# --------------------------------------------------------------------------


class ScenarioFailure(CountingEvaluator):
    """The named candidates fail in one scenario. Everything else is unchanged."""

    def __init__(self, candidates: set[str], scenario: str = "speech_in_babble", transient: bool = False):
        super().__init__()
        self.candidates, self.scenario, self.transient = candidates, scenario, transient

    def evaluate_experiment(self, spec):
        self.calls.append(spec.experiment_id)
        if spec.candidate_id in self.candidates and spec.scenario_id == self.scenario:
            if self.transient:
                raise TransientEvaluatorError("queue timeout")
            raise RuntimeError("solver diverged")
        return self.inner.evaluate_experiment(spec)


async def test_a_design_with_a_failed_case_cannot_win(tmp_path):
    baseline = await run_study(make_request("clean"), Harness(tmp_path).deps)
    assert baseline.report.selected_candidate_id == "len45"

    harness = Harness(tmp_path, evaluator=ScenarioFailure({"len45"}))
    outcome = await run_study(make_request("with_failure"), harness.deps)
    report = outcome.report

    assert outcome.state is StudyState.COMPLETED
    assert report.selected_candidate_id == "len90"
    loser = next(c for c in report.candidates if c.candidate_id == "len45")
    assert not loser.eligible
    assert loser.ineligibility_reasons == ("Only 2 of 3 planned cases completed.",)
    assert loser.improvement_over_reference is None
    assert report.experiments_not_completed == ("len45--speech_in_babble--default_canal--s0",)
    assert any("1 of 12 planned evaluation cases did not complete" in text for text in report.limitations)
    hypothesis = report.hypotheses[0]
    assert hypothesis.verdict == "inconclusive"
    assert not hypothesis.data_complete
    assert len(harness.evaluator.calls) == 12


async def test_transient_failures_retry_only_the_identical_case(tmp_path):
    harness = Harness(tmp_path, evaluator=ScenarioFailure({"len30"}, transient=True))
    outcome = await run_study(make_request(), harness.deps)

    target = "len30--speech_in_babble--default_canal--s0"
    assert harness.evaluator.calls.count(target) == 2
    assert len(harness.evaluator.calls) == 13
    assert set(harness.evaluator.calls) == {
        e["experiment_id"] for e in load(outcome, "plan.json")["experiments"]
    }
    record = next(
        r for r in load(outcome, "experiment_results.json")["records"] if r["experiment_id"] == target
    )
    assert record["outcome"] == "failed"
    assert record["result"] is None
    assert [a["outcome"] for a in record["attempts"]] == ["transient_error", "transient_error"]


async def test_no_winner_is_forced_when_every_design_fails(tmp_path):
    harness = Harness(tmp_path, evaluator=ScenarioFailure({"len30", "len45", "len90"}))
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert outcome.report.selected_candidate_id is None
    assert outcome.report.selection.reason_code == "no_eligible_candidate"
    assert load(outcome, "results.json")["selected_candidate"] is None
    assert all(n.status != "addressed" for n in outcome.report.needs)


async def test_no_winner_when_the_control_is_incomplete_or_nothing_improves(tmp_path):
    harness = Harness(tmp_path, evaluator=ScenarioFailure({"unaided"}))
    outcome = await run_study(make_request("no_control"), harness.deps)
    assert outcome.report.selection.reason_code == "reference_incomplete"
    assert outcome.report.selected_candidate_id is None

    class NoBenefit(CountingEvaluator):
        def evaluate_experiment(self, spec):
            self.calls.append(spec.experiment_id)
            as_unaided = spec.model_copy(
                update={
                    "candidate_kind": "baseline",
                    "baseline_id": "unaided",
                    "family_id": None,
                    "parameters": {},
                }
            )
            result = self.inner.evaluate_experiment(as_unaided)
            return result.model_copy(
                update={"spec_hash": spec.spec_hash(), "parameters": dict(spec.parameters)}
            )

    flat = await run_study(make_request("no_benefit"), Harness(tmp_path, evaluator=NoBenefit()).deps)
    assert flat.report.selected_candidate_id is None
    assert flat.report.selection.reason_code == "no_eligible_candidate"
    assert all(
        "Does not improve on the reference control" in " ".join(c.ineligibility_reasons)
        for c in flat.report.candidates
        if c.kind == "design"
    )


async def test_hypotheses_get_per_scenario_data_and_needs_say_how_they_were_met(tmp_path):
    outcome = await run_study(make_request(), Harness(tmp_path).deps)
    document = load(outcome, "results.json")
    report = outcome.report
    assert report is not None

    point = next(p for p in report.hypotheses[0].data if p.candidate_id == "len45")
    assert [s.scenario_id for s in point.by_scenario] == [
        "quiet_conversation",
        "speech_in_babble",
        "distant_talker",
    ]
    for scenario in point.by_scenario:
        (case,) = [
            c
            for c in document["experiments"]
            if c["candidate_id"] == "len45" and c["scenario_id"] == scenario.scenario_id
        ]
        (value,) = [m["value"] for m in case["metrics"] if m["name"] == "fixture_audible_speech_fraction"]
        assert scenario.mean == value
        assert (scenario.n_completed, scenario.n_planned) == (1, 1)

    needs = {n.need: n for n in report.needs}
    assert needs["compact_size"].status == "addressed"
    assert "stayed within the plan's limit of at most 100 (mean 45)" in needs["compact_size"].explanation
    assert "improved on the reference control" not in needs["compact_size"].explanation
    assert "fixture_audible_speech_fraction improved on the reference control in distant_talker" in (
        needs["hear_coach"].explanation
    )


async def test_reported_numbers_are_the_evaluators_numbers(tmp_path):
    harness = Harness(tmp_path)
    outcome = await run_study(make_request(), harness.deps)
    fixture = DevelopmentFixtureEvaluator()
    plan = load(outcome, "plan.json")
    document = load(outcome, "results.json")

    for case in document["experiments"]:
        spec = next(e for e in plan["experiments"] if e["experiment_id"] == case["experiment_id"])
        from horn_study.contracts import ExperimentSpec

        direct = fixture.evaluate_experiment(ExperimentSpec.model_validate(spec))
        assert case["metrics"] == [m.model_dump(mode="json") for m in direct.metrics]
        assert case["evaluator_version"] == "fixture-0.1"

    selected = next(c for c in outcome.report.candidates if c.candidate_id == "len45")
    cases = [c for c in document["experiments"] if c["candidate_id"] == "len45"]
    values = [
        m["value"] for c in cases for m in c["metrics"] if m["name"] == "fixture_audible_speech_fraction"
    ]
    assert selected.primary_metric_mean == pytest.approx(sum(values) / 3)
    assert document["selected_candidate"]["candidate_id"] == "len45"
    assert document["selected_candidate"]["parameters"]["length_mm"] == 45.0
    assert document["result_label"] == "Development fixture output. Not simulation results."
    assert "DEVELOPMENT FIXTURE" in outcome.report.limitations[0]
    assert document["development_fixture_label"] == "Fictional thresholds for automated tests."


# --------------------------------------------------------------------------
# Interpretation has no power over results or execution
# --------------------------------------------------------------------------


async def test_the_interpreter_cannot_change_the_selection_or_run_anything(tmp_path):
    def overreaching(messages, bound):
        if not any(isinstance(m, AIMessage) for m in messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "evaluate_experiment", "args": {"candidate_id": "len120"}, "id": "e1"},
                ],
            )
        payload = narrative(
            summary="The best design is len30 and I recommend evaluating len120 next.",
            hypothesis_verdicts=[
                {"hypothesis_id": "H1", "verdict": "contradicted", "explanation": "x"},
                {"hypothesis_id": "H_invented", "verdict": "supported", "explanation": "y"},
            ],
        )
        return call("ReportNarrative", payload)

    harness = Harness(tmp_path, interpreter=overreaching)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert outcome.report.selected_candidate_id == "len45"
    assert [h.hypothesis_id for h in outcome.report.hypotheses] == ["H1"]
    assert len(harness.evaluator.calls) == 12
    assert harness.interpreter_model.log.bound_tool_sets == [["ReportNarrative"]] * len(
        harness.interpreter_model.log.bound_tool_sets
    )


async def test_the_report_survives_a_failed_interpretation(tmp_path):
    def broken(messages, bound):
        raise RuntimeError("model unavailable")

    harness = Harness(tmp_path, interpreter=broken)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert outcome.report.narrative_source == "unavailable"
    assert outcome.report.selected_candidate_id == "len45"
    assert outcome.report.hypotheses[0].verdict == "inconclusive"
    assert outcome.report.follow_up_proposals == ()
    assert any("written interpretation could not be generated" in t for t in outcome.report.limitations)


# --------------------------------------------------------------------------
# Follow-ups need a new user request
# --------------------------------------------------------------------------


async def test_a_suggested_follow_up_causes_no_evaluation_until_requested(tmp_path):
    harness = Harness(tmp_path)
    outcome = await run_study(make_request(), harness.deps)

    assert [p.proposal_id for p in outcome.report.follow_up_proposals] == ["FU1"]
    calls_at_completion = len(harness.evaluator.calls)
    model_calls = harness.research_model.log.calls
    await asyncio.sleep(0.2)
    assert len(harness.evaluator.calls) == calls_at_completion == 12
    assert harness.research_model.log.calls == model_calls
    assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task()] == []

    request = follow_up_request(tmp_path, outcome.study_id, "FU1", "study_followup_001")
    assert len(harness.evaluator.calls) == 12
    assert request["parent_study_id"] == outcome.study_id
    assert request["start"]["initiated_by"] == "user"
    assert request["start"]["action"] == "refine_design"


async def test_a_follow_up_is_a_new_study_and_the_parent_record_is_kept(tmp_path):
    parent = await run_study(make_request(), Harness(tmp_path).deps)
    before = digest(parent.directory)

    child_harness = Harness(tmp_path)
    request = follow_up_request(tmp_path, parent.study_id, "FU1", "study_followup_001")
    child = await run_study(request, child_harness.deps)

    assert child.state is StudyState.COMPLETED
    assert child.directory != parent.directory
    assert digest(parent.directory) == before
    document = load(child, "results.json")
    assert document["parent_study_id"] == parent.study_id
    assert document["prior_study"]["selected_candidate_id"] == "len45"
    assert document["prior_study"]["follow_up_proposal"]["proposal_id"] == "FU1"
    assert first(child, "study.started").data["start_action"] == "refine_design"


async def test_follow_ups_must_name_a_real_parent_and_proposal(tmp_path):
    harness = Harness(tmp_path)
    parent = await run_study(make_request(), harness.deps)

    from horn_study.followup import FollowUpError

    with pytest.raises(FollowUpError, match="no follow-up proposal 'FU9'"):
        follow_up_request(tmp_path, parent.study_id, "FU9", "x")
    orphan = make_request("orphan", parent_study_id="does_not_exist")
    with pytest.raises(InputRejected) as caught:
        await run_study(orphan, harness.deps)
    assert caught.value.issues[0].code == "follow_up.parent_unavailable"


async def test_an_existing_study_is_never_overwritten(tmp_path):
    harness = Harness(tmp_path)
    first_run = await run_study(make_request(), harness.deps)
    before = digest(first_run.directory)
    with pytest.raises(StudyExists):
        await run_study(make_request(), harness.deps)
    assert digest(first_run.directory) == before
    assert len(harness.evaluator.calls) == 12


# --------------------------------------------------------------------------
# Lifecycle and structure
# --------------------------------------------------------------------------


def test_the_lifecycle_only_moves_forward():
    assert allowed_transitions(StudyState.INTERPRETING) == {
        StudyState.COMPLETED,
        StudyState.FAILED,
        StudyState.CANCELLED,
    }
    for terminal in (StudyState.COMPLETED, StudyState.FAILED, StudyState.CANCELLED):
        assert allowed_transitions(terminal) == frozenset()
    machine = StudyStateMachine(EventBus("s"))
    with pytest.raises(IllegalTransition):
        machine.transition(StudyState.EVALUATING)
    machine.transition(StudyState.RESEARCHING)
    with pytest.raises(IllegalTransition):
        machine.transition(StudyState.CREATED)


async def test_nothing_leads_from_results_back_to_planning_or_evaluation(tmp_path):
    captured = {}

    class Capture(BaseTracer):
        def _persist_run(self, run: Run) -> None:
            captured["root"] = run

    harness = Harness(tmp_path, callbacks=[Capture()])
    from horn_study import workflow

    built = {}
    original = workflow.build_graph

    def spy(**kwargs):
        built["graph"] = original(**kwargs)
        return built["graph"]

    workflow.build_graph = spy
    try:
        await run_study(make_request(), harness.deps)
    finally:
        workflow.build_graph = original

    edges = {(edge.source, edge.target) for edge in built["graph"].get_graph().edges}

    def reachable(start: str) -> set[str]:
        seen, frontier = set(), [start]
        while frontier:
            node = frontier.pop()
            for source, target in edges:
                if source == node and target not in seen:
                    seen.add(target)
                    frontier.append(target)
        return seen

    assert reachable(NODE_EVALUATE) == {NODE_INTERPRET, "__end__"}
    assert reachable(NODE_INTERPRET) == {"__end__"}
    assert (NODE_FREEZE, NODE_PLAN) in edges
    assert all((name, NODE_SYNTHESIZE) in edges for name in RESEARCH_NODES)


async def test_the_trace_exposes_branches_planning_evaluation_and_report(tmp_path):
    roots: list[Run] = []

    class Capture(BaseTracer):
        def _persist_run(self, run: Run) -> None:
            roots.append(run)

    harness = Harness(tmp_path, callbacks=[Capture()])
    outcome = await run_study(make_request(), harness.deps)

    (root,) = roots
    assert root.name == f"study {outcome.study_id}"
    assert str(root.id) == outcome.events.history[0].trace.run_id
    children = {child.name: child for child in root.child_runs}
    assert set(children) >= {
        *RESEARCH_NODES,
        NODE_SYNTHESIZE,
        NODE_PLAN,
        NODE_FREEZE,
        NODE_EVALUATE,
        NODE_INTERPRET,
    }

    def names(run: Run) -> set[str]:
        found = {run.name}
        for child in run.child_runs:
            found |= names(child)
        return found

    assert "hearing_research_agent" in names(children["hearing_research"])
    assert "search_literature" in names(children["hearing_research"])
    assert "study_coordinator" in names(children[NODE_PLAN])
    assert "results_interpreter" in names(children[NODE_INTERPRET])

    attempts = [run for run in children[NODE_EVALUATE].child_runs if run.name == "evaluate_experiment"]
    assert len(attempts) == 12
    metadata = attempts[0].extra["metadata"]
    assert metadata["study_id"] == outcome.study_id
    assert metadata["attempt"] == 1
    assert metadata["evaluator_version"] == "fixture-0.1"
    assert metadata["plan_hash"] == load(outcome, "plan.json")["plan_hash"]
    assert {run.extra["metadata"]["experiment_id"] for run in attempts} == set(harness.evaluator.calls)
    assert "evaluate_experiment" not in names(children[NODE_INTERPRET])
    assert root.extra["metadata"]["evaluator_version"] == "fixture-0.1"


async def test_a_study_that_runs_too_long_fails_cleanly(tmp_path):
    harness = Harness(tmp_path)
    harness.research_model.delay = 5
    request = make_request()
    request["budget"]["max_run_seconds"] = 0.3
    outcome = await run_study(request, harness.deps)

    assert outcome.state is StudyState.FAILED
    assert outcome.failure["kind"] == "timeout"
    assert harness.evaluator.calls == []
    assert types(outcome)[-1] == "study.failed"


async def test_cancelling_a_study_records_the_cancellation(tmp_path):
    harness = Harness(tmp_path)
    harness.research_model.delay = 5
    task = asyncio.create_task(run_study(make_request(), harness.deps))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    events = read_events(ArtifactStore(tmp_path, "study_test_001"))
    assert events[-1].type == "study.cancelled"
    document = json.loads((tmp_path / "study_test_001" / "results.json").read_text())
    assert document["state"] == "CANCELLED"
    assert harness.evaluator.calls == []
