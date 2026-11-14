"""Plan validation: only executable, in-budget, controlled plans can be frozen."""

from __future__ import annotations

import pytest
from helpers import design, make_request, valid_draft
from pydantic import ValidationError

from horn_study.contracts import EvaluatorCapabilities
from horn_study.evaluator_adapter import DevelopmentFixtureEvaluator
from horn_study.intake import parse_request, validate_request
from horn_study.planner import COORDINATOR_PROMPT, PlanDraft, build_plan, freeze_plan
from horn_study.research import INVESTIGATORS

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


def test_a_plan_missing_a_required_kind_of_scenario_is_rejected_until_it_is_added():
    assert CAPS.required_scenario_tags == ("quiet", "noise")
    draft = valid_draft(needs=False)
    draft["scenario_ids"] = ["quiet_conversation", "distant_talker"]
    plan, errors = check(draft, needs=False)
    assert plan is None
    assert errors == [
        "Missing required coverage: every study must include at least one scenario tagged 'noise'. "
        "Add one of: speech_in_babble."
    ]

    draft["scenario_ids"].append("speech_in_babble")
    plan, errors = check(draft, needs=False)
    assert errors == []
    assert plan.scenario_ids == ("quiet_conversation", "distant_talker", "speech_in_babble")


def test_a_plan_with_too_few_scenarios_is_rejected_until_it_is_broadened():
    assert CAPS.minimum_scenarios == 2
    draft = valid_draft(needs=False)
    draft["scenario_ids"] = ["speech_in_babble"]
    plan, errors = check(draft, needs=False)
    assert plan is None
    assert errors == [
        "Too few scenarios: the plan lists 1 supported scenario, but this evaluator requires at least 2 "
        "in every study. Add from: quiet_conversation, distant_talker.",
        "Missing required coverage: every study must include at least one scenario tagged 'quiet'. "
        "Add one of: quiet_conversation.",
    ]

    draft["scenario_ids"] = ["speech_in_babble", "quiet_conversation"]
    plan, errors = check(draft, needs=False)
    assert errors == []
    assert len(plan.experiments) == 4 * 2


def test_an_unsupported_scenario_does_not_count_toward_coverage():
    draft = valid_draft(needs=False)
    draft["scenario_ids"] = ["quiet_conversation", "concert_hall"]
    message = errors_of(draft, needs=False)
    assert "Scenario 'concert_hall' is not supported" in message
    assert "Too few scenarios: the plan lists 1 supported scenario" in message
    assert "at least one scenario tagged 'noise'" in message


def test_going_over_budget_does_not_invite_dropping_required_coverage():
    draft = valid_draft()
    draft["candidates"].append(design("len60", 60))
    message = errors_of(draft)
    assert "Remove candidates, canal configurations, or seeds first." in message
    assert (
        "Scenarios can be removed only while the plan keeps at least 2 scenarios and at least one "
        "scenario tagged each of 'quiet', 'noise'."
    ) in message


def test_an_evaluator_that_declares_no_coverage_accepts_a_single_scenario():
    undeclared = EvaluatorCapabilities.model_validate(
        CAPS.model_dump(
            mode="json", exclude={"required_scenario_tags", "minimum_scenarios", "planning_notes"}
        )
    )
    assert (undeclared.required_scenario_tags, undeclared.minimum_scenarios) == ((), 1)
    draft = valid_draft(needs=False)
    draft["scenario_ids"] = ["speech_in_babble"]
    plan, errors = build_plan(
        PlanDraft.model_validate(draft),
        validate_request(parse_request(make_request(needs=False)), undeclared),
        FINDINGS,
        plan_version=1,
    )
    assert errors == []
    assert plan.scenario_ids == ("speech_in_babble",)

    over_budget = valid_draft(needs=False)
    over_budget["candidates"].append(design("len60", 60))
    _, errors = build_plan(
        PlanDraft.model_validate(over_budget),
        validate_request(parse_request(make_request(needs=False)), undeclared),
        FINDINGS,
        plan_version=1,
    )
    assert errors[0].endswith("Remove candidates, scenarios, canal configurations, or seeds.")


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        (
            {"required_scenario_tags": ["quiet", "music"]},
            r"\['music'\] are not carried by any declared scenario",
        ),
        ({"minimum_scenarios": 4}, "minimum_scenarios is 4 but only 3 scenarios are declared"),
    ],
)
def test_coverage_no_plan_could_meet_is_refused_when_capabilities_are_read(declared, expected):
    with pytest.raises(ValidationError, match=expected):
        EvaluatorCapabilities.model_validate({**CAPS.model_dump(mode="json"), **declared})


def test_the_frozen_rule_records_the_per_scenario_tolerance_from_the_metric():
    plan, _ = check(valid_draft())
    rule = plan.selection_rule
    assert CAPS.metric("fixture_audible_speech_fraction").resolution == 0.01
    assert rule.scenario_tolerance == 0.01
    assert rule.require_not_worse_than_reference_in_every_scenario is True

    by_gain = valid_draft()
    by_gain["selection"]["primary_metric"] = "fixture_target_band_gain_db"
    plan, errors = check(by_gain)
    assert errors == []
    assert plan.selection_rule.scenario_tolerance == 0.0


def test_the_coordinator_cannot_switch_the_per_scenario_rule_off():
    draft = valid_draft()
    draft["selection"]["require_not_worse_than_reference_in_every_scenario"] = False
    draft["selection"]["scenario_tolerance"] = 1.0
    plan, errors = check(draft)
    assert errors == []
    assert plan.selection_rule.require_not_worse_than_reference_in_every_scenario is True
    assert plan.selection_rule.scenario_tolerance == 0.01
    assert "scenario_tolerance" not in PlanDraft.model_json_schema()["$defs"]["DraftSelection"]["properties"]


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


def test_an_informational_metric_cannot_rank_designs_or_stand_for_a_need_without_a_limit():
    length = next(m for m in CAPS.metrics if m.name == "fixture_device_length_mm")
    neutral = CAPS.model_copy(
        update={
            "metrics": tuple(
                m.model_copy(update={"direction": "informational"}) if m is length else m
                for m in CAPS.metrics
            )
        }
    )

    def check_neutral(draft: dict):
        return build_plan(
            PlanDraft.model_validate(draft),
            validate_request(parse_request(make_request()), neutral),
            FINDINGS,
            plan_version=1,
        )

    # valid_draft uses the length metric as a tie-breaker, which an informational metric cannot be.
    plan, errors = check_neutral(valid_draft())
    assert plan is None
    assert any("is informational and has no better or worse direction" in e for e in errors)

    constrained = valid_draft()
    constrained["selection"]["tie_breaker_metrics"] = []
    plan, errors = check_neutral(constrained)
    assert errors == []
    assert plan is not None

    unconstrained = valid_draft()
    unconstrained["selection"]["tie_breaker_metrics"] = []
    unconstrained["selection"]["constraints"] = []
    plan, errors = check_neutral(unconstrained)
    assert plan is None
    assert any("only through a selection constraint" in e for e in errors)


def test_the_coordinator_is_told_what_every_investigator_researched():
    assert len(INVESTIGATORS) == 4
    for spec in INVESTIGATORS:
        assert spec.covers in COORDINATOR_PROMPT
    assert "Three investigators" not in COORDINATOR_PROMPT
    assert "{" not in COORDINATOR_PROMPT
