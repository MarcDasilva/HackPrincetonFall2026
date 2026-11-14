"""The selection rule applied directly to a frozen plan and chosen results."""

from __future__ import annotations

from helpers import make_request, valid_draft

from horn_study.contracts import ExperimentRecord, StudyPlan
from horn_study.evaluator_adapter import DevelopmentFixtureEvaluator
from horn_study.intake import parse_request, validate_request
from horn_study.planner import PlanDraft, build_plan, freeze_plan
from horn_study.reporting import summarize_candidates

FIXTURE = DevelopmentFixtureEvaluator()
CAPS = FIXTURE.get_evaluator_capabilities()
FRACTION = "fixture_audible_speech_fraction"
GAIN = "fixture_target_band_gain_db"
LENGTH = "fixture_device_length_mm"
QUIET, BABBLE, DISTANT = "quiet_conversation", "speech_in_babble", "distant_talker"


def frozen_plan(primary_metric: str) -> StudyPlan:
    draft = valid_draft()
    draft["selection"].update(primary_metric=primary_metric, tie_breaker_metrics=[], constraints=[])
    package = validate_request(parse_request(make_request()), CAPS)
    plan, errors = build_plan(
        PlanDraft.model_validate(draft), package, frozenset({"design-F1", "hearing-F1"}), 1
    )
    assert errors == []
    assert plan is not None
    return freeze_plan(plan)


def records_with(plan: StudyPlan, scores: dict[str, dict[str, float]]) -> list[ExperimentRecord]:
    """One completed record per planned case, with the primary metric set from `scores`."""
    metric = plan.selection_rule.primary_metric
    records = []
    for spec in plan.experiments:
        result = FIXTURE.evaluate_experiment(spec)
        value = scores[spec.candidate_id][spec.scenario_id]
        metrics = tuple(
            m.model_copy(update={"value": value}) if m.name == metric else m for m in result.metrics
        )
        records.append(
            ExperimentRecord(
                experiment_id=spec.experiment_id,
                candidate_id=spec.candidate_id,
                spec_hash=spec.spec_hash(),
                outcome="completed",
                result=result.model_copy(update={"metrics": metrics}),
            )
        )
    return records


def test_worse_means_higher_when_the_primary_metric_is_lower_is_better():
    plan = frozen_plan(LENGTH)
    assert (plan.selection_rule.direction, plan.selection_rule.scenario_tolerance) == ("lower_is_better", 0.0)
    scores = {
        "unaided": {QUIET: 50.0, BABBLE: 50.0, DISTANT: 50.0},
        "len30": {QUIET: 40.0, BABBLE: 40.0, DISTANT: 55.0},
        "len45": {QUIET: 45.0, BABBLE: 45.0, DISTANT: 50.0},
        "len90": {QUIET: 60.0, BABBLE: 60.0, DISTANT: 60.0},
    }
    summaries, selection = summarize_candidates(plan, records_with(plan, scores), CAPS)
    by_id = {s.candidate_id: s for s in summaries}

    # The lowest (best) mean of all, but longer than the control in one scenario.
    assert by_id["len30"].primary_metric_mean == 45.0
    assert by_id["len30"].improvement_over_reference == 5.0
    assert by_id["len30"].ineligibility_reasons == (
        "Worse than the reference control in distant_talker (55 against 50).",
    )
    distant = by_id["len30"].primary_metric_by_scenario[2]
    assert (distant.difference_from_reference, distant.standing) == (-5.0, "worse")
    assert [s.standing for s in by_id["len45"].primary_metric_by_scenario] == [
        "better",
        "better",
        "within_tolerance",
    ]
    assert selection.selected_candidate_id == "len45"
    assert by_id["len90"].ineligibility_reasons == (
        "Worse than the reference control in quiet_conversation (60 against 50), "
        "speech_in_babble (60 against 50), distant_talker (60 against 50).",
        f"Does not improve on the reference control for {LENGTH}.",
    )


def test_a_loss_too_small_to_show_in_four_digits_is_still_printed_as_a_difference():
    plan = frozen_plan(GAIN)
    assert plan.selection_rule.scenario_tolerance == 0.0
    scores = {
        "unaided": {QUIET: 0.93001, BABBLE: 0.3, DISTANT: 0.4},
        "len30": {QUIET: 0.92996, BABBLE: 0.8, DISTANT: 0.9},
        "len45": {QUIET: 0.93001, BABBLE: 0.5, DISTANT: 0.5},
        "len90": {QUIET: 0.93001, BABBLE: 0.4, DISTANT: 0.4},
    }
    summaries, selection = summarize_candidates(plan, records_with(plan, scores), CAPS)

    loser = next(s for s in summaries if s.candidate_id == "len30")
    assert loser.ineligibility_reasons == (
        "Worse than the reference control in quiet_conversation (0.92996 against 0.93001).",
    )
    assert selection.selected_candidate_id == "len45"


def test_a_scenario_with_nothing_to_compare_never_counts_as_not_worse():
    plan = frozen_plan(FRACTION)
    scores = {
        "unaided": {QUIET: 0.5, BABBLE: 0.3, DISTANT: 0.4},
        "len30": {QUIET: 0.6, BABBLE: 0.8, DISTANT: 0.9},
        "len45": {QUIET: 0.6, BABBLE: 0.5, DISTANT: 0.5},
        "len90": {QUIET: 0.6, BABBLE: 0.4, DISTANT: 0.5},
    }
    records = records_with(plan, scores)
    assert summarize_candidates(plan, records, CAPS)[1].selected_candidate_id == "len30"

    # A plan that names a scenario none of its cases cover leaves that scenario unproven.
    uncovered = plan.model_copy(update={"scenario_ids": (*plan.scenario_ids, "empty_room")})
    summaries, selection = summarize_candidates(uncovered, records, CAPS)

    assert selection.selected_candidate_id is None
    assert selection.reason_code == "no_eligible_candidate"
    for summary in summaries:
        last = summary.primary_metric_by_scenario[-1]
        assert (last.scenario_id, last.mean, last.n_planned, last.standing) == (
            "empty_room",
            None,
            0,
            "not_compared",
        )
        if summary.kind == "design":
            assert summary.all_cases_completed
            assert summary.ineligibility_reasons == (
                f"No complete {FRACTION} data to compare with the reference control in empty_room.",
            )
