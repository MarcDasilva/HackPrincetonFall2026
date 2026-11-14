"""The evaluator seam: real code plugs in by path and its data is preserved."""

from __future__ import annotations

import json

import fake_real_evaluator
import pytest
from helpers import Harness, make_request

from horn_study.contracts import StudyState
from horn_study.evaluator_adapter import (
    REAL_EVALUATOR_ENV,
    DevelopmentFixtureEvaluator,
    EvaluatorNotConfigured,
    evaluator_for,
    load_evaluator,
)
from horn_study.workflow import run_study


def test_modes_resolve_explicitly_and_real_never_falls_back():
    assert isinstance(evaluator_for("development_fixture", env={}), DevelopmentFixtureEvaluator)
    with pytest.raises(EvaluatorNotConfigured, match="No real evaluator is configured"):
        evaluator_for("real", env={})
    with pytest.raises(EvaluatorNotConfigured, match="Could not load"):
        evaluator_for("real", env={REAL_EVALUATOR_ENV: "no_such_module:thing"})
    with pytest.raises(EvaluatorNotConfigured, match="does not provide"):
        load_evaluator("json")


async def test_a_real_evaluator_module_runs_a_study_and_keeps_its_own_fields(tmp_path):
    fake_real_evaluator.CALLS.clear()
    evaluator = evaluator_for("real", env={REAL_EVALUATOR_ENV: "fake_real_evaluator"})
    harness = Harness(tmp_path, evaluator=evaluator)
    outcome = await run_study(make_request(evaluation_mode="real"), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert len(fake_real_evaluator.CALLS) == 12
    sent = fake_real_evaluator.CALLS[0]
    assert sent["hearing_input"]["target_ear"] == "right"
    assert [m["threshold_db_hl"] for m in sent["hearing_input"]["measurements"]] == [15, 20, 30, 45, 55, 50]
    assert sent["calibration_ref"] == "fixture-cal-v1"

    report = outcome.report
    assert report is not None
    assert report.result_kind == "real"
    assert report.result_label.startswith("Simulation results for a modeled hearing profile")
    assert report.selected_candidate_id == "len90"
    assert not any("DEVELOPMENT FIXTURE" in text for text in report.limitations)

    saved = json.loads((outcome.directory / "experiment_results.json").read_text())
    first = saved["records"][0]["result"]
    assert first["solver_iterations"] == 42
    assert first["assets"][0]["ref"].endswith("/response.npy")
    capabilities = json.loads((outcome.directory / "capabilities.json").read_text())
    assert capabilities["solver_build"] == "abc123"
    assert json.loads((outcome.directory / "results.json").read_text())["fixture_notice"] is None
