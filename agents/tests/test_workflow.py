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
from horn_study.research import INVESTIGATORS
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

EVIDENCE_TOOLS = {"search_literature", "read_source", "record_finding", "submit_finding"}
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


async def test_a_research_only_study_completes_without_planning_or_evaluating(tmp_path):
    """Catches the dashboard's study running the fixture planner and evaluator the lead now replaces."""
    harness = Harness(tmp_path)
    harness.deps.research_only = True
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    phases = [e.data["to"] for e in outcome.events.history if e.type == "study.state_changed"]
    assert phases == ["RESEARCHING", "COMPLETED"]
    assert harness.coordinator_model.log.calls == 0
    assert harness.evaluator.calls == []
    assert types(outcome)[-1] == "study.completed"


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


async def test_all_research_branches_overlap_and_return_identifiable_evidence(tmp_path):
    harness = Harness(tmp_path)
    outcome = await run_study(make_request(), harness.deps)
    history = outcome.events.history

    started = [e.sequence for e in history if e.type == "research.agent_started"]
    finished = [e.sequence for e in history if e.type == "research.agent_completed"]
    assert len(started) == len(finished) == len(INVESTIGATORS)
    assert max(started) < min(finished)
    assert harness.research_model.log.max_active == len(INVESTIGATORS)

    research = load(outcome, "research.json")
    assert [b["investigator"] for b in research["branches"]] == list(RESEARCH_NODES)
    assert {f["finding_id"] for f in research["findings"]} == {
        "hearing-F1",
        "context-F1",
        "design-F1",
        "fit-F1",
    }
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


async def test_the_report_states_how_much_of_the_evidence_is_scholarly(tmp_path):
    def cites_documentation(messages, bound):
        """The design investigator reads a repository directly instead of searching the literature."""
        who = investigator_of(messages)
        if who != "acoustic_design_research":
            return research_responder(messages, bound)
        step = sum(1 for m in messages if isinstance(m, AIMessage))
        url = "https://github.com/example/acoustics-tool"
        if step == 0:
            return call("read_source", {"url": url, "focus": "horn"}, "d-1")
        if step == 1:
            return call(
                "record_finding",
                {
                    "question": "q",
                    "source": url,
                    "claim": "The tool models path length.",
                    "evidence_passage": "The acoustic path length of a horn shifts the frequency region where its response peaks.",
                    "applicability": "a",
                    "limitations": "l",
                    "related_user_goal": "g",
                    "motivates": "m",
                },
                "d-2",
            )
        return call("InvestigatorOutput", investigator_report(who), "d-3")

    outcome = await run_study(make_request(), Harness(tmp_path, research=cites_documentation).deps)
    report = outcome.report
    assert report is not None
    assert report.findings_by_source_tier == {"scholarly": 3, "technical_documentation": 1}
    assert any(
        text.startswith("3 of 4 research findings rest on scholarly literature.")
        for text in report.limitations
    )
    research = load(outcome, "research.json")
    assert {f["finding_id"]: f["source_tier"] for f in research["findings"]}[
        "design-F1"
    ] == "technical_documentation"

    all_scholarly = await run_study(make_request("all_papers"), Harness(tmp_path).deps)
    assert all_scholarly.report is not None
    assert all_scholarly.report.findings_by_source_tier == {"scholarly": len(INVESTIGATORS)}
    assert not any("rest on scholarly literature" in text for text in all_scholarly.report.limitations)


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
    assert len(load(outcome, "research.json")["findings"]) == len(INVESTIGATORS)


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


# --------------------------------------------------------------------------
# A design must not lose to the control in any scenario
# --------------------------------------------------------------------------

PRIMARY = "fixture_audible_speech_fraction"
QUIET, BABBLE, DISTANT = "quiet_conversation", "speech_in_babble", "distant_talker"


class FixedScores(CountingEvaluator):
    """Returns chosen primary-metric values. Everything else is the fixture's own output.

    `scores` maps candidate -> scenario -> one value, or one value per seed.
    `resolution` replaces the primary metric's declared resolution.
    """

    def __init__(self, scores: dict[str, dict[str, Any]], resolution: float | None = None):
        super().__init__()
        self.scores, self.resolution = scores, resolution

    def get_evaluator_capabilities(self):
        capabilities = self.inner.get_evaluator_capabilities()
        if self.resolution is None:
            return capabilities
        metrics = tuple(
            m.model_copy(update={"resolution": self.resolution}) if m.name == PRIMARY else m
            for m in capabilities.metrics
        )
        return capabilities.model_copy(update={"metrics": metrics})

    def evaluate_experiment(self, spec):
        self.calls.append(spec.experiment_id)
        result = self.inner.evaluate_experiment(spec)
        value = self.scores[spec.candidate_id][spec.scenario_id]
        if isinstance(value, dict):
            value = value[spec.seed]
        metrics = tuple(
            m.model_copy(update={"value": value}) if m.name == PRIMARY else m for m in result.metrics
        )
        return result.model_copy(update={"metrics": metrics})


def summary_of(outcome, candidate_id: str):
    return next(c for c in outcome.report.candidates if c.candidate_id == candidate_id)


def standings(outcome, candidate_id: str) -> dict[str, str]:
    return {s.scenario_id: s.standing for s in summary_of(outcome, candidate_id).primary_metric_by_scenario}


async def test_a_design_that_loses_to_the_control_in_one_scenario_cannot_win(tmp_path):
    scores = {
        "unaided": {QUIET: 0.93, BABBLE: 0.30, DISTANT: 0.40},
        "len30": {QUIET: 0.667, BABBLE: 0.80, DISTANT: 0.90},
        "len45": {QUIET: 0.94, BABBLE: 0.50, DISTANT: 0.55},
        "len90": {QUIET: 0.93, BABBLE: 0.45, DISTANT: 0.45},
    }
    outcome = await run_study(make_request(), Harness(tmp_path, evaluator=FixedScores(scores)).deps)
    report = outcome.report

    loser = summary_of(outcome, "len30")
    assert loser.primary_metric_mean == max(c.primary_metric_mean for c in report.candidates)
    assert loser.improvement_over_reference == pytest.approx(0.789 - 0.5433, abs=1e-3)
    assert not loser.eligible
    assert loser.rank is None
    assert loser.ineligibility_reasons == (
        "Worse than the reference control in quiet_conversation (0.667 against 0.93), "
        "by more than the 0.01 fraction tolerance.",
    )
    assert standings(outcome, "len30") == {QUIET: "worse", BABBLE: "better", DISTANT: "better"}

    assert report.selected_candidate_id == "len45"
    assert report.selection.explanation == (
        f"'len45' has the best mean {PRIMARY} among eligible designs: 0.6633 fraction over 3 completed "
        "cases, against 0.5433 fraction for the reference control 'unaided'. In each of the 3 planned "
        "scenarios it is at least as good as the control, within the 0.01 fraction tolerance."
    )
    assert summary_of(outcome, "len90").rank == 2
    assert load(outcome, "results.json")["selected_candidate"]["candidate_id"] == "len45"


async def test_a_design_within_the_declared_resolution_of_the_control_stays_eligible(tmp_path):
    scores = {
        "unaided": {QUIET: 0.93, BABBLE: 0.30, DISTANT: 0.40},
        # Exactly the declared resolution (0.01) below the control in quiet: not a meaningful loss.
        "len30": {QUIET: 0.92, BABBLE: 0.80, DISTANT: 0.90},
        "len45": {QUIET: 0.925, BABBLE: 0.50, DISTANT: 0.55},
        # Just past the resolution: a loss.
        "len90": {QUIET: 0.919, BABBLE: 0.95, DISTANT: 0.95},
    }
    outcome = await run_study(make_request(), Harness(tmp_path, evaluator=FixedScores(scores)).deps)

    assert load(outcome, "plan.json")["selection_rule"]["scenario_tolerance"] == 0.01
    for candidate_id in ("len30", "len45"):
        assert summary_of(outcome, candidate_id).eligible
        assert standings(outcome, candidate_id)[QUIET] == "within_tolerance"
    assert summary_of(outcome, "len30").primary_metric_by_scenario[0].difference_from_reference == (
        pytest.approx(-0.01)
    )
    assert outcome.report.selected_candidate_id == "len30"
    assert summary_of(outcome, "len90").ineligibility_reasons == (
        "Worse than the reference control in quiet_conversation (0.919 against 0.93), "
        "by more than the 0.01 fraction tolerance.",
    )


async def test_a_scenario_at_the_metric_ceiling_does_not_disqualify_a_design(tmp_path):
    scores = {
        "unaided": {QUIET: 1.0, BABBLE: 0.30, DISTANT: 0.40},
        "len30": {QUIET: 1.0, BABBLE: 0.80, DISTANT: 0.90},
        "len45": {QUIET: 0.999, BABBLE: 0.85, DISTANT: 0.95},
        "len90": {QUIET: 1.0, BABBLE: 0.30, DISTANT: 0.40},
    }
    # No resolution declared: every difference counts, and equal is still not worse.
    harness = Harness(tmp_path, evaluator=FixedScores(scores, resolution=0.0))
    outcome = await run_study(make_request(), harness.deps)

    assert load(outcome, "plan.json")["selection_rule"]["scenario_tolerance"] == 0.0
    at_ceiling = summary_of(outcome, "len30")
    assert at_ceiling.eligible
    assert at_ceiling.primary_metric_by_scenario[0].difference_from_reference == 0.0
    assert standings(outcome, "len30") == {QUIET: "within_tolerance", BABBLE: "better", DISTANT: "better"}
    assert outcome.report.selected_candidate_id == "len30"
    assert summary_of(outcome, "len45").ineligibility_reasons == (
        "Worse than the reference control in quiet_conversation (0.999 against 1).",
    )
    # Never worse anywhere, but no better overall either: equal to the control is not a win.
    assert summary_of(outcome, "len90").ineligibility_reasons == (
        f"Does not improve on the reference control for {PRIMARY}.",
    )


async def test_nothing_is_selected_when_every_design_loses_somewhere(tmp_path):
    scores = {
        "unaided": {QUIET: 0.93, BABBLE: 0.30, DISTANT: 0.40},
        "len30": {QUIET: 0.667, BABBLE: 0.80, DISTANT: 0.90},
        "len45": {QUIET: 0.95, BABBLE: 0.20, DISTANT: 0.90},
        "len90": {QUIET: 0.70, BABBLE: 0.90, DISTANT: 0.25},
    }
    outcome = await run_study(make_request(), Harness(tmp_path, evaluator=FixedScores(scores)).deps)
    report = outcome.report

    assert outcome.state is StudyState.COMPLETED
    assert all(c.improvement_over_reference > 0 for c in report.candidates if c.kind == "design")
    assert report.selected_candidate_id is None
    assert report.selection.reason_code == "no_eligible_candidate"
    assert report.selection.explanation == (
        "No design was selected: no candidate completed all planned cases, met the plan's constraints, "
        "stayed at least as good as the reference control 'unaided' in every scenario, and improved on "
        f"it over all cases for {PRIMARY}. Worse than the control, by more than the 0.01 fraction "
        "tolerance: 'len30' in quiet_conversation (0.667 against 0.93); 'len45' in speech_in_babble "
        "(0.2 against 0.3); 'len90' in quiet_conversation (0.7 against 0.93), distant_talker "
        "(0.25 against 0.4)."
    )
    # The progress event has room for less, and stops at the end of a sentence.
    assert first(outcome, "report.completed").summary == (
        "No design was selected: no candidate completed all planned cases, met the plan's constraints, "
        "stayed at least as good as the reference control 'unaided' in every scenario, and improved on "
        f"it over all cases for {PRIMARY}."
    )
    document = load(outcome, "results.json")
    assert document["selected_candidate_id"] is None
    assert document["selected_candidate"] is None
    assert all(n.status != "addressed" for n in report.needs)


async def test_scenarios_are_compared_on_their_means_over_seeds(tmp_path):
    draft = valid_draft()
    draft["candidates"] = [c for c in draft["candidates"] if c["candidate_id"] != "len90"]
    draft["hypotheses"][0]["candidate_ids"] = ["len30", "len45"]
    draft["scenario_ids"] = [QUIET, BABBLE]
    draft["seeds"] = [0, 1]
    for item in draft["needs_coverage"]:
        item["scenario_ids"] = [BABBLE] if item["scenario_ids"] else []
    scores = {
        "unaided": {QUIET: 0.90, BABBLE: 0.30},
        # One seed beats the control in quiet, but the scenario mean (0.89) does not.
        "len30": {QUIET: {0: 0.80, 1: 0.98}, BABBLE: 0.90},
        # One seed is below the control in quiet, but the scenario mean (0.91) is not.
        "len45": {QUIET: {0: 0.85, 1: 0.97}, BABBLE: 0.60},
    }
    harness = Harness(
        tmp_path, evaluator=FixedScores(scores, resolution=0.0), coordinator=coordinator_responder(draft)
    )
    outcome = await run_study(make_request(), harness.deps)

    assert len(harness.evaluator.calls) == 3 * 2 * 2
    quiet = summary_of(outcome, "len30").primary_metric_by_scenario[0]
    assert (quiet.mean, quiet.reference_mean) == (pytest.approx(0.89), pytest.approx(0.90))
    assert (quiet.n_completed, quiet.n_planned) == (2, 2)
    assert summary_of(outcome, "len30").ineligibility_reasons == (
        "Worse than the reference control in quiet_conversation (0.89 against 0.9).",
    )
    assert standings(outcome, "len45") == {QUIET: "better", BABBLE: "better"}
    assert outcome.report.selected_candidate_id == "len45"


async def test_a_scenario_with_a_missing_case_is_never_counted_as_not_worse(tmp_path):
    harness = Harness(tmp_path, evaluator=ScenarioFailure({"len45"}))
    outcome = await run_study(make_request(), harness.deps)

    incomplete = summary_of(outcome, "len45")
    assert not incomplete.eligible
    babble = next(s for s in incomplete.primary_metric_by_scenario if s.scenario_id == BABBLE)
    assert (babble.mean, babble.n_completed, babble.n_planned) == (None, 0, 1)
    assert babble.reference_mean is not None
    assert babble.difference_from_reference is None
    assert babble.standing == "not_compared"
    assert standings(outcome, "len45") == {QUIET: "better", BABBLE: "not_compared", DISTANT: "better"}

    # Without the control's case no design can be compared in that scenario at all.
    no_control = await run_study(
        make_request("no_control"), Harness(tmp_path, evaluator=ScenarioFailure({"unaided"})).deps
    )
    for candidate in no_control.report.candidates:
        assert not candidate.eligible
        assert standings(no_control, candidate.candidate_id)[BABBLE] == "not_compared"


async def test_per_scenario_numbers_in_the_report_are_the_evaluators_numbers(tmp_path):
    outcome = await run_study(make_request(), Harness(tmp_path).deps)
    document = load(outcome, "results.json")

    def returned(candidate_id: str, scenario_id: str) -> float:
        (case,) = [
            c
            for c in document["experiments"]
            if c["candidate_id"] == candidate_id and c["scenario_id"] == scenario_id
        ]
        (value,) = [m["value"] for m in case["metrics"] if m["name"] == PRIMARY]
        return value

    assert [c["candidate_id"] for c in document["report"]["candidates"]] == [
        "unaided",
        "len30",
        "len45",
        "len90",
    ]
    for candidate in document["report"]["candidates"]:
        rows = candidate["primary_metric_by_scenario"]
        assert [row["scenario_id"] for row in rows] == [QUIET, BABBLE, DISTANT]
        for row in rows:
            own = returned(candidate["candidate_id"], row["scenario_id"])
            control = returned("unaided", row["scenario_id"])
            assert row["mean"] == own
            assert row["reference_mean"] == control
            assert row["difference_from_reference"] == own - control
            assert (row["n_completed"], row["n_planned"]) == (1, 1)
        assert candidate["primary_metric_mean"] == pytest.approx(sum(row["mean"] for row in rows) / 3)
    assert {row["standing"] for row in document["report"]["candidates"][0]["primary_metric_by_scenario"]} == {
        "within_tolerance"
    }


async def test_the_interpreter_is_shown_where_each_design_wins_and_loses(tmp_path):
    seen: dict[str, Any] = {}

    def capture(messages, bound):
        seen["system"] = str(messages[0].content)
        seen["brief"] = json.loads(str(messages[-1].content).removeprefix("Study results:\n\n"))
        return call("ReportNarrative", narrative())

    scores = {
        "unaided": {QUIET: 0.93, BABBLE: 0.30, DISTANT: 0.40},
        "len30": {QUIET: 0.667, BABBLE: 0.80, DISTANT: 0.90},
        "len45": {QUIET: 0.94, BABBLE: 0.50, DISTANT: 0.55},
        "len90": {QUIET: 0.93, BABBLE: 0.45, DISTANT: 0.45},
    }
    harness = Harness(tmp_path, evaluator=FixedScores(scores), interpreter=capture)
    outcome = await run_study(make_request(), harness.deps)

    assert "not worse than the reference control in any scenario" in " ".join(seen["system"].split())
    assert seen["brief"]["plan"]["selection_rule"]["scenario_tolerance"] == 0.01
    shown = next(c for c in seen["brief"]["candidate_comparison"] if c["candidate_id"] == "len30")
    assert shown["primary_metric_by_scenario"] == [
        s.model_dump(mode="json") for s in summary_of(outcome, "len30").primary_metric_by_scenario
    ]
    assert shown["primary_metric_by_scenario"][0]["standing"] == "worse"
    assert shown["ineligibility_reasons"] == list(summary_of(outcome, "len30").ineligibility_reasons)


async def test_a_plan_without_required_coverage_is_sent_back_before_freezing(tmp_path):
    narrow = valid_draft(needs=False)
    narrow["scenario_ids"] = [BABBLE]
    harness = Harness(tmp_path, coordinator=coordinator_responder(narrow, valid_draft(needs=False)))
    outcome = await run_study(make_request(needs=False), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    revision = first(outcome, "plan.revision_requested")
    assert revision.sequence < first(outcome, "plan.frozen").sequence
    assert revision.data["errors"] == [
        "Too few scenarios: the plan lists 1 supported scenario, but this evaluator requires at least 2 "
        "in every study. Add from: quiet_conversation, distant_talker.",
        "Missing required coverage: every study must include at least one scenario tagged 'quiet'. "
        "Add one of: quiet_conversation.",
    ]
    assert load(outcome, "plan.json")["scenario_ids"] == [QUIET, BABBLE, DISTANT]
    assert load(outcome, "plan.json")["plan_version"] == 2
    assert {e.split("--")[1] for e in harness.evaluator.calls} == {QUIET, BABBLE, DISTANT}

    stubborn = Harness(tmp_path, coordinator=coordinator_responder(narrow))
    failed = await run_study(make_request("never_broadened", needs=False), stubborn.deps)
    assert failed.state is StudyState.FAILED
    assert failed.failure["kind"] == "plan_invalid"
    assert stubborn.evaluator.calls == []


async def test_the_coordinator_is_given_the_coverage_rules_and_planning_notes(tmp_path):
    seen: dict[str, str] = {}

    def capture(messages, bound):
        seen["system"] = " ".join(str(messages[0].content).split())
        seen["brief"] = str(messages[1].content)
        return coordinator_responder(valid_draft())(messages, bound)

    harness = Harness(tmp_path, coordinator=capture)
    outcome = await run_study(make_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    capabilities = load(outcome, "capabilities.json")
    assert capabilities["required_scenario_tags"] == ["quiet", "noise"]
    assert capabilities["minimum_scenarios"] == 2
    for note in capabilities["planning_notes"]:
        assert json.dumps(note) in seen["brief"]
    assert "capabilities.planning_notes" in seen["system"]
    assert "capabilities.required_scenario_tags" in seen["system"]
    assert "not worse than the reference control on the primary metric in any scenario" in seen["system"]


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
