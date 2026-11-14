"""Execution: only the frozen spec, bounded identical retries, honest failures."""

from __future__ import annotations

from helpers import make_request, valid_draft

from horn_study.contracts import CapabilitySnapshot, ErrorInfo
from horn_study.evaluator_adapter import DevelopmentFixtureEvaluator, TransientEvaluatorError
from horn_study.events import EventBus
from horn_study.intake import parse_request, validate_request
from horn_study.planner import PlanDraft, build_plan, freeze_plan
from horn_study.runner import EvaluationCache, check_result, execute_experiment

FIXTURE = DevelopmentFixtureEvaluator()
CAPS = FIXTURE.get_evaluator_capabilities()
SNAPSHOT = CapabilitySnapshot(
    evaluator_name=CAPS.evaluator_name,
    evaluator_version=CAPS.evaluator_version,
    kind=CAPS.kind,
    capabilities_hash=CAPS.snapshot_hash(),
)


def frozen_plan():
    package = validate_request(parse_request(make_request()), CAPS)
    plan, errors = build_plan(
        PlanDraft.model_validate(valid_draft()), package, frozenset({"design-F1", "hearing-F1"}), 1
    )
    assert not errors
    assert plan is not None
    return freeze_plan(plan)


SPEC = frozen_plan().experiments[4]


async def run(evaluate, max_attempts=2, cache=None):
    events = EventBus("s")
    record = await execute_experiment(
        SPEC,
        evaluate=evaluate,
        capabilities=CAPS,
        max_attempts=max_attempts,
        cache=cache or EvaluationCache(None, SNAPSHOT),
        events=events,
        plan_hash="h",
    )
    return record, events


async def test_completed_result_is_recorded_exactly_as_returned():
    expected = FIXTURE.evaluate_experiment(SPEC)
    record, events = await run(FIXTURE.evaluate_experiment)
    assert record.outcome == "completed"
    assert record.result.metrics == expected.metrics
    assert record.result.spec_hash == SPEC.spec_hash()
    assert record.result.provenance.kind == "development_fixture"
    assert [e.type for e in events.history] == ["experiment.started", "experiment.completed"]


async def test_transient_failure_retries_the_identical_spec_within_the_limit():
    seen = []

    def flaky(spec):
        seen.append(spec)
        if len(seen) == 1:
            raise TransientEvaluatorError("worker restarted")
        return FIXTURE.evaluate_experiment(spec)

    record, events = await run(flaky, max_attempts=3)
    assert record.outcome == "completed"
    assert [a.outcome for a in record.attempts] == ["transient_error", "completed"]
    assert all(spec is SPEC for spec in seen)
    assert [e.type for e in events.history] == [
        "experiment.started",
        "experiment.retried",
        "experiment.completed",
    ]


async def test_retries_are_bounded_and_a_failure_never_becomes_a_score():
    calls = []

    def always_down(spec):
        calls.append(spec.experiment_id)
        raise TransientEvaluatorError("still down")

    record, events = await run(always_down, max_attempts=2)
    assert len(calls) == 2
    assert record.outcome == "failed"
    assert record.result is None
    assert events.history[-1].type == "experiment.failed"


async def test_non_transient_errors_are_not_retried():
    calls = []

    def crash(spec):
        calls.append(1)
        raise RuntimeError("solver diverged")

    record, _ = await run(crash, max_attempts=3)
    assert len(calls) == 1
    assert record.outcome == "failed"
    assert "solver diverged" in record.issues[0]

    def reported_failure(spec):
        calls.append(1)
        good = FIXTURE.evaluate_experiment(spec)
        return good.model_copy(
            update={
                "status": "failed",
                "metrics": (),
                "error": ErrorInfo(code="diverged", message="No convergence."),
            }
        )

    record, _ = await run(reported_failure, max_attempts=3)
    assert len(calls) == 2
    assert record.outcome == "failed"
    assert record.result.status == "failed"


async def test_results_that_do_not_answer_the_spec_are_invalid():
    def wrong_case(spec):
        return FIXTURE.evaluate_experiment(spec).model_copy(update={"spec_hash": "0" * 64})

    record, _ = await run(wrong_case)
    assert record.outcome == "invalid"
    assert "spec_hash does not match" in record.issues[0]

    good = FIXTURE.evaluate_experiment(SPEC)
    first = good.metrics[0]
    not_a_number = good.model_copy(update={"metrics": (first.model_copy(update={"value": float("nan")}),)})
    assert check_result(SPEC, not_a_number, CAPS) == [
        "Metric 'fixture_audible_speech_fraction' is not a finite number."
    ]
    rescaled = good.model_copy(update={"metrics": (first.model_copy(update={"unit": "percent"}),)})
    assert "declared 'fraction'" in check_result(SPEC, rescaled, CAPS)[0]
    other_version = good.model_copy(update={"evaluator_version": "fixture-9"})
    assert "frozen against" in check_result(SPEC, other_version, CAPS)[0]


async def test_identical_completed_evaluations_are_reused(tmp_path):
    cache = EvaluationCache(tmp_path, SNAPSHOT)
    calls = []

    def counted(spec):
        calls.append(1)
        return FIXTURE.evaluate_experiment(spec)

    first, _ = await run(counted, cache=cache)
    second, events = await run(counted, cache=cache)
    assert len(calls) == 1
    assert second.cache_hit
    assert not first.cache_hit
    assert second.result.metrics == first.result.metrics
    assert events.history[-1].data["cache_hit"] is True


def test_fixture_results_are_labeled_and_deterministic():
    one, two = FIXTURE.evaluate_experiment(SPEC), FIXTURE.evaluate_experiment(SPEC)
    assert one.metrics == two.metrics
    assert one.provenance.kind == "development_fixture"
    assert "DEVELOPMENT FIXTURE" in one.provenance.notes
    assert all(m.name.startswith("fixture_") for m in one.metrics)
    outside = SPEC.model_copy(update={"parameters": {**SPEC.parameters, "length_mm": 900.0}})
    assert FIXTURE.evaluate_experiment(outside).status == "unsupported"
