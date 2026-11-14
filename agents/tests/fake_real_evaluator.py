"""A stand-in for the numerical owner's module, written the way it would be.

It exposes the two contract functions and takes and returns plain dicts, to
prove the evaluator seam works for code that lives in another package.
It borrows the fixture's capability declaration only to keep this file short.
"""

from __future__ import annotations

from typing import Any

from horn_study.evaluator_adapter import DevelopmentFixtureEvaluator

CALLS: list[dict[str, Any]] = []
VERSION = "real-test-1.0"


def get_evaluator_capabilities() -> dict[str, Any]:
    capabilities = DevelopmentFixtureEvaluator().get_evaluator_capabilities().model_dump(mode="json")
    capabilities.update(
        evaluator_name="team-acoustic-evaluator",
        evaluator_version=VERSION,
        kind="real",
        solver_build="abc123",
    )
    return capabilities


def evaluate_experiment(spec: dict[str, Any]) -> dict[str, Any]:
    CALLS.append(spec)
    is_design = spec["candidate_kind"] == "design"
    return {
        "candidate_id": spec["candidate_id"],
        "experiment_id": spec["experiment_id"],
        "spec_hash": spec["spec_hash"],
        "status": "completed",
        "parameters": spec["parameters"],
        "evaluation_config": {"scenario_id": spec["scenario_id"], "calibration_ref": spec["calibration_ref"]},
        "metrics": [
            {
                "name": "fixture_audible_speech_fraction",
                "value": 0.5 + (spec["parameters"]["length_mm"] / 1000 if is_design else 0.0),
                "unit": "fraction",
            },
            {
                "name": "fixture_device_length_mm",
                "value": spec["parameters"].get("length_mm", 0.0),
                "unit": "mm",
            },
        ],
        "assets": [{"kind": "response_curve", "ref": f"runs/{spec['experiment_id']}/response.npy"}],
        "evaluator_version": VERSION,
        "seed": spec["seed"],
        "runtime_seconds": 0.01,
        "provenance": {
            "kind": "real",
            "evaluator_name": "team-acoustic-evaluator",
            "evaluator_version": VERSION,
        },
        "solver_iterations": 42,
    }
