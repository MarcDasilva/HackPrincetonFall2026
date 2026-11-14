"""Profile intake: supplied results are checked, preserved, and never invented."""

from __future__ import annotations

import pytest
from helpers import make_request, measurements

from horn_study.evaluator_adapter import DevelopmentFixtureEvaluator
from horn_study.intake import DEFAULT_CONTEXT_NAME, InputRejected, parse_request, validate_request

CAPS = DevelopmentFixtureEvaluator().get_evaluator_capabilities()


def accept(raw):
    return validate_request(parse_request(raw), CAPS)


def reject(raw) -> list[str]:
    with pytest.raises(InputRejected) as caught:
        accept(raw)
    return [issue.code for issue in caught.value.issues]


def test_supplied_results_reach_the_evaluator_input_unchanged():
    raw = make_request()
    raw["hearing_profile"]["tested_on"] = "2026-03-02"
    raw["hearing_profile"]["original_report_ref"] = "report-17.pdf"
    package = accept(raw)
    used = package.hearing_input
    assert used.source == "user_entered_test_results"
    assert used.target_ear == "right"
    assert str(used.tested_on) == "2026-03-02"
    assert used.original_report_ref == "report-17.pdf"
    assert [
        (m.ear, m.frequency_hz, m.threshold_db_hl, m.measurement_type, m.status) for m in used.measurements
    ] == [
        ("right", f, t, "air_conduction", "measured")
        for f, t in ((250, 15), (500, 20), (1000, 30), (2000, 45), (4000, 55), (8000, 50))
    ]


def test_missing_required_frequency_is_reported_not_filled():
    raw = make_request()
    raw["hearing_profile"]["measurements"] = [m for m in measurements() if m["frequency_hz"] != 2000]
    with pytest.raises(InputRejected) as caught:
        accept(raw)
    (issue,) = caught.value.issues
    assert issue.code == "hearing.required_frequency_missing"
    assert "2000 Hz" in issue.message
    assert "right ear" in issue.message


def test_other_ear_is_never_copied_to_the_target_ear():
    raw = make_request()
    raw["hearing_profile"]["measurements"] = measurements(ear="left")
    codes = reject(raw)
    assert codes == ["hearing.required_frequency_missing"] * 4


def test_other_ear_and_unsupported_types_are_retained_but_unused():
    raw = make_request()
    raw["hearing_profile"]["measurements"] = [
        *measurements(),
        {"ear": "left", "frequency_hz": 1000, "threshold_db_hl": 10},
        {"ear": "right", "frequency_hz": 1000, "threshold_db_hl": 25, "measurement_type": "bone_conduction"},
    ]
    package = accept(raw)
    assert all(
        m.ear == "right" and m.measurement_type == "air_conduction"
        for m in package.hearing_input.measurements
    )
    unused = {(m.ear, m.measurement_type) for m in package.hearing_input.retained_but_unused}
    assert unused == {("left", "air_conduction"), ("right", "bone_conduction")}


def test_no_response_marker_is_preserved_and_not_turned_into_a_threshold():
    raw = make_request()
    raw["hearing_profile"]["measurements"] = [m for m in measurements() if m["frequency_hz"] != 4000] + [
        {"ear": "right", "frequency_hz": 4000, "status": "no_response", "no_response_at_db_hl": 110}
    ]
    assert reject(raw) == ["hearing.required_frequency_unusable"]


def test_a_marker_cannot_carry_a_numeric_threshold():
    raw = make_request()
    raw["hearing_profile"]["measurements"][0] = {
        "ear": "right",
        "frequency_hz": 250,
        "status": "unreadable",
        "threshold_db_hl": 30,
    }
    with pytest.raises(InputRejected) as caught:
        parse_request(raw)
    assert "cannot carry a numeric threshold" in caught.value.issues[0].message


def test_out_of_range_threshold_is_rejected():
    raw = make_request()
    raw["hearing_profile"]["measurements"][2]["threshold_db_hl"] = 450
    assert "hearing.threshold_out_of_range" in reject(raw)


def test_conflicting_duplicate_values_are_rejected():
    raw = make_request()
    raw["hearing_profile"]["measurements"].append(
        {"ear": "right", "frequency_hz": 1000, "threshold_db_hl": 60}
    )
    assert reject(raw) == ["hearing.duplicate_measurement"]


def test_a_budget_too_small_for_the_required_coverage_is_rejected_before_anything_runs():
    assert CAPS.minimum_scenarios == 2
    raw = make_request()
    raw["budget"]["max_evaluation_cases"] = 3
    with pytest.raises(InputRejected) as caught:
        accept(raw)
    (issue,) = caught.value.issues
    assert (issue.code, issue.field) == ("budget.below_required_coverage", "budget.max_evaluation_cases")
    assert issue.message == (
        "The budget allows 3 evaluation cases, but the smallest study this evaluator accepts needs 4: "
        "the control and one design in each of at least 2 scenarios. Raise budget.max_evaluation_cases."
    )

    raw["budget"]["max_evaluation_cases"] = 4
    assert accept(raw).budget.max_evaluation_cases == 4


def test_personalized_mode_requires_a_hearing_profile():
    raw = make_request()
    del raw["hearing_profile"]
    assert reject(raw) == ["hearing.missing_profile"]


def test_personalized_mode_never_switches_to_demo_data():
    raw = make_request()
    del raw["hearing_profile"]
    raw["demo_profile_id"] = "demo_sloping_high_frequency"
    assert set(reject(raw)) == {"demo.not_selected", "hearing.missing_profile"}

    synthetic = make_request()
    synthetic["hearing_profile"]["source"] = "synthetic_demo"
    assert reject(synthetic) == ["hearing.synthetic_in_personalized"]


def test_demo_mode_is_explicit_and_stays_labeled():
    raw = make_request(mode="demo", demo_profile_id="demo_sloping_high_frequency")
    del raw["hearing_profile"]
    package = accept(raw)
    assert package.hearing_input.source == "synthetic_demo"
    assert package.hearing_input.profile_id == "demo_sloping_high_frequency"

    real_data_in_demo = make_request(mode="demo")
    assert reject(real_data_in_demo) == ["demo.source_mismatch"]


def test_free_text_and_notes_never_create_measurements():
    raw = make_request()
    raw["hearing_profile"]["measurements"] = []
    raw["hearing_profile"]["user_notes"] = "My right ear is much worse, around 60 dB at 2000 Hz."
    raw["needs_profile"]["free_text"] = "I think I have severe loss at 4000 Hz."
    assert reject(raw) == ["hearing.required_frequency_missing"] * 4


def test_needs_keep_the_users_words_next_to_the_normalized_form():
    package = accept(make_request())
    context = package.study_context
    assert not context.is_default
    assert context.needs.activities == ("sports", "busy restaurants")
    assert context.normalized_needs.activities == ("sports", "busy_restaurants")
    assert context.needs.free_text == "I want to hear people during activities."


def test_skipping_needs_uses_a_named_default_context_and_keeps_the_results():
    package = accept(make_request(needs=False))
    assert package.study_context.is_default
    assert package.study_context.name == DEFAULT_CONTEXT_NAME
    assert len(package.hearing_input.measurements) == 6


def test_a_start_must_be_user_originated():
    raw = make_request()
    raw["start"] = {"initiated_by": "agent"}
    with pytest.raises(InputRejected):
        parse_request(raw)
    del raw["start"]
    with pytest.raises(InputRejected):
        parse_request(raw)


def test_evaluation_mode_must_match_the_configured_evaluator():
    assert reject(make_request(evaluation_mode="real")) == ["evaluation.mode_mismatch"]
