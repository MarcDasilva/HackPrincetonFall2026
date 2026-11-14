"""The bounded study workflow.

    create study -> three research branches in parallel -> synthesize evidence
    -> plan -> validate and freeze -> evaluate the fixed batch -> interpret -> done

The only cycle is between planning and validation, and it closes before the
plan is frozen. Nothing leads from evaluation or interpretation back to
planning, so results can never start more experiments. A new study needs a new
user request.
"""

from __future__ import annotations

import asyncio
import operator
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tracers.langchain import wait_for_all_tracers
from langchain_core.utils.uuid import uuid7
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langsmith import utils as langsmith_utils

from horn_study.contracts import (
    SCHEMA_VERSION,
    BranchResult,
    EvaluatorCapabilities,
    ExperimentRecord,
    ExperimentSpec,
    InputIssue,
    ResearchRecord,
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
from horn_study.planner import (
    PlanDraft,
    PlanningFailed,
    build_plan,
    freeze_plan,
    initial_messages,
    propose_plan,
    revision_request,
)
from horn_study.reporting import (
    build_report,
    hypothesis_data,
    interpretation_brief,
    need_outcomes,
    summarize_candidates,
    write_narrative,
)
from horn_study.research import INVESTIGATORS, InvestigatorSpec, ResearchLedger, run_investigator
from horn_study.runner import EvaluateFn, EvaluationCache, execute_experiment
from horn_study.sources import Reader, Search

RESEARCH_NODES = tuple(spec.name for spec in INVESTIGATORS)
NODE_SYNTHESIZE = "synthesize_evidence"
NODE_PLAN = "plan_experiments"
NODE_FREEZE = "validate_and_freeze_plan"
NODE_EVALUATE = "evaluate_batch"
NODE_INTERPRET = "interpret_results"


class IllegalTransition(Exception):
    pass


class StudyFailed(Exception):
    def __init__(self, kind: str, message: str, details: list[str] | None = None) -> None:
        self.kind = kind
        self.details = details or []
        super().__init__(message)


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


class GraphState(TypedDict):
    branches: Annotated[list[BranchResult], operator.add]
    research: ResearchRecord
    coordinator_messages: list[BaseMessage]
    draft: PlanDraft
    plan_errors: list[str]
    plan_revision: int
    plan: StudyPlan
    records: list[ExperimentRecord]
    report: StudyReport


@dataclass
class _Progress:
    """What exists so far, so a failed study still saves an honest partial record."""

    research: ResearchRecord | None = None
    plan: StudyPlan | None = None
    records: list[ExperimentRecord] = field(default_factory=list)
    report: StudyReport | None = None


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
    progress: _Progress,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Wire the study. Each node receives only the capabilities its phase needs.

    Research nodes get evidence tools. Only the evaluation node holds
    `evaluate`. The interpretation node gets a model with no tools at all.
    """
    capabilities: EvaluatorCapabilities = package.capabilities
    ledger = ResearchLedger()

    def research_node(spec: InvestigatorSpec) -> Any:
        async def node(state: GraphState) -> dict[str, Any]:
            result = await run_investigator(
                spec,
                package,
                model=research_model,
                search=search,
                reader=reader,
                ledger=ledger,
                events=events,
            )
            return {"branches": [result]}

        return node

    async def synthesize_evidence(state: GraphState) -> dict[str, Any]:
        order = {name: index for index, name in enumerate(RESEARCH_NODES)}
        branches = tuple(sorted(state["branches"], key=lambda b: order[b.investigator]))
        research = ResearchRecord(
            study_id=package.study_id,
            branches=branches,
            findings=ledger.findings,
            sources=ledger.sources,
        )
        progress.research = research
        store.write_json("research.json", research)
        if all(branch.status == "failed" for branch in branches):
            raise StudyFailed(
                "research_failed",
                "All three research branches failed, so there is no evidence to plan from.",
                [f"{b.investigator}: {b.error}" for b in branches],
            )
        if not research.findings:
            raise StudyFailed(
                "no_evidence",
                "Research produced no sourced findings, so no evidence-based plan can be made.",
            )
        machine.transition(StudyState.PLANNING)
        return {
            "research": research,
            "coordinator_messages": initial_messages(package, research),
            "plan_revision": 0,
        }

    async def plan_experiments(state: GraphState) -> dict[str, Any]:
        try:
            draft, messages = await propose_plan(
                coordinator_model,
                state["coordinator_messages"],
                study_id=package.study_id,
                revision=state["plan_revision"],
            )
        except PlanningFailed as exc:
            raise StudyFailed("planning_failed", str(exc), exc.errors) from exc
        return {"draft": draft, "coordinator_messages": messages}

    async def validate_and_freeze_plan(state: GraphState) -> dict[str, Any]:
        revision = state["plan_revision"]
        accepted = frozenset(f.finding_id for f in state["research"].findings)
        plan, errors = build_plan(state["draft"], package, accepted, plan_version=revision + 1)
        if plan is not None and check_buildable is not None:
            # Dial ranges cannot say whether a combination of values fits this ear, so each design
            # is test-built now, while the plan can still be corrected and before any result exists.
            errors = await unbuildable_candidates(
                plan, check_buildable, package.budget.max_parallel_evaluations
            )
            if errors:
                plan = None
        if plan is None:
            if revision >= package.budget.max_plan_revisions:
                raise StudyFailed(
                    "plan_invalid",
                    f"The plan was still not executable after {revision} revision(s).",
                    errors,
                )
            events.emit(
                "plan.revision_requested",
                f"The draft plan had {len(errors)} validation problem(s); asking the coordinator to correct it.",
                component="plan_validation",
                data={"errors": errors, "revision": revision + 1},
            )
            return {
                "plan_errors": errors,
                "plan_revision": revision + 1,
                "coordinator_messages": [
                    *state["coordinator_messages"],
                    HumanMessage(content=revision_request(errors)),
                ],
            }
        frozen = freeze_plan(plan)
        progress.plan = frozen
        store.write_json("plan.json", frozen)
        for hypothesis in frozen.hypotheses:
            events.emit(
                "hypothesis.created",
                hypothesis.statement[:300],
                component="study_coordinator",
                hypothesis_ids=[hypothesis.hypothesis_id],
                finding_ids=hypothesis.supporting_finding_ids,
                candidate_ids=hypothesis.candidate_ids,
                data={"metric": hypothesis.metric, "varied_parameter": hypothesis.varied_parameter},
            )
        machine.transition(StudyState.PLAN_FROZEN)
        events.emit(
            "plan.frozen",
            (
                f"Plan frozen: {len(frozen.candidates)} candidates, {len(frozen.experiments)} "
                f"evaluation cases, {len(frozen.hypotheses)} hypotheses."
            ),
            component="plan_validation",
            hypothesis_ids=[h.hypothesis_id for h in frozen.hypotheses],
            candidate_ids=[c.candidate_id for c in frozen.candidates],
            experiment_ids=[e.experiment_id for e in frozen.experiments],
            artifacts=["plan.json"],
            data={"plan_hash": frozen.plan_hash, "plan_version": frozen.plan_version},
        )
        return {"plan": frozen, "plan_errors": []}

    def after_validation(state: GraphState) -> str:
        return NODE_PLAN if state.get("plan_errors") else NODE_EVALUATE

    async def evaluate_batch(state: GraphState) -> dict[str, Any]:
        plan = state["plan"]
        if not plan.is_frozen or plan.plan_hash != plan.compute_hash():
            raise StudyFailed("plan_not_frozen", "Refusing to evaluate a plan that is not frozen.")
        machine.transition(StudyState.EVALUATING)
        gate = asyncio.Semaphore(package.budget.max_parallel_evaluations)

        async def run_one(spec: Any) -> ExperimentRecord:
            async with gate:
                return await execute_experiment(
                    spec,
                    evaluate=evaluate,
                    capabilities=capabilities,
                    max_attempts=package.budget.max_attempts_per_experiment,
                    cache=cache,
                    events=events,
                    plan_hash=plan.plan_hash,
                )

        records = list(await asyncio.gather(*(run_one(spec) for spec in plan.experiments)))
        progress.records = records
        store.write_json("experiment_results.json", {"plan_hash": plan.plan_hash, "records": records})
        return {"records": records}

    async def interpret_results(state: GraphState) -> dict[str, Any]:
        machine.transition(StudyState.INTERPRETING)
        plan, records, research = state["plan"], state["records"], state["research"]
        summaries, selection = summarize_candidates(plan, records, capabilities)
        data = hypothesis_data(plan, records)
        needs = need_outcomes(plan, records, capabilities, selection)
        narrative, narrative_error = None, None
        try:
            narrative = await write_narrative(
                interpreter_model,
                interpretation_brief(package, plan, research, summaries, selection, data, needs, records),
                study_id=package.study_id,
                plan_hash=plan.plan_hash,
                is_fixture=capabilities.kind == "development_fixture",
            )
        except Exception as exc:  # the numbers stand without the prose
            narrative_error = f"{type(exc).__name__}: {exc}"[:300]
        report = build_report(
            package, plan, research, records, summaries, selection, data, needs, narrative, narrative_error
        )
        progress.report = report
        events.emit(
            "report.completed",
            _whole_sentences(report.selection.explanation, 300),
            component="results_interpreter",
            candidate_ids=[report.selected_candidate_id] if report.selected_candidate_id else [],
            hypothesis_ids=[h.hypothesis_id for h in report.hypotheses],
            data={
                "selected_candidate_id": report.selected_candidate_id,
                "reason_code": report.selection.reason_code,
                "follow_up_proposal_ids": [p.proposal_id for p in report.follow_up_proposals],
            },
        )
        return {"report": report}

    builder: StateGraph[GraphState, Any, Any, Any] = StateGraph(GraphState)
    for spec in INVESTIGATORS:
        builder.add_node(spec.name, research_node(spec))
        builder.add_edge(START, spec.name)
    builder.add_node(NODE_SYNTHESIZE, synthesize_evidence)
    builder.add_node(NODE_PLAN, plan_experiments)
    builder.add_node(NODE_FREEZE, validate_and_freeze_plan)
    builder.add_node(NODE_EVALUATE, evaluate_batch)
    builder.add_node(NODE_INTERPRET, interpret_results)
    builder.add_edge(list(RESEARCH_NODES), NODE_SYNTHESIZE)
    builder.add_edge(NODE_SYNTHESIZE, NODE_PLAN)
    builder.add_edge(NODE_PLAN, NODE_FREEZE)
    builder.add_conditional_edges(NODE_FREEZE, after_validation, [NODE_PLAN, NODE_EVALUATE])
    builder.add_edge(NODE_EVALUATE, NODE_INTERPRET)
    builder.add_edge(NODE_INTERPRET, END)
    return builder.compile(name="study")


def _whole_sentences(text: str, limit: int) -> str:
    """Shorten text for an event summary, ending on a full sentence when one fits."""
    if len(text) <= limit:
        return text
    end = text.rfind(". ", 0, limit)
    return text[: end + 1] if end > 0 else text[:limit]


async def unbuildable_candidates(
    plan: StudyPlan, check_buildable: BuildabilityCheck, max_parallel: int
) -> list[str]:
    """Ask the evaluator to test-build each design in a draft plan. Returns one error per design
    that cannot be built, worded so the coordinator can change it. Nothing is scored here.

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
    progress: _Progress,
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
    progress = _Progress()

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
                {"branches": []},
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
