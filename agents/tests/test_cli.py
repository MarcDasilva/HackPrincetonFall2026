"""The command line: exit codes, input errors first, replays labeled as replays."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import Harness, make_request

from horn_study import cli
from horn_study.workflow import run_study

EXAMPLES = Path(__file__).parent.parent / "examples" / "requests"


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch, tmp_path):
    for variable in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_FEDERATION_RULE_ID",
        "HORN_STUDY_MODEL",
        "HORN_STUDY_REAL_EVALUATOR",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli, "load_dotenv", lambda *args, **kwargs: False)


def write(tmp_path: Path, request: dict) -> str:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    return str(path)


@pytest.mark.parametrize("name", ["dev_with_needs.json", "dev_without_needs.json", "demo_profile.json"])
def test_example_requests_are_accepted(name, capsys):
    assert cli.main(["validate", str(EXAMPLES / name)]) == cli.EXIT_COMPLETED
    assert json.loads(capsys.readouterr().out)["accepted"] is True


def test_missing_results_example_is_rejected_with_actionable_errors(capsys):
    assert cli.main(["validate", str(EXAMPLES / "dev_missing_results.json")]) == cli.EXIT_INPUT_REJECTED
    captured = capsys.readouterr()
    issues = json.loads(captured.out)["issues"]
    assert [issue["code"] for issue in issues] == [
        "hearing.required_frequency_missing",
        "hearing.required_frequency_unusable",
    ]
    assert "2000 Hz" in captured.err
    assert "It was not replaced with a number." in captured.err


def test_input_errors_are_reported_before_any_model_is_needed(tmp_path, capsys):
    request = make_request()
    request["hearing_profile"]["measurements"] = []
    code = cli.main(["run", write(tmp_path, request), "--studies-dir", str(tmp_path / "studies")])
    assert code == cli.EXIT_INPUT_REJECTED
    assert not (tmp_path / "studies").exists()


def test_a_missing_model_key_is_a_clear_configuration_error(tmp_path, capsys):
    code = cli.main(["run", write(tmp_path, make_request()), "--studies-dir", str(tmp_path / "studies")])
    assert code == cli.EXIT_CONFIGURATION
    assert "Set ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "studies").exists()


def test_real_evaluation_is_never_silently_replaced_by_the_fixture(tmp_path, capsys):
    request = make_request(evaluation_mode="real")
    assert cli.main(["validate", write(tmp_path, request)]) == cli.EXIT_CONFIGURATION
    assert "No real evaluator is configured" in capsys.readouterr().err


def test_capabilities_are_printed_for_the_frontend(capsys):
    assert cli.main(["capabilities"]) == cli.EXIT_COMPLETED
    capabilities = json.loads(capsys.readouterr().out)
    assert capabilities["kind"] == "development_fixture"
    assert capabilities["hearing_input"]["required_frequencies_hz"] == [500.0, 1000.0, 2000.0, 4000.0]


async def test_replay_reemits_recorded_events_labeled_as_a_replay(tmp_path, capsys):
    harness = Harness(tmp_path)
    outcome = await run_study(make_request(), harness.deps)
    calls = len(harness.evaluator.calls)

    code = await cli._replay(
        cli.build_parser().parse_args(
            ["replay", outcome.study_id, "--studies-dir", str(tmp_path), "--speed", "0", "--json"]
        )
    )
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == cli.EXIT_COMPLETED
    assert [line["sequence"] for line in lines] == [e.sequence for e in outcome.events.history]
    assert all(line["replay"] is True for line in lines)
    assert len(harness.evaluator.calls) == calls


async def test_follow_up_command_builds_a_request_and_runs_nothing(tmp_path, capsys):
    harness = Harness(tmp_path)
    parent = await run_study(make_request(), harness.deps)
    capsys.readouterr()

    args = ["follow-up", parent.study_id, "FU1", "--study-id", "next_001", "--studies-dir", str(tmp_path)]
    assert cli.cmd_follow_up(cli.build_parser().parse_args(args)) == cli.EXIT_COMPLETED
    request = json.loads(capsys.readouterr().out)
    assert request["study_id"] == "next_001"
    assert request["parent_study_id"] == parent.study_id
    assert request["start"]["follow_up_proposal_id"] == "FU1"
    assert sorted(p.name for p in tmp_path.iterdir() if not p.name.startswith(".")) == [parent.study_id]
    assert len(harness.evaluator.calls) == 12

    missing = ["follow-up", parent.study_id, "FU7", "--study-id", "x", "--studies-dir", str(tmp_path)]
    assert cli.cmd_follow_up(cli.build_parser().parse_args(missing)) == cli.EXIT_INPUT_REJECTED
