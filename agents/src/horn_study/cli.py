"""Command line entry point.

horn-study run request.json          run one study
horn-study validate request.json     check inputs without running anything
horn-study capabilities              print what the evaluator supports
horn-study follow-up PARENT FU1 ...  build (and optionally run) a user-requested follow-up
horn-study replay STUDY_ID           re-emit a recorded study's events, labeled as a replay
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

from horn_study import __version__
from horn_study.contracts import InputIssue, StartingPackage
from horn_study.evaluator_adapter import Evaluator, EvaluatorNotConfigured, evaluator_for
from horn_study.events import ArtifactStore, StudyEvent, StudyExists, read_events
from horn_study.followup import FollowUpError, follow_up_request, load_prior_study
from horn_study.intake import InputRejected, parse_request, validate_request

EXIT_COMPLETED = 0
EXIT_FAILED = 1
EXIT_INPUT_REJECTED = 2
EXIT_CONFIGURATION = 3

STUDIES_DIR_ENV = "HORN_STUDY_DIR"


def _studies_dir(args: argparse.Namespace) -> Path:
    return Path(args.studies_dir or os.environ.get(STUDIES_DIR_ENV) or "studies")


def _load_json(path: str) -> dict[str, Any]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("The request file must contain a JSON object.")
    return value


def format_event(event: StudyEvent) -> str:
    stamp = event.timestamp.astimezone().strftime("%H:%M:%S")
    prefix = "REPLAY " if event.replay else ""
    return f"{prefix}{stamp} {event.sequence:>3} {event.phase.value:<12} {event.type:<26} {event.component}: {event.summary}"


def _print_event(as_json: bool):
    def listener(event: StudyEvent) -> None:
        print(event.model_dump_json() if as_json else format_event(event), flush=True)

    return listener


def _print_issues(error: InputRejected) -> None:
    print("The request cannot start a study:", file=sys.stderr)
    for issue in error.issues:
        print(f"  - [{issue.code}] {issue.field}: {issue.message}", file=sys.stderr)
    print(json.dumps({"accepted": False, "issues": [i.model_dump() for i in error.issues]}, indent=2))


def _configuration_error(message: str) -> int:
    print(f"Configuration problem: {message}", file=sys.stderr)
    return EXIT_CONFIGURATION


def _preflight(raw: dict[str, Any], args: argparse.Namespace) -> tuple[Evaluator, StartingPackage]:
    """Check everything that can be checked without a model: inputs, evaluator, parent study."""
    request = parse_request(raw)
    evaluator = evaluator_for(request.evaluation_mode)
    prior = None
    if request.parent_study_id:
        try:
            prior = load_prior_study(
                _studies_dir(args), request.parent_study_id, request.start.follow_up_proposal_id
            )
        except FollowUpError as error:
            raise InputRejected(
                [InputIssue(code="follow_up.parent_unavailable", field="parent_study_id", message=str(error))]
            ) from error
    return evaluator, validate_request(request, evaluator.get_evaluator_capabilities(), prior)


async def _run(raw: dict[str, Any], args: argparse.Namespace) -> int:
    from horn_study.llm import ModelNotConfigured, Role, load_model, model_name
    from horn_study.sources import HttpReader, default_search, make_http_client
    from horn_study.workflow import StudyDependencies, run_study

    roles: tuple[Role, ...] = ("research", "coordinator", "interpreter")
    try:
        evaluator, _ = _preflight(raw, args)
    except InputRejected as error:
        _print_issues(error)
        return EXIT_INPUT_REJECTED
    except EvaluatorNotConfigured as error:
        return _configuration_error(str(error))

    try:
        models = {role: load_model(role) for role in roles}
    except ModelNotConfigured as error:
        return _configuration_error(str(error))
    except Exception as error:
        return _configuration_error(
            f"could not create the chat model '{model_name('research')}' ({type(error).__name__}: {error})."
        )

    async with make_http_client() as client:
        deps = StudyDependencies(
            evaluator=evaluator,
            research_model=models["research"],
            coordinator_model=models["coordinator"],
            interpreter_model=models["interpreter"],
            search=default_search(client),
            reader=HttpReader(client),
            studies_root=_studies_dir(args),
            listeners=(_print_event(args.json),),
            use_cache=not args.no_cache,
        )
        try:
            outcome = await run_study(raw, deps)
        except InputRejected as error:
            _print_issues(error)
            return EXIT_INPUT_REJECTED
        except StudyExists as error:
            print(str(error), file=sys.stderr)
            return EXIT_INPUT_REJECTED

    if not args.json:
        print()
        print(f"Study {outcome.study_id}: {outcome.state.value}")
        print(f"Artifacts: {outcome.directory}")
        if outcome.report is not None:
            report = outcome.report
            print(f"Results: {report.result_label}")
            print(f"Selected candidate: {report.selected_candidate_id or 'none'}")
            print(f"  {report.selection.explanation}")
            for proposal in report.follow_up_proposals:
                print(f"Follow-up available ({proposal.proposal_id}, not started): {proposal.title}")
        if outcome.failure is not None:
            print(f"Failure ({outcome.failure['kind']}): {outcome.failure['message']}")
            for detail in outcome.failure.get("details", []):
                print(f"  - {detail}")
    return EXIT_COMPLETED if outcome.state.value == "COMPLETED" else EXIT_FAILED


def cmd_run(args: argparse.Namespace) -> int:
    return asyncio.run(_run(_load_json(args.request), args))


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        _, package = _preflight(_load_json(args.request), args)
    except InputRejected as error:
        _print_issues(error)
        return EXIT_INPUT_REJECTED
    except EvaluatorNotConfigured as error:
        return _configuration_error(str(error))
    print(
        json.dumps(
            {
                "accepted": True,
                "issues": [],
                "hearing_input": package.hearing_input.model_dump(mode="json"),
                "study_context": package.study_context.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    return EXIT_COMPLETED


def cmd_capabilities(args: argparse.Namespace) -> int:
    try:
        capabilities = evaluator_for(args.evaluation_mode).get_evaluator_capabilities()
    except EvaluatorNotConfigured as error:
        return _configuration_error(str(error))
    print(capabilities.model_dump_json(indent=2))
    return EXIT_COMPLETED


def cmd_follow_up(args: argparse.Namespace) -> int:
    needs = _load_json(args.needs) if args.needs else None
    try:
        request = follow_up_request(
            _studies_dir(args), args.parent_study_id, args.proposal_id, args.study_id, needs
        )
    except FollowUpError as error:
        print(str(error), file=sys.stderr)
        return EXIT_INPUT_REJECTED
    if args.out:
        Path(args.out).write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote the follow-up request to {args.out}. Nothing has run.", file=sys.stderr)
    if args.run:
        return asyncio.run(_run(request, args))
    if not args.out:
        print(json.dumps(request, indent=2))
    return EXIT_COMPLETED


async def _replay(args: argparse.Namespace) -> int:
    store = ArtifactStore(_studies_dir(args), args.study_id)
    events = read_events(store)
    if not events:
        print(f"No recorded events for study '{args.study_id}' in {store.root}.", file=sys.stderr)
        return EXIT_INPUT_REJECTED
    emit = _print_event(args.json)
    if not args.json:
        print(
            f"REPLAY of study {args.study_id}, recorded {events[0].timestamp.astimezone():%Y-%m-%d %H:%M}. "
            "Nothing is being researched or evaluated now."
        )
    previous = events[0].timestamp
    for event in events:
        gap = (event.timestamp - previous).total_seconds()
        previous = event.timestamp
        if args.speed > 0:
            await asyncio.sleep(min(gap / args.speed, 2.0))
        emit(event.model_copy(update={"replay": True}))
    return EXIT_COMPLETED


def cmd_replay(args: argparse.Namespace) -> int:
    return asyncio.run(_replay(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="horn-study",
        description="Research and experiment planning for the passive acoustic hearing device study.",
    )
    parser.add_argument("--version", action="version", version=f"horn-study {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--studies-dir",
        help=f"Where studies are saved (default: ${STUDIES_DIR_ENV} or ./studies).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", parents=[common], help="Run one study from a request file.")
    run.add_argument("request", help="Path to a study request JSON file, or - for stdin.")
    run.add_argument("--json", action="store_true", help="Print events as JSON lines.")
    run.add_argument("--no-cache", action="store_true", help="Do not reuse identical completed evaluations.")
    run.set_defaults(handler=cmd_run)

    validate = commands.add_parser("validate", parents=[common], help="Check a request without running it.")
    validate.add_argument("request", help="Path to a study request JSON file, or - for stdin.")
    validate.set_defaults(handler=cmd_validate)

    capabilities = commands.add_parser("capabilities", help="Print the evaluator capability contract.")
    capabilities.add_argument(
        "--evaluation-mode", choices=["development_fixture", "real"], default="development_fixture"
    )
    capabilities.set_defaults(handler=cmd_capabilities)

    follow_up = commands.add_parser(
        "follow-up",
        parents=[common],
        help="Build a new study request from a follow-up proposal the user selected.",
    )
    follow_up.add_argument("parent_study_id")
    follow_up.add_argument("proposal_id")
    follow_up.add_argument("--study-id", required=True, help="ID for the new study.")
    follow_up.add_argument("--needs", help="JSON file with a replacement needs_profile.")
    follow_up.add_argument("--out", help="Write the new request to this file.")
    follow_up.add_argument("--run", action="store_true", help="Start the new study now.")
    follow_up.add_argument("--json", action="store_true", help="Print events as JSON lines.")
    follow_up.add_argument("--no-cache", action="store_true")
    follow_up.set_defaults(handler=cmd_follow_up)

    replay = commands.add_parser("replay", parents=[common], help="Replay a recorded study's events.")
    replay.add_argument("study_id")
    replay.add_argument("--speed", type=float, default=4.0, help="Playback speed-up. 0 prints at once.")
    replay.add_argument("--json", action="store_true", help="Print events as JSON lines.")
    replay.set_defaults(handler=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(find_dotenv(usecwd=True))
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_FAILED
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
