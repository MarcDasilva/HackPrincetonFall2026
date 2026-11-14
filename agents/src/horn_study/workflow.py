"""The bounded study workflow.

    create study -> the orchestrator runs it -> the workflow makes sure it finished

One Deep Agent, the study orchestrator, runs the study: it assigns the investigators, designs
the plan, and asks for the experiments and the report (see orchestrator.py). Every phase is a
tool that code gates, and the study moves forward only: once a plan is submitted research is
closed, and once it is frozen nothing can be planned again. So results can never start more
experiments. A new study needs a new user request.

The second step is the guarantee. If the orchestrator stops with a frozen plan whose cases or
report are still owed, the workflow finishes them, and if no plan was frozen the study fails.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableLambda
from langchain_core.tracers.langchain import wait_for_all_tracers
from langchain_core.utils.uuid import uuid7
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langsmith import utils as langsmith_utils

from horn_study.contracts import (
    SCHEMA_VERSION,
    EvaluatorCapabilities,
    ExperimentSpec,
    InputIssue,
    StartingPackage,
    StudyPlan,
    StudyReport,
    StudyRequest,
    StudyState,
    allowed_transitions,
)
from horn_study.evaluator_adapter import FIXTURE_NOTICE, BuildabilityCheck, Evaluator
from horn_study.events import ARTIFACT_NAMES, ArtifactStore, EventBus, EventListener, TraceRef
from horn_study.followup import FollowUpError, load_prior_study
from horn_study.intake import InputRejected, parse_request, validate_request
from horn_study.orchestrator import (
    ORCHESTRATOR_NAME,
    Progress,
    StudyControl,
    StudyFailed,
    run_orchestrator,
)
from horn_study.research import INVESTIGATORS
from horn_study.runner import EvaluateFn, EvaluationCache
from horn_study.sources import Reader, Search

RESEARCH_NODES = tuple(spec.name for spec in INVESTIGATORS)
NODE_ORCHESTRATE = "orchestrate_study"
NODE_COMPLETE = "complete_study"


class IllegalTransition(Exception):
    pass


class StudyStateMachine:
    """The explicit lifecycle. Moves are forward-only or to a terminal state."""

    def __init__(self, events: EventBus) -> None:
        self.state = StudyState.CREATED
        self._events = events

    def transition(self, target: StudyState) -> None:
        if target not in allowed_transitions(self.state):
            raise IllegalTransition(f"A study cannot move from {self.state} to {target}.")
        previous, self.state = self.state, target
        self._events.phase = target
        self._events.emit(
            "study.state_changed",
            f"{previous} -> {target}",
            component="workflow",
            data={"from": previous.value, "to": target.value},
        )


@dataclass
class StudyDependencies:
    evaluator: Evaluator
    research_model: BaseChatModel
    coordinator_model: BaseChatModel
    interpreter_model: BaseChatModel
    search: Search
    reader: Reader
    studies_root: Path
    listeners: tuple[EventListener, ...] = ()
    use_cache: bool = True
    callbacks: list[Any] = field(default_factory=list)


@dataclass
class StudyOutcome:
    study_id: str
    state: StudyState
    directory: Path
    report: StudyReport | None = None
    failure: dict[str, Any] | None = None
    events: EventBus | None = None


class GraphState(TypedDict, total=False):
    finished: bool


def build_graph(
    *,
    package: StartingPackage,
    research_model: BaseChatModel,
    coordinator_model: BaseChatModel,
    interpreter_model: BaseChatModel,
    evaluate: EvaluateFn,
    check_buildable: BuildabilityCheck | None,
    search: Search,
    reader: Reader,
    cache: EvaluationCache,
    events: EventBus,
    store: ArtifactStore,
    machine: StudyStateMachine,
    progress: Progress,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Wire the study: the orchestrator, then the check that it finished.

    The orchestrator never holds `evaluate` or a model for another role. They sit behind
    StudyControl's gates, which decide whether each phase may run.
    """
    control = StudyControl(
        package=package,
        research_model=research_model,
        interpreter_model=interpreter_model,
        evaluate=evaluate,
        check_buildable=check_buildable,
        unbuildable=unbuildable_candidates,
        search=search,
        reader=reader,
        cache=cache,
        events=events,
        store=store,
        state=lambda: machine.state,
        transition=machine.transition,
        progress=progress,
    )

    async def orchestrate_study(state: GraphState) -> dict[str, Any]:
        await run_orchestrator(coordinator_model, control)
        return {}

    async def complete_study(state: GraphState) -> dict[str, Any]:
        await control.complete()
        return {"finished": True}

    builder: StateGraph[GraphState, Any, Any, Any] = StateGraph(GraphState)
    builder.add_node(NODE_ORCHESTRATE, orchestrate_study)
    builder.add_node(NODE_COMPLETE, complete_study)
    builder.add_edge(START, NODE_ORCHESTRATE)
    builder.add_edge(NODE_ORCHESTRATE, NODE_COMPLETE)
    builder.add_edge(NODE_COMPLETE, END)
    return builder.compile(name="study")


async def unbuildable_candidates(
    plan: StudyPlan, check_buildable: BuildabilityCheck, max_parallel: int
) -> list[str]:
    """Ask the evaluator to test-build each design in a draft plan. Returns one error per design
    that cannot be built, worded so the orchestrator can change it. Nothing is scored here.

    A check that itself breaks is not held against the design: the case will report its own
    failure when it runs.
    """
    gate = asyncio.Semaphore(max_parallel)
    call = RunnableLambda(check_buildable, name="check_buildable")

    async def check(candidate_id: str, spec: ExperimentSpec) -> str | None:
        async with gate:
            try:
                problem = await call.ainvoke(
                    spec,
                    config={
                        "run_name": "check_buildable",
                        "tags": ["plan_validation"],
                        "metadata": {
                            "study_id": plan.study_id,
                            "component": "plan_validation",
                            "candidate_id": candidate_id,
                        },
                    },
                )
            except Exception:
                return None
        if problem is None:
            return None
        return f"candidate '{candidate_id}' cannot be built ({problem.code}): {problem.message}"[:900]

    first_case: dict[str, ExperimentSpec] = {}
    for spec in plan.experiments:
        if spec.candidate_kind == "design":
            first_case.setdefault(spec.candidate_id, spec)
    found = await asyncio.gather(*(check(cid, spec) for cid, spec in first_case.items()))
    return [message for message in found if message]


def results_document(
    *,
    request: StudyRequest,
    package: StartingPackage,
    state: StudyState,
    progress: Progress,
    trace: TraceRef,
    failure: dict[str, Any] | None,
) -> dict[str, Any]:
    """The frontend-ready record of a study (results.json)."""
    capabilities = package.capabilities
    plan, report = progress.plan, progress.report
    records = {record.experiment_id: record for record in progress.records}
    experiments = []
    for spec in plan.experiments if plan else ():
        record = records.get(spec.experiment_id)
        result = record.result if record else None
        experiments.append(
            {
                "experiment_id": spec.experiment_id,
                "candidate_id": spec.candidate_id,
                "scenario_id": spec.scenario_id,
                "canal_config_id": spec.canal_config_id,
                "seed": spec.seed,
                "spec_hash": spec.spec_hash(),
                "outcome": record.outcome if record else "not_run",
                "cache_hit": record.cache_hit if record else False,
                "attempts": len(record.attempts) if record else 0,
                "issues": list(record.issues) if record else [],
                "metrics": [m.model_dump(mode="json") for m in result.metrics] if result else [],
                "assets": [a.model_dump(mode="json") for a in result.assets] if result else [],
                "evaluator_version": result.evaluator_version if result else None,
                "runtime_seconds": result.runtime_seconds if result else None,
            }
        )
    selected_id = report.selected_candidate_id if report else None
    selected = plan.candidate(selected_id) if plan and selected_id else None
    is_fixture = capabilities.kind == "development_fixture"
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": request.study_id,
        "parent_study_id": request.parent_study_id,
        "state": state.value,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": request.mode,
        "evaluation_mode": request.evaluation_mode,
        "result_label": (
            "Development fixture output. Not simulation results."
            if is_fixture
            else "Simulation results for a modeled hearing profile under declared assumptions."
        ),
        "fixture_notice": FIXTURE_NOTICE if is_fixture else None,
        "development_fixture_label": request.development_fixture_label,
        "start": request.start.model_dump(mode="json"),
        "failure": failure,
        "hearing_input": package.hearing_input.model_dump(mode="json"),
        "study_context": package.study_context.model_dump(mode="json"),
        "anatomy": package.anatomy.model_dump(mode="json"),
        "prior_study": package.prior_study.model_dump(mode="json") if package.prior_study else None,
        "evaluator": {
            "name": capabilities.evaluator_name,
            "version": capabilities.evaluator_version,
            "kind": capabilities.kind,
            "metrics": [m.model_dump(mode="json") for m in capabilities.metrics],
            "scenarios": [s.model_dump(mode="json") for s in capabilities.scenarios],
            "calibration": capabilities.calibration.model_dump(mode="json"),
        },
        "research": progress.research.model_dump(mode="json") if progress.research else None,
        "orchestrator": {
            "agent": ORCHESTRATOR_NAME,
            "evidence_scorecard": progress.scorecard,
            "notes": dict(progress.notes),
            "notes_label": "Working notes written by the orchestrator model. They are not results.",
            "phases_completed_by_workflow": list(progress.phases_completed_by_workflow),
        },
        "plan": plan.model_dump(mode="json", exclude={"experiments"}) if plan else None,
        "experiments": experiments,
        "report": report.model_dump(mode="json") if report else None,
        "selected_candidate_id": selected_id,
        "selected_candidate": selected.model_dump(mode="json") if selected else None,
        "trace": trace.model_dump(mode="json"),
        "artifacts": list(ARTIFACT_NAMES),
    }


async def run_study(raw_request: Mapping[str, Any], deps: StudyDependencies) -> StudyOutcome:
    """Run one user-requested study from request to terminal state.

    Raises InputRejected, before anything is saved or evaluated, when the
    request cannot be used. Otherwise always returns a terminal outcome.
    """
    request = parse_request(raw_request)
    capabilities = deps.evaluator.get_evaluator_capabilities()

    prior = None
    if request.parent_study_id:
        try:
            prior = load_prior_study(
                deps.studies_root, request.parent_study_id, request.start.follow_up_proposal_id
            )
        except FollowUpError as exc:
            raise InputRejected(
                [InputIssue(code="follow_up.parent_unavailable", field="parent_study_id", message=str(exc))]
            ) from exc
    package = validate_request(request, capabilities, prior)

    store = ArtifactStore(deps.studies_root, request.study_id)
    store.create()
    run_id = uuid7()
    tracing = bool(langsmith_utils.tracing_is_enabled())
    trace = TraceRef(
        run_id=str(run_id),
        project=langsmith_utils.get_tracer_project() if tracing else None,
        tracing_enabled=tracing,
    )
    events = EventBus(request.study_id, store, deps.listeners, trace)
    machine = StudyStateMachine(events)
    progress = Progress()

    store.write_json(
        "request.json",
        {
            "original": dict(raw_request),
            "normalized": request.model_dump(mode="json"),
            "hearing_input": package.hearing_input.model_dump(mode="json"),
            "study_context": package.study_context.model_dump(mode="json"),
        },
    )
    store.write_json("capabilities.json", capabilities)
    events.emit(
        "study.started",
        (
            f"Study started for the {package.hearing_input.target_ear} ear "
            f"({package.hearing_input.source.replace('_', ' ')}), context '{package.study_context.name}'."
        ),
        component="workflow",
        artifacts=["request.json", "capabilities.json"],
        data={
            "mode": request.mode,
            "evaluation_mode": request.evaluation_mode,
            "evaluator_version": capabilities.evaluator_version,
            "parent_study_id": request.parent_study_id,
            "start_action": request.start.action,
        },
    )

    snapshot_cache = EvaluationCache(
        deps.studies_root / ".evaluation_cache" if deps.use_cache else None,
        _snapshot(capabilities),
    )
    graph = build_graph(
        package=package,
        research_model=deps.research_model,
        coordinator_model=deps.coordinator_model,
        interpreter_model=deps.interpreter_model,
        evaluate=deps.evaluator.evaluate_experiment,
        check_buildable=getattr(deps.evaluator, "check_buildable", None),
        search=deps.search,
        reader=deps.reader,
        cache=snapshot_cache,
        events=events,
        store=store,
        machine=machine,
        progress=progress,
    )

    failure: dict[str, Any] | None = None

    def finish(state: StudyState) -> StudyOutcome:
        if machine.state is not state:
            machine.transition(state)
        store.write_json(
            "results.json",
            results_document(
                request=request, package=package, state=state, progress=progress, trace=trace, failure=failure
            ),
        )
        return StudyOutcome(
            study_id=request.study_id,
            state=state,
            directory=store.directory,
            report=progress.report,
            failure=failure,
            events=events,
        )

    try:
        machine.transition(StudyState.RESEARCHING)
        async with asyncio.timeout(package.budget.max_run_seconds):
            await graph.ainvoke(
                {},
                config={
                    "run_name": f"study {request.study_id}",
                    "run_id": run_id,
                    "recursion_limit": 40,
                    "callbacks": list(deps.callbacks),
                    "tags": ["horn-study", capabilities.kind],
                    "metadata": {
                        "study_id": request.study_id,
                        "parent_study_id": request.parent_study_id,
                        "mode": request.mode,
                        "evaluation_mode": request.evaluation_mode,
                        "evaluator_version": capabilities.evaluator_version,
                    },
                },
            )
        outcome = finish(StudyState.COMPLETED)
        events.emit(
            "study.completed",
            "Study completed. Follow-up proposals stay inactive until a user starts a new study.",
            component="workflow",
            artifacts=list(ARTIFACT_NAMES),
            data={"selected_candidate_id": outcome.report.selected_candidate_id if outcome.report else None},
        )
        return outcome
    except asyncio.CancelledError:
        failure = {"kind": "cancelled", "message": "The study was cancelled.", "details": []}
        outcome = finish(StudyState.CANCELLED)
        events.emit("study.cancelled", "Study cancelled.", component="workflow", artifacts=["results.json"])
        raise
    except Exception as exc:
        if isinstance(exc, StudyFailed):
            failure = {"kind": exc.kind, "message": str(exc), "details": exc.details}
        elif isinstance(exc, TimeoutError):
            failure = {
                "kind": "timeout",
                "message": f"The study exceeded its {package.budget.max_run_seconds:g} second limit.",
                "details": [],
            }
        else:
            failure = {"kind": "error", "message": f"{type(exc).__name__}: {exc}"[:600], "details": []}
        outcome = finish(StudyState.FAILED)
        events.emit(
            "study.failed",
            failure["message"][:300],
            component="workflow",
            artifacts=["results.json"],
            data=failure,
        )
        return outcome
    finally:
        if tracing:
            await asyncio.to_thread(wait_for_all_tracers)


def _snapshot(capabilities: EvaluatorCapabilities) -> Any:
    from horn_study.contracts import CapabilitySnapshot

    return CapabilitySnapshot(
        evaluator_name=capabilities.evaluator_name,
        evaluator_version=capabilities.evaluator_version,
        kind=capabilities.kind,
        capabilities_hash=capabilities.snapshot_hash(),
    )
