"""The study coordinator: evidence in, one validated frozen plan out.

A model proposes the plan. Code decides whether it is executable: every
candidate, scenario, metric, and case count is checked against the evaluator
capabilities and the budget before the plan is frozen. Corrections happen
here, before any result exists.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, Field, ValidationError

from horn_study.contracts import (
    ID_PATTERN,
    Candidate,
    CapabilitySnapshot,
    EvaluatorCapabilities,
    ExperimentSpec,
    GeometryFamily,
    Hypothesis,
    MetricConstraint,
    NeedCoverage,
    ParameterValue,
    ResearchRecord,
    SelectionRule,
    StartingPackage,
    StudyPlan,
)
from horn_study.intake import normalize_token, user_needs
from horn_study.research import render_package

_ID = re.compile(ID_PATTERN)


# Model-facing schemas. Every field is required and none is a union: providers
# compile these into a constrained-output grammar, and optional or union fields
# multiply its size. "Not applicable" is an empty string or an empty list.


class DraftParameter(BaseModel):
    name: str
    value: float = Field(description="Numeric value in the parameter's unit. Use 0 for a choice parameter.")
    choice: str = Field(description="Only for choice parameters: the chosen option. Otherwise empty.")


class DraftCandidate(BaseModel):
    candidate_id: str
    kind: Literal["design", "baseline"]
    family_id: str = Field(description="Geometry family of a design. Empty for a baseline.")
    baseline_id: str = Field(description="Baseline ID of a baseline. Empty for a design.")
    parameters: list[DraftParameter] = Field(
        description="One entry per family parameter. Empty for a baseline."
    )
    label: str
    rationale: str


class DraftHypothesis(BaseModel):
    hypothesis_id: str
    statement: str
    supporting_finding_ids: list[str]
    user_goals: list[str]
    candidate_ids: list[str]
    metric: str
    varied_parameter: str = Field(description="The one parameter this comparison varies, or empty.")
    scenario_ids: list[str] = Field(
        description="Scenarios this comparison uses. Empty means all in the plan."
    )
    supports_if: str
    contradicts_if: str


class DraftNeedCoverage(BaseModel):
    need: str
    classification: Literal["modeled", "untested"]
    scenario_ids: list[str]
    metric_names: list[str]
    explanation: str


class DraftConstraint(BaseModel):
    metric: str
    bound: Literal["max", "min"]
    value: float


class DraftSelection(BaseModel):
    primary_metric: str
    reference_candidate_id: str
    tie_breaker_metrics: list[str]
    constraints: list[DraftConstraint]


class PlanDraft(BaseModel):
    """The coordinator's proposal. Not executable until validated and frozen."""

    rationale: str
    hypotheses: list[DraftHypothesis]
    candidates: list[DraftCandidate]
    scenario_ids: list[str]
    canal_config_ids: list[str] = Field(description="Empty means the evaluator's default.")
    seeds: list[int] = Field(description="Empty means one run per case.")
    fidelity: str = Field(description="A supported fidelity level, or empty for the default.")
    selection: DraftSelection
    needs_coverage: list[DraftNeedCoverage]
    conflicting_goals: list[str]
    future_work: list[str]


COORDINATOR_PROMPT = """\
You are the study coordinator for a study of a passive, battery-free hearing device: a \
printed horn whose geometry shapes its acoustic response. Three investigators have researched \
the hearing profile, the use context, and the acoustic design space. Your job is to turn their \
findings into one coherent, executable study: hypotheses, controls, candidate designs, fixed \
comparison settings, and the reason for each choice.

The plan is fixed before anything is evaluated. Once it is frozen, exactly these cases run \
and the study ends with a report. Nothing can be added after results exist, so include what \
you want compared now, as far as the evaluation budget allows: controls, a spread across a \
geometry family, controlled comparisons that vary one parameter while holding the others \
fixed, and robustness scenarios.

How the plan becomes experiments
- Every candidate is evaluated in every scenario, canal configuration, and seed you list. \
The number of evaluation cases is candidates x scenarios x canal configurations x seeds, and \
it must not exceed budget.max_evaluation_cases.
- Leave canal_config_ids empty to use the evaluator's default, and seeds empty for one run \
per case.
- Read capabilities.planning_notes first and follow them. They are the evaluator owner's \
guidance on how to spend the budget, for example which of candidates and scenarios is the \
expensive one.

What the study must cover
- The plan must list at least capabilities.minimum_scenarios scenarios, and at least one \
scenario carrying each tag in capabilities.required_scenario_tags. A plan without this \
coverage is rejected.
- A design that helps in one listening situation can hurt in another, so prefer a broad set \
of scenarios over a long list of candidates. When the budget is tight, remove candidates \
before you go below the required coverage.

What makes the plan valid
- Use only geometry families, parameter names and bounds, baselines, scenarios, metrics, and \
fidelity levels from the evaluator capabilities. Give every parameter of a design \
candidate's family a value.
- Include the unaided control as a baseline candidate and use it as \
selection.reference_candidate_id. Add the generic-device baseline when the evaluator offers \
one and the budget allows.
- Each hypothesis is a specific, testable proposal, not a result. It cites the finding IDs \
that motivate it, names at least two candidates to compare and one metric, and says what \
outcome would support or contradict it.
- The selection rule is applied by code. A design can be selected only if it is not worse \
than the reference control on the primary metric in any scenario of the plan, and its \
average over all of its cases is better than the control's. The per-scenario comparison \
allows for the primary metric's declared resolution. This is always enforced and you cannot \
relax it. Choose the primary metric that best reflects the user's top priority, and use \
constraints or tie-breakers for secondary priorities that a supported metric can express.
- Account for every entry in the user's normalized activities, goals, priorities, and \
requirements exactly once in needs_coverage, using the normalized text. Mark a need \
"modeled" only when a scenario or metric in this plan actually tests it, and name them. \
Otherwise mark it "untested" and say why. Never invent a metric for an unsupported need, and \
treat the evaluator's listed unsupported requirements as untested.
- When the user gave no needs, the study context is the named default: plan a general \
comparison and leave needs_coverage empty.
- Record goals that conflict with each other under conflicting_goals instead of quietly \
choosing between them.
- Put worthwhile ideas the evaluator cannot run under future_work.

The hearing measurements are user-supplied inputs. Do not alter, extend, or reinterpret \
them, and do not describe a diagnosis.

Some evaluators test-build each design before the plan is frozen. If a design comes back as \
unbuildable, change the dials its message names, or replace the design: the same values will \
fail the same way.

If the plan comes back with validation errors, correct exactly those problems and resubmit \
the complete plan.\
"""


def coordinator_brief(package: StartingPackage, research: ResearchRecord) -> str:
    research_view = {
        "investigators": [
            {
                "investigator": branch.investigator,
                "status": branch.status,
                "error": branch.error,
                "report": branch.output.model_dump(mode="json") if branch.output else None,
            }
            for branch in research.branches
        ],
        "findings": [finding.model_dump(mode="json") for finding in research.findings],
    }
    return (
        "Starting package (the same one every investigator received):\n\n"
        + render_package(package)
        + "\n\nResearch results:\n\n"
        + json.dumps(research_view, indent=1, ensure_ascii=False)
        + "\n\nDesign the study plan."
    )


def revision_request(errors: list[str]) -> str:
    listed = "\n".join(f"- {error}" for error in errors)
    return (
        "The plan cannot be frozen yet. No experiment has run. "
        f"Fix these validation errors and resubmit the complete plan:\n{listed}"
    )


async def propose_plan(
    model: BaseChatModel, messages: list[BaseMessage], *, study_id: str, revision: int
) -> tuple[PlanDraft, list[BaseMessage]]:
    """Ask the coordinator for a draft. It has no tools of any kind."""
    agent = create_agent(
        model,
        tools=[],
        system_prompt=COORDINATOR_PROMPT,
        middleware=[ModelRetryMiddleware(max_retries=2, on_failure="error")],
        response_format=PlanDraft,
        name="study_coordinator",
    )
    conversation: Any = {"messages": messages}
    result = await agent.ainvoke(
        conversation,
        config={
            "run_name": "study_coordinator",
            "recursion_limit": 12,
            "tags": ["planning"],
            "metadata": {"study_id": study_id, "component": "study_coordinator", "plan_revision": revision},
        },
    )
    draft = result.get("structured_response")
    if not isinstance(draft, PlanDraft):
        raise PlanningFailed(["The coordinator did not return a structured plan."])
    return draft, list(result["messages"])


class PlanningFailed(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _coerce_parameters(
    candidate: DraftCandidate, family: GeometryFamily, errors: list[str]
) -> dict[str, ParameterValue]:
    where = f"candidate '{candidate.candidate_id}'"
    given: dict[str, DraftParameter] = {}
    for parameter in candidate.parameters:
        if parameter.name in given:
            errors.append(f"{where}: parameter '{parameter.name}' is given more than once.")
        given[parameter.name] = parameter
    declared = {p.name: p for p in family.parameters}
    for name in given:
        if name not in declared:
            errors.append(
                f"{where}: '{name}' is not a parameter of family '{family.family_id}' "
                f"(parameters: {', '.join(declared)})."
            )
    values: dict[str, ParameterValue] = {}
    for name, spec in declared.items():
        if name not in given:
            errors.append(f"{where}: missing a value for parameter '{name}'.")
            continue
        if spec.kind == "choice":
            if given[name].choice not in spec.choices:
                errors.append(f"{where}: '{name}' must be one of {list(spec.choices)}.")
                continue
            values[name] = given[name].choice
            continue
        value = given[name].value
        if not math.isfinite(value):
            errors.append(f"{where}: '{name}' must be a number in {spec.unit or 'its unit'}.")
            continue
        if spec.kind == "int" and float(value) != int(value):
            errors.append(f"{where}: '{name}' must be a whole number.")
            continue
        unit = f" {spec.unit}" if spec.unit else ""
        if spec.minimum is not None and value < spec.minimum:
            errors.append(f"{where}: {name}={value:g} is below the minimum {spec.minimum:g}{unit}.")
            continue
        if spec.maximum is not None and value > spec.maximum:
            errors.append(f"{where}: {name}={value:g} is above the maximum {spec.maximum:g}{unit}.")
            continue
        values[name] = int(value) if spec.kind == "int" else float(value)
    return values


def _unique(values: list[Any], what: str, errors: list[str]) -> None:
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            errors.append(f"Duplicate {what} '{value}'.")
        seen.add(value)


def _coverage_requirement(caps: EvaluatorCapabilities) -> str:
    """The evaluator's coverage requirement in words, or empty when it declares none."""
    parts: list[str] = []
    if caps.minimum_scenarios > 1:
        parts.append(f"at least {caps.minimum_scenarios} scenarios")
    if caps.required_scenario_tags:
        tags = ", ".join(f"'{tag}'" for tag in caps.required_scenario_tags)
        parts.append(f"at least one scenario tagged each of {tags}")
    return " and ".join(parts)


def _coverage_errors(scenario_ids: list[str], caps: EvaluatorCapabilities) -> list[str]:
    """Check the listed scenarios against the coverage the evaluator requires of every study."""
    errors: list[str] = []
    listed = [s for s in caps.scenarios if s.scenario_id in scenario_ids]
    unlisted = [s.scenario_id for s in caps.scenarios if s.scenario_id not in scenario_ids]
    if scenario_ids and len(listed) < caps.minimum_scenarios:
        errors.append(
            f"Too few scenarios: the plan lists {len(listed)} supported "
            f"scenario{'' if len(listed) == 1 else 's'}, but this evaluator requires at least "
            f"{caps.minimum_scenarios} in every study. Add from: {', '.join(unlisted)}."
        )
    for tag in caps.required_scenario_tags:
        if any(tag in s.tags for s in listed):
            continue
        carriers = ", ".join(s.scenario_id for s in caps.scenarios if tag in s.tags)
        errors.append(
            f"Missing required coverage: every study must include at least one scenario tagged "
            f"'{tag}'. Add one of: {carriers}."
        )
    return errors


def _over_budget_advice(caps: EvaluatorCapabilities) -> str:
    requirement = _coverage_requirement(caps)
    if not requirement:
        return "Remove candidates, scenarios, canal configurations, or seeds."
    return (
        "Remove candidates, canal configurations, or seeds first. Scenarios can be removed only "
        f"while the plan keeps {requirement}."
    )


def build_plan(
    draft: PlanDraft,
    package: StartingPackage,
    accepted_finding_ids: frozenset[str],
    plan_version: int,
) -> tuple[StudyPlan | None, list[str]]:
    """Validate a draft against capabilities and budget.

    Returns (plan, []) when executable, or (None, errors) describing every
    problem in terms the coordinator can act on.
    """
    caps: EvaluatorCapabilities = package.capabilities
    errors: list[str] = []

    # -- candidates --------------------------------------------------------
    _unique([c.candidate_id for c in draft.candidates], "candidate_id", errors)
    candidates: list[Candidate] = []
    signatures: dict[str, str] = {}
    for item in draft.candidates:
        if not _ID.match(item.candidate_id):
            errors.append(f"candidate_id '{item.candidate_id}' must be letters, digits, '_', '-', or '.'.")
            continue
        if item.kind == "baseline":
            if caps.baseline(item.baseline_id or "") is None:
                available = ", ".join(b.baseline_id for b in caps.baselines) or "none"
                errors.append(
                    f"candidate '{item.candidate_id}': baseline '{item.baseline_id}' is not "
                    f"supported (available: {available})."
                )
                continue
            if item.parameters or item.family_id:
                errors.append(f"candidate '{item.candidate_id}': a baseline has no family or parameters.")
                continue
            parameters: dict[str, ParameterValue] = {}
            signature = f"baseline:{item.baseline_id}"
        else:
            family = caps.family(item.family_id or "")
            if family is None:
                available = ", ".join(f.family_id for f in caps.geometry_families)
                errors.append(
                    f"candidate '{item.candidate_id}': geometry family '{item.family_id}' is not "
                    f"supported (available: {available})."
                )
                continue
            before = len(errors)
            parameters = _coerce_parameters(item, family, errors)
            if len(errors) > before:
                continue
            signature = f"{family.family_id}:{sorted(parameters.items())}"
        if signature in signatures:
            errors.append(
                f"candidate '{item.candidate_id}' duplicates '{signatures[signature]}' "
                "(same design or baseline)."
            )
            continue
        signatures[signature] = item.candidate_id
        candidates.append(
            Candidate(
                candidate_id=item.candidate_id,
                kind=item.kind,
                family_id=item.family_id if item.kind == "design" else None,
                baseline_id=item.baseline_id if item.kind == "baseline" else None,
                parameters=parameters,
                label=item.label,
                rationale=item.rationale,
            )
        )
    by_id = {c.candidate_id: c for c in candidates}
    draft_ids = {c.candidate_id for c in draft.candidates}

    if not any(c.kind == "design" for c in candidates) and not errors:
        errors.append("The plan needs at least one design candidate.")
    unaided = [b.baseline_id for b in caps.baselines if b.kind == "unaided"]
    if unaided and not any(c.baseline_id in unaided for c in candidates):
        errors.append(f"Missing control: include a baseline candidate with baseline_id '{unaided[0]}'.")

    # -- comparison settings -----------------------------------------------
    scenario_names = {s.scenario_id for s in caps.scenarios}
    _unique(draft.scenario_ids, "scenario_id", errors)
    if not draft.scenario_ids:
        errors.append("List at least one scenario_id.")
    for scenario_id in draft.scenario_ids:
        if scenario_id not in scenario_names:
            errors.append(
                f"Scenario '{scenario_id}' is not supported (available: {', '.join(sorted(scenario_names))})."
            )
    errors.extend(_coverage_errors(draft.scenario_ids, caps))

    canal_names = {c.canal_config_id for c in caps.canal_configurations}
    _unique(draft.canal_config_ids, "canal_config_id", errors)
    for canal_id in draft.canal_config_ids:
        if canal_id not in canal_names:
            errors.append(
                f"Canal configuration '{canal_id}' is not supported "
                f"(available: {', '.join(sorted(canal_names)) or 'none'})."
            )
    canal_ids: tuple[str | None, ...] = tuple(draft.canal_config_ids) or (caps.default_canal_config_id(),)

    _unique(draft.seeds, "seed", errors)
    if draft.seeds and not caps.supports_seeds:
        errors.append("This evaluator does not support seeds. Leave seeds empty.")
    if len(draft.seeds) > caps.max_repetitions:
        errors.append(
            f"{len(draft.seeds)} seeds requested but the evaluator supports at most "
            f"{caps.max_repetitions} repetitions."
        )
    seeds: tuple[int | None, ...] = tuple(draft.seeds) or ((0,) if caps.supports_seeds else (None,))

    fidelity = draft.fidelity or caps.default_fidelity
    if fidelity not in caps.fidelity_levels:
        errors.append(
            f"Fidelity '{fidelity}' is not supported (available: {', '.join(caps.fidelity_levels)})."
        )

    # -- metrics and selection rule ----------------------------------------
    metric_names = {m.name for m in caps.metrics}

    def check_metric(name: str, where: str) -> bool:
        if name in metric_names:
            return True
        errors.append(
            f"{where}: metric '{name}' is not supported (available: {', '.join(sorted(metric_names))})."
        )
        return False

    informational = {m.name for m in caps.metrics if m.direction == "informational"}

    def check_rankable(name: str, where: str) -> bool:
        if not check_metric(name, where):
            return False
        if name in informational:
            errors.append(
                f"{where}: metric '{name}' is informational and has no better or worse direction, "
                "so it cannot rank designs. Use it only in a constraint or a hypothesis."
            )
            return False
        return True

    selection = draft.selection
    primary_ok = check_rankable(selection.primary_metric, "selection.primary_metric")
    for name in selection.tie_breaker_metrics:
        check_rankable(name, "selection.tie_breaker_metrics")
    constrained = {constraint.metric for constraint in selection.constraints}
    for constraint in selection.constraints:
        check_metric(constraint.metric, "selection.constraints")
    reference = by_id.get(selection.reference_candidate_id)
    if reference is None:
        if selection.reference_candidate_id not in draft_ids:
            errors.append(
                f"selection.reference_candidate_id '{selection.reference_candidate_id}' is not a candidate."
            )
    elif reference.kind != "baseline":
        errors.append("selection.reference_candidate_id must be a baseline control candidate.")

    # -- hypotheses --------------------------------------------------------
    _unique([h.hypothesis_id for h in draft.hypotheses], "hypothesis_id", errors)
    if not draft.hypotheses:
        errors.append("The plan needs at least one hypothesis.")
    parameter_names = {p.name for f in caps.geometry_families for p in f.parameters}
    hypotheses: list[Hypothesis] = []
    for item in draft.hypotheses:
        where = f"hypothesis '{item.hypothesis_id}'"
        before = len(errors)
        if not _ID.match(item.hypothesis_id):
            errors.append(f"hypothesis_id '{item.hypothesis_id}' must be letters, digits, '_', '-', or '.'.")
        cited = [f for f in item.supporting_finding_ids if f in accepted_finding_ids]
        unknown = [f for f in item.supporting_finding_ids if f not in accepted_finding_ids]
        if unknown:
            errors.append(f"{where}: finding IDs {unknown} do not exist. Cite recorded findings only.")
        if not cited and not unknown:
            errors.append(f"{where}: cite at least one recorded finding that motivates it.")
        missing = [c for c in item.candidate_ids if c not in draft_ids]
        if missing:
            errors.append(f"{where}: candidate IDs {missing} are not in the plan.")
        if len(set(item.candidate_ids)) < 2:
            errors.append(f"{where}: name at least two candidates to compare.")
        check_metric(item.metric, where)
        if item.varied_parameter and item.varied_parameter not in parameter_names:
            errors.append(
                f"{where}: varied_parameter '{item.varied_parameter}' is not a supported parameter."
            )
        outside = [s for s in item.scenario_ids if s not in draft.scenario_ids]
        if outside:
            errors.append(f"{where}: scenarios {outside} are not in the plan's scenario_ids.")
        if len(errors) == before:
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=item.hypothesis_id,
                    statement=item.statement,
                    supporting_finding_ids=tuple(cited),
                    user_goals=tuple(item.user_goals),
                    candidate_ids=tuple(dict.fromkeys(item.candidate_ids)),
                    metric=item.metric,
                    varied_parameter=item.varied_parameter or None,
                    scenario_ids=tuple(item.scenario_ids) or tuple(draft.scenario_ids),
                    supports_if=item.supports_if,
                    contradicts_if=item.contradicts_if,
                )
            )

    # -- needs -------------------------------------------------------------
    required = user_needs(package.study_context)
    unsupported = {normalize_token(u.requirement) for u in caps.unsupported_requirements}
    covered: dict[str, DraftNeedCoverage] = {}
    coverage: list[NeedCoverage] = []
    for item in draft.needs_coverage:
        key = normalize_token(item.need)
        where = f"needs_coverage '{item.need}'"
        if key in covered:
            errors.append(f"{where}: listed more than once.")
            continue
        covered[key] = item
        if item.classification == "modeled":
            if key in unsupported:
                errors.append(
                    f"{where}: the evaluator declares this requirement unsupported. Mark it 'untested'."
                )
            if not item.scenario_ids and not item.metric_names:
                errors.append(
                    f"{where}: a 'modeled' need must name the scenario or metric in this plan that tests it."
                )
            outside = [s for s in item.scenario_ids if s not in draft.scenario_ids]
            if outside:
                errors.append(f"{where}: scenarios {outside} are not in the plan's scenario_ids.")
            for name in item.metric_names:
                if check_metric(name, where) and name in informational and name not in constrained:
                    errors.append(
                        f"{where}: metric '{name}' is informational, so it shows a need is met only "
                        "through a selection constraint on it. Add the constraint or mark the need 'untested'."
                    )
        elif item.scenario_ids or item.metric_names:
            errors.append(f"{where}: an 'untested' need cannot list scenarios or metrics.")
        coverage.append(
            NeedCoverage(
                need=key,
                classification=item.classification,
                scenario_ids=tuple(item.scenario_ids),
                metric_names=tuple(item.metric_names),
                explanation=item.explanation,
            )
        )
    for need in required:
        if need not in covered:
            errors.append(
                f"needs_coverage is missing the user's need '{need}'. Classify it as 'modeled' or 'untested'."
            )

    # -- budget ------------------------------------------------------------
    total = len(draft.candidates) * len(draft.scenario_ids) * len(canal_ids) * len(seeds)
    limit = package.budget.max_evaluation_cases
    if total > limit:
        errors.append(
            f"Over budget: {len(draft.candidates)} candidates x {len(draft.scenario_ids)} scenarios x "
            f"{len(canal_ids)} canal configurations x {len(seeds)} seeds = {total} evaluation cases, "
            f"but the budget allows {limit}. {_over_budget_advice(caps)}"
        )

    if errors:
        return None, errors
    assert reference is not None
    assert primary_ok
    primary = caps.metric(selection.primary_metric)
    assert primary is not None
    assert primary.direction != "informational"  # rejected above by check_rankable

    experiments = tuple(
        ExperimentSpec(
            study_id=package.study_id,
            experiment_id=_experiment_id(candidate.candidate_id, scenario_id, canal_id, seed),
            candidate_id=candidate.candidate_id,
            candidate_kind=candidate.kind,
            family_id=candidate.family_id,
            baseline_id=candidate.baseline_id,
            parameters=dict(candidate.parameters),
            hearing_input=package.hearing_input,
            scenario_id=scenario_id,
            canal_config_id=canal_id,
            ear_mesh_ref=package.anatomy.ear_mesh_ref,
            seed=seed,
            fidelity=fidelity,
            calibration_ref=caps.calibration.calibration_ref,
        )
        for candidate in candidates
        for scenario_id in draft.scenario_ids
        for canal_id in canal_ids
        for seed in seeds
    )
    try:
        plan = StudyPlan(
            study_id=package.study_id,
            plan_version=plan_version,
            capability_snapshot=CapabilitySnapshot(
                evaluator_name=caps.evaluator_name,
                evaluator_version=caps.evaluator_version,
                kind=caps.kind,
                capabilities_hash=caps.snapshot_hash(),
            ),
            study_context_name=package.study_context.name,
            rationale=draft.rationale,
            hypotheses=tuple(hypotheses),
            candidates=tuple(candidates),
            experiments=experiments,
            scenario_ids=tuple(draft.scenario_ids),
            canal_config_ids=canal_ids,
            seeds=seeds,
            fidelity=fidelity,
            calibration_ref=caps.calibration.calibration_ref,
            metric_names=tuple(m.name for m in caps.metrics),
            selection_rule=SelectionRule(
                primary_metric=primary.name,
                direction=primary.direction,
                reference_candidate_id=reference.candidate_id,
                scenario_tolerance=primary.resolution,
                tie_breaker_metrics=tuple(selection.tie_breaker_metrics),
                constraints=tuple(
                    MetricConstraint(metric=c.metric, bound=c.bound, value=c.value)
                    for c in selection.constraints
                ),
            ),
            needs_coverage=tuple(coverage),
            conflicting_goals=tuple(draft.conflicting_goals),
            future_work=tuple(draft.future_work),
        )
    except ValidationError as exc:
        return None, [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return plan, []


def _experiment_id(candidate_id: str, scenario_id: str, canal_id: str | None, seed: int | None) -> str:
    parts = [candidate_id, scenario_id]
    if canal_id is not None:
        parts.append(canal_id)
    if seed is not None:
        parts.append(f"s{seed}")
    return "--".join(parts)


def freeze_plan(plan: StudyPlan) -> StudyPlan:
    """Stamp the plan's hash and freeze time. Execution accepts only frozen plans."""
    if plan.is_frozen:
        raise ValueError("The plan is already frozen.")
    return plan.model_copy(update={"plan_hash": plan.compute_hash(), "frozen_at": datetime.now(UTC)})


def initial_messages(package: StartingPackage, research: ResearchRecord) -> list[BaseMessage]:
    return [HumanMessage(content=coordinator_brief(package, research))]
