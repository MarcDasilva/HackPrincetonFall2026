"""Plan validation: only executable, in-budget, controlled plans can be frozen."""

from __future__ import annotations

import pytest
from helpers import design, make_request, valid_draft

from horn_study.evaluator_adapter import DevelopmentFixtureEvaluator
from horn_study.intake import parse_request, validate_request
from horn_study.planner import PlanDraft, build_plan, freeze_plan

CAPS = DevelopmentFixtureEvaluator().get_evaluator_capabilities()
FINDINGS = frozenset({"hearing-F1", "context-F1", "design-F1"})


def package(**overrides):
    return validate_request(parse_request(make_request(**overrides)), CAPS)


def check(draft: dict, **overrides):
    return build_plan(PlanDraft.model_validate(draft), package(**overrides), FINDINGS, plan_version=1)


def errors_of(draft: dict, **overrides) -> str:
    plan, errors = check(draft, **overrides)
    assert plan is None
    return "\n".join(errors)


def test_valid_draft_expands_to_every_candidate_in_every_scenario():
    plan, errors = check(valid_draft())
    assert errors == []
    assert len(plan.experiments) == 4 * 3
    assert len({e.experiment_id for e in plan.experiments}) == 12
    per_candidate = {
        c.candidate_id: [e.scenario_id for e in plan.experiments if e.candidate_id == c.candidate_id]
        for c in plan.candidates
    }
    assert all(
        scenarios == ["quiet_conversation", "speech_in_babble", "distant_talker"]
        for scenarios in per_candidate.values()
    )
    assert all(e.calibration_ref == CAPS.calibration.calibration_ref for e in plan.experiments)
    assert all(e.hearing_input == package().hearing_input for e in plan.experiments)
    assert plan.selection_rule.direction == "higher_is_better"


def test_over_budget_workload_counts_scenarios_canals_and_seeds():
    draft = valid_draft()
    draft["canal_config_ids"] = ["default_canal", "short_canal"]
    draft["seeds"] = [0, 1]
    message = errors_of(draft)
    assert "4 candidates x 3 scenarios x 2 canal configurations x 2 seeds = 48" in message
    assert "budget allows 12" in message


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d["candidates"][1]["parameters"][0].update(value=500), "above the maximum 120 mm"),
        (
            lambda d: d["candidates"][1]["parameters"].pop(),
            "missing a value for parameter 'mouth_diameter_mm'",
        ),
        (
            lambda d: d["candidates"][1]["parameters"].append({"name": "wall_mm", "value": 1, "choice": ""}),
            "'wall_mm' is not a parameter",
        ),
        (
            lambda d: d["candidates"][1].update(family_id="spiral_horn"),
            "geometry family 'spiral_horn' is not supported",
        ),
        (lambda d: d["scenario_ids"].append("concert_hall"), "Scenario 'concert_hall' is not supported"),
        (
            lambda d: d["selection"].update(primary_metric="speech_intelligibility_index"),
            "metric 'speech_intelligibility_index' is not supported",
        ),
        (lambda d: d.update(fidelity="full_3d"), "Fidelity 'full_3d' is not supported"),
        (lambda d: d["candidates"].pop(0), "Missing control"),
        (lambda d: d["selection"].update(reference_candidate_id="len30"), "must be a baseline control"),
        (lambda d: d["candidates"].append(design("len30_copy", 30)), "duplicates 'len30'"),
        (lambda d: d["candidates"].append(design("len30", 31)), "Duplicate candidate_id 'len30'"),
        (lambda d: d["hypotheses"][0].update(supporting_finding_ids=["design-F9"]), "do not exist"),
        (
            lambda d: d["hypotheses"][0].update(supporting_finding_ids=[]),
            "cite at least one recorded finding",
        ),
        (lambda d: d["hypotheses"][0].update(candidate_ids=["len30"]), "at least two candidates"),
        (lambda d: d.update(seeds=[0, 1, 2, 3]), "at most 3 repetitions"),
    ],
)
def test_unsupported_or_malformed_plans_are_rejected(mutate, expected):
    draft = valid_draft()
    mutate(draft)
    assert expected in errors_of(draft)


def test_every_user_need_must_be_accounted_for():
    draft = valid_draft()
    draft["needs_coverage"] = [n for n in draft["needs_coverage"] if n["need"] != "hear_coach"]
    assert "missing the user's need 'hear_coach'" in errors_of(draft)


def test_adding_a_priority_changes_what_a_valid_plan_must_contain():
    request = make_request()
    request["needs_profile"]["priorities"].append("music quality")
    plan, errors = build_plan(
        PlanDraft.model_validate(valid_draft()),
        validate_request(parse_request(request), CAPS),
        FINDINGS,
        plan_version=1,
    )
    assert plan is None
    assert errors == [
        "needs_coverage is missing the user's need 'music_quality'. Classify it as 'modeled' or 'untested'."
    ]


def test_an_unsupported_need_cannot_be_dressed_up_as_modeled():
    draft = valid_draft()
    retention = next(n for n in draft["needs_coverage"] if n["need"] == "secure_retention")
    retention.update(classification="modeled", metric_names=["fixture_audible_speech_fraction"])
    assert "declares this requirement unsupported" in errors_of(draft)

    invented = valid_draft()
    next(n for n in invented["needs_coverage"] if n["need"] == "sports").update(
        scenario_ids=[], metric_names=["retention_force_newtons"]
    )
    assert "metric 'retention_force_newtons' is not supported" in errors_of(invented)


def test_default_context_needs_no_coverage():
    plan, errors = check(valid_draft(needs=False), needs=False)
    assert errors == []
    assert plan.needs_coverage == ()
    assert plan.study_context_name == "default_everyday_listening"


def test_freezing_stamps_a_hash_that_detects_any_change():
    plan, _ = check(valid_draft())
    assert not plan.is_frozen
    frozen = freeze_plan(plan)
    assert frozen.is_frozen
    assert frozen.plan_hash == frozen.compute_hash()
    tampered = frozen.model_copy(update={"scenario_ids": ("quiet_conversation",)})
    assert tampered.plan_hash != tampered.compute_hash()
    with pytest.raises(ValueError, match="already frozen"):
        freeze_plan(frozen)
