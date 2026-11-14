"""Bounded execution of frozen experiment specs.

The runner sends each frozen spec to the evaluator and records what came back.
It may repeat the identical spec after a transient operational failure, up to
a fixed number of attempts. It never changes a spec, never adds one, and never
turns a failure into a number.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from horn_study.contracts import (
    AttemptOutcome,
    AttemptRecord,
    CapabilitySnapshot,
    EvaluatorCapabilities,
    ExperimentOutcome,
    ExperimentRecord,
    ExperimentResult,
    ExperimentSpec,
)
from horn_study.evaluator_adapter import TransientEvaluatorError
from horn_study.events import EventBus

EvaluateFn = Callable[[ExperimentSpec], ExperimentResult]


class EvaluationCache:
    """Reuses completed results for identical evaluations by the same evaluator version."""

    def __init__(self, root: Path | None, snapshot: CapabilitySnapshot) -> None:
        self._directory = (
            None
            if root is None
            else Path(root)
            / f"{snapshot.evaluator_name}-{snapshot.evaluator_version}-{snapshot.capabilities_hash[:12]}"
        )

    def _path(self, spec: ExperimentSpec) -> Path | None:
        return None if self._directory is None else self._directory / f"{spec.evaluation_key()}.json"

    def get(self, spec: ExperimentSpec) -> ExperimentResult | None:
        path = self._path(spec)
        if path is None or not path.exists():
            return None
        try:
            cached = ExperimentResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError, json.JSONDecodeError):
            return None
        if cached.status != "completed":
            return None
        # Same computation, this study's identifiers.
        return cached.model_copy(
            update={
                "experiment_id": spec.experiment_id,
                "candidate_id": spec.candidate_id,
                "spec_hash": spec.spec_hash(),
            }
        )

    def put(self, spec: ExperimentSpec, result: ExperimentResult) -> None:
        path = self._path(spec)
        if path is None or result.status != "completed":
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(result.model_dump_json())
        os.replace(temp_name, path)


def check_result(
    spec: ExperimentSpec, result: ExperimentResult, capabilities: EvaluatorCapabilities
) -> list[str]:
    """Return reasons a returned result cannot be trusted as the answer to `spec`."""
    issues: list[str] = []
    if result.experiment_id != spec.experiment_id:
        issues.append(f"Result is for experiment '{result.experiment_id}', not '{spec.experiment_id}'.")
    if result.candidate_id != spec.candidate_id:
        issues.append(f"Result is for candidate '{result.candidate_id}', not '{spec.candidate_id}'.")
    if result.spec_hash != spec.spec_hash():
        issues.append("Result spec_hash does not match the frozen specification.")
    if result.evaluator_version != capabilities.evaluator_version:
        issues.append(
            f"Result came from evaluator version '{result.evaluator_version}', but the plan was "
            f"frozen against '{capabilities.evaluator_version}'."
        )
    if result.provenance.kind != capabilities.kind:
        issues.append(
            f"Result provenance is '{result.provenance.kind}' but the evaluator declared '{capabilities.kind}'."
        )
    if result.status == "completed":
        if not result.metrics:
            issues.append("A completed result has no metrics.")
        seen: set[str] = set()
        for metric in result.metrics:
            declared = capabilities.metric(metric.name)
            if metric.name in seen:
                issues.append(f"Metric '{metric.name}' is reported more than once.")
            seen.add(metric.name)
            if not math.isfinite(metric.value):
                issues.append(f"Metric '{metric.name}' is not a finite number.")
            if declared is not None and declared.unit != metric.unit:
                issues.append(
                    f"Metric '{metric.name}' is in '{metric.unit}' but the evaluator declared '{declared.unit}'."
                )
    return issues


async def execute_experiment(
    spec: ExperimentSpec,
    *,
    evaluate: EvaluateFn,
    capabilities: EvaluatorCapabilities,
    max_attempts: int,
    cache: EvaluationCache,
    events: EventBus,
    plan_hash: str,
) -> ExperimentRecord:
    """Evaluate one frozen spec, with bounded identical retries."""
    spec_hash = spec.spec_hash()
    ids = {"experiment_ids": [spec.experiment_id], "candidate_ids": [spec.candidate_id]}
    events.emit(
        "experiment.started",
        f"Evaluating {spec.candidate_id} in {spec.scenario_id}.",
        component="evaluation",
        **ids,
        data={"spec_hash": spec_hash, "scenario_id": spec.scenario_id, "seed": spec.seed},
    )

    cached = cache.get(spec)
    if cached is not None and not check_result(spec, cached, capabilities):
        events.emit(
            "experiment.completed",
            f"{spec.candidate_id} in {spec.scenario_id}: reused an identical completed evaluation.",
            component="evaluation",
            **ids,
            data={"outcome": "completed", "cache_hit": True, "metrics": _metric_view(cached)},
        )
        return ExperimentRecord(
            experiment_id=spec.experiment_id,
            candidate_id=spec.candidate_id,
            spec_hash=spec_hash,
            outcome="completed",
            result=cached,
            cache_hit=True,
        )

    call = RunnableLambda(evaluate, name="evaluate_experiment")
    attempts: list[AttemptRecord] = []
    record: ExperimentRecord | None = None
    for attempt in range(1, max_attempts + 1):
        started = datetime.now(UTC)
        retryable = False
        outcome: AttemptOutcome
        result: ExperimentResult | None = None
        issues: list[str] = []
        error: str | None = None
        try:
            result = await call.ainvoke(
                spec,
                config={
                    "run_name": "evaluate_experiment",
                    "tags": ["evaluation"],
                    "metadata": {
                        "study_id": spec.study_id,
                        "component": "evaluation",
                        "experiment_id": spec.experiment_id,
                        "candidate_id": spec.candidate_id,
                        "spec_hash": spec_hash,
                        "plan_hash": plan_hash,
                        "attempt": attempt,
                        "evaluator_version": capabilities.evaluator_version,
                    },
                },
            )
        except TransientEvaluatorError as exc:
            outcome, error, retryable = "transient_error", f"{exc}"[:500], True
        except Exception as exc:  # an evaluator crash is a failed case, not a crashed study
            outcome, error = "error", f"{type(exc).__name__}: {exc}"[:500]
        else:
            if not isinstance(result, ExperimentResult):
                outcome, error, result = "invalid", "The evaluator did not return an ExperimentResult.", None
            else:
                issues = check_result(spec, result, capabilities)
                if issues:
                    outcome, error = "invalid", " ".join(issues)
                elif result.status == "failed":
                    outcome = "failed"
                    error = result.error.message if result.error else "The evaluator reported a failure."
                    retryable = bool(result.error and result.error.transient)
                else:
                    outcome = result.status
        attempts.append(
            AttemptRecord(
                attempt=attempt, started_at=started, ended_at=datetime.now(UTC), outcome=outcome, error=error
            )
        )
        if retryable and attempt < max_attempts:
            events.emit(
                "experiment.retried",
                f"{spec.experiment_id}: transient failure on attempt {attempt}; retrying the identical case.",
                component="evaluation",
                **ids,
                data={"attempt": attempt, "error": error},
            )
            continue
        final: ExperimentOutcome = "failed" if outcome in ("transient_error", "error", "failed") else outcome
        record = ExperimentRecord(
            experiment_id=spec.experiment_id,
            candidate_id=spec.candidate_id,
            spec_hash=spec_hash,
            outcome=final,
            result=result,
            attempts=tuple(attempts),
            issues=tuple(issues) if issues else ((error,) if error and final != "completed" else ()),
        )
        break
    assert record is not None

    if record.outcome == "completed" and record.result is not None:
        cache.put(spec, record.result)
        events.emit(
            "experiment.completed",
            f"{spec.candidate_id} in {spec.scenario_id}: completed.",
            component="evaluation",
            **ids,
            data={
                "outcome": "completed",
                "cache_hit": False,
                "attempts": len(attempts),
                "metrics": _metric_view(record.result),
                "assets": [a.model_dump(mode="json") for a in record.result.assets],
            },
        )
    else:
        events.emit(
            "experiment.failed",
            f"{spec.candidate_id} in {spec.scenario_id}: {record.outcome}. {'; '.join(record.issues)[:300]}",
            component="evaluation",
            **ids,
            data={"outcome": record.outcome, "attempts": len(attempts), "issues": list(record.issues)},
        )
    return record


def _metric_view(result: ExperimentResult) -> list[dict[str, object]]:
    return [{"name": m.name, "value": m.value, "unit": m.unit} for m in result.metrics]
