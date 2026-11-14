"""Result aggregation, selection, and the grounded report.

Every number and the selected design are computed here, in code, from the
evaluator's returned results and the frozen plan's rule. A model only explains
the computed comparison. It has no tools and cannot change a score, pick a
different winner, or start anything.
"""

from __future__ import annotations

import json
import math
from statistics import fmean
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from horn_study.contracts import (
    Candidate,
    CandidateSummary,
    EvaluatorCapabilities,
    ExperimentRecord,
    ExperimentSpec,
    FollowUpProposal,
    HypothesisDataPoint,
    HypothesisOutcome,
    MetricAggregate,
    NeedOutcome,
    ResearchRecord,
    Selection,
    StartingPackage,
    StudyPlan,
    StudyReport,
)
from horn_study.evaluator_adapter import FIXTURE_NOTICE

MAX_FOLLOW_UPS = 3


class HypothesisVerdict(BaseModel):
    hypothesis_id: str
    verdict: Literal["supported", "contradicted", "inconclusive"]
    explanation: str


class DraftFollowUp(BaseModel):
    kind: Literal["refine_design", "run_follow_up", "compare_use_case"]
    title: str
    description: str
    rationale: str


class ReportNarrative(BaseModel):
    """The model-written part of the report: explanation only."""

    summary: str
    hypothesis_verdicts: list[HypothesisVerdict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    inconclusive_findings: list[str] = Field(default_factory=list)
    follow_up_proposals: list[DraftFollowUp] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def _metric_values(
    specs: list[ExperimentSpec], records: dict[str, ExperimentRecord], metric: str
) -> list[float]:
    values: list[float] = []
    for spec in specs:
        record = records.get(spec.experiment_id)
        if record is None or record.outcome != "completed" or record.result is None:
            continue
        for item in record.result.metrics:
            if item.name == metric:
                values.append(item.value)
    return values


def _completed(specs: list[ExperimentSpec], records: dict[str, ExperimentRecord]) -> int:
    return sum(
        1
        for spec in specs
        if (record := records.get(spec.experiment_id)) is not None and record.outcome == "completed"
    )


def _signed(direction: str, value: float) -> float:
    return value if direction == "higher_is_better" else -value


def summarize_candidates(
    plan: StudyPlan, records: list[ExperimentRecord], capabilities: EvaluatorCapabilities
) -> tuple[tuple[CandidateSummary, ...], Selection]:
    """Aggregate cases per candidate and apply the frozen selection rule.

    A candidate is judged on all of its planned cases. One that is missing a
    case is not eligible, so a design cannot look better because a hard
    scenario failed.
    """
    rule = plan.selection_rule
    by_experiment = {record.experiment_id: record for record in records}
    units = {m.name: m.unit for m in capabilities.metrics}
    directions = {m.name: m.direction for m in capabilities.metrics}

    drafts: dict[str, dict[str, Any]] = {}
    for candidate in plan.candidates:
        specs = [e for e in plan.experiments if e.candidate_id == candidate.candidate_id]
        aggregates: list[MetricAggregate] = []
        for name in plan.metric_names:
            values = _metric_values(specs, by_experiment, name)
            if values:
                aggregates.append(
                    MetricAggregate(
                        name=name,
                        unit=units.get(name, ""),
                        mean=fmean(values),
                        minimum=min(values),
                        maximum=max(values),
                        n_cases=len(values),
                    )
                )
        primary_values = _metric_values(specs, by_experiment, rule.primary_metric)
        n_completed = _completed(specs, by_experiment)
        drafts[candidate.candidate_id] = {
            "candidate": candidate,
            "n_planned": len(specs),
            "n_completed": n_completed,
            "complete": n_completed == len(specs) and len(primary_values) == len(specs) and bool(specs),
            "metrics": tuple(aggregates),
            "primary": fmean(primary_values) if primary_values else None,
        }

    reference = drafts[rule.reference_candidate_id]
    reference_ok = bool(reference["complete"])

    def mean_of(candidate_id: str, metric: str) -> float | None:
        for aggregate in drafts[candidate_id]["metrics"]:
            if aggregate.name == metric and aggregate.n_cases == drafts[candidate_id]["n_planned"]:
                return aggregate.mean
        return None

    eligible: list[str] = []
    for candidate_id, draft in drafts.items():
        candidate: Candidate = draft["candidate"]
        reasons: list[str] = []
        improvement: float | None = None
        if draft["complete"] and reference_ok:
            improvement = _signed(rule.direction, draft["primary"]) - _signed(
                rule.direction, reference["primary"]
            )
        if candidate.kind == "baseline":
            reasons.append("Baseline control, not a design.")
        else:
            if not draft["complete"]:
                reasons.append(
                    f"Only {draft['n_completed']} of {draft['n_planned']} planned cases completed."
                )
            if not reference_ok:
                reasons.append("The reference control did not complete all of its cases.")
            for constraint in rule.constraints if draft["complete"] else ():
                value = mean_of(candidate_id, constraint.metric)
                if value is None:
                    reasons.append(f"No complete data for constraint metric {constraint.metric}.")
                elif constraint.bound == "max" and value > constraint.value:
                    reasons.append(
                        f"{constraint.metric} mean {value:.4g} exceeds the limit {constraint.value:.4g}."
                    )
                elif constraint.bound == "min" and value < constraint.value:
                    reasons.append(
                        f"{constraint.metric} mean {value:.4g} is below the floor {constraint.value:.4g}."
                    )
            if improvement is not None and improvement <= rule.minimum_improvement:
                reasons.append(f"Does not improve on the reference control for {rule.primary_metric}.")
        draft["improvement"] = improvement
        draft["reasons"] = tuple(reasons)
        if not reasons:
            eligible.append(candidate_id)

    def sort_key(candidate_id: str) -> tuple[float, ...]:
        key = [round(-drafts[candidate_id]["improvement"], 9)]
        for metric in rule.tie_breaker_metrics:
            value = mean_of(candidate_id, metric)
            direction = directions.get(metric, "higher_is_better")
            key.append(round(-_signed(direction, value), 9) if value is not None else math.inf)
        return tuple(key)

    ranked = sorted(eligible, key=lambda cid: (sort_key(cid), cid))
    ranks = {candidate_id: index + 1 for index, candidate_id in enumerate(ranked)}

    unit = units.get(rule.primary_metric, "")
    if not reference_ok:
        selection = Selection(
            selected_candidate_id=None,
            reason_code="reference_incomplete",
            explanation=(
                f"No design was selected: the reference control '{rule.reference_candidate_id}' "
                f"completed {reference['n_completed']} of {reference['n_planned']} planned cases, "
                "so no candidate can be compared against it."
            ),
        )
    elif not ranked:
        selection = Selection(
            selected_candidate_id=None,
            reason_code="no_eligible_candidate",
            explanation=(
                "No design was selected: no candidate completed all planned cases, met the "
                f"plan's constraints, and improved on the reference control for {rule.primary_metric}."
            ),
        )
    elif len(ranked) > 1 and sort_key(ranked[0]) == sort_key(ranked[1]):
        tied = [cid for cid in ranked if sort_key(cid) == sort_key(ranked[0])]
        selection = Selection(
            selected_candidate_id=None,
            reason_code="tie",
            explanation=(
                f"No design was selected: {', '.join(tied)} are tied on {rule.primary_metric} "
                "and every tie-breaker in the plan."
            ),
        )
    else:
        winner = drafts[ranked[0]]
        selection = Selection(
            selected_candidate_id=ranked[0],
            reason_code="selected",
            explanation=(
                f"'{ranked[0]}' has the best mean {rule.primary_metric} among eligible designs: "
                f"{winner['primary']:.4g} {unit} over {winner['n_planned']} completed cases, against "
                f"{reference['primary']:.4g} {unit} for the reference control "
                f"'{rule.reference_candidate_id}'."
            ).replace("  ", " "),
        )

    summaries = tuple(
        CandidateSummary(
            candidate_id=candidate_id,
            kind=draft["candidate"].kind,
            label=draft["candidate"].label,
            n_planned=draft["n_planned"],
            n_completed=draft["n_completed"],
            all_cases_completed=draft["complete"],
            metrics=draft["metrics"],
            primary_metric_mean=draft["primary"],
            improvement_over_reference=draft["improvement"],
            eligible=not draft["reasons"],
            ineligibility_reasons=draft["reasons"],
            rank=ranks.get(candidate_id),
        )
        for candidate_id, draft in drafts.items()
    )
    return summaries, selection


def hypothesis_data(
    plan: StudyPlan, records: list[ExperimentRecord]
) -> dict[str, tuple[tuple[HypothesisDataPoint, ...], bool]]:
    by_experiment = {record.experiment_id: record for record in records}
    output: dict[str, tuple[tuple[HypothesisDataPoint, ...], bool]] = {}
    for hypothesis in plan.hypotheses:
        points: list[HypothesisDataPoint] = []
        complete = True
        for candidate_id in hypothesis.candidate_ids:
            candidate = plan.candidate(candidate_id)
            specs = [
                e
                for e in plan.experiments
                if e.candidate_id == candidate_id and e.scenario_id in hypothesis.scenario_ids
            ]
            values = _metric_values(specs, by_experiment, hypothesis.metric)
            if not specs or len(values) != len(specs):
                complete = False
            points.append(
                HypothesisDataPoint(
                    candidate_id=candidate_id,
                    varied_parameter_value=(
                        candidate.parameters.get(hypothesis.varied_parameter)
                        if candidate is not None and hypothesis.varied_parameter
                        else None
                    ),
                    mean=fmean(values) if values else None,
                    n_completed=len(values),
                    n_planned=len(specs),
                )
            )
        output[hypothesis.hypothesis_id] = (tuple(points), complete)
    return output


def need_outcomes(
    plan: StudyPlan,
    records: list[ExperimentRecord],
    capabilities: EvaluatorCapabilities,
    selection: Selection,
) -> tuple[NeedOutcome, ...]:
    by_experiment = {record.experiment_id: record for record in records}
    directions = {m.name: m.direction for m in capabilities.metrics}
    rule = plan.selection_rule
    constrained = {c.metric for c in rule.constraints}
    outcomes: list[NeedOutcome] = []
    for coverage in plan.needs_coverage:
        if coverage.classification == "untested":
            outcomes.append(
                NeedOutcome(
                    need=coverage.need,
                    status="untested",
                    explanation=coverage.explanation
                    or "The evaluator has no model for this need, so the study did not test it.",
                )
            )
            continue
        selected = selection.selected_candidate_id
        if selected is None:
            outcomes.append(
                NeedOutcome(
                    need=coverage.need,
                    status="evaluated_unsuccessfully",
                    explanation=f"Evaluated, but no design was selected. {selection.explanation}",
                )
            )
            continue
        scenarios = coverage.scenario_ids or plan.scenario_ids
        metrics = coverage.metric_names or (rule.primary_metric,)
        shortfalls: list[str] = []
        for metric in metrics:
            if metric in constrained:
                continue  # the selected design already satisfies the plan's limit on it
            chosen = _metric_values(
                [e for e in plan.experiments if e.candidate_id == selected and e.scenario_id in scenarios],
                by_experiment,
                metric,
            )
            control = _metric_values(
                [
                    e
                    for e in plan.experiments
                    if e.candidate_id == rule.reference_candidate_id and e.scenario_id in scenarios
                ],
                by_experiment,
                metric,
            )
            if not chosen or not control:
                shortfalls.append(f"no complete {metric} data in {', '.join(scenarios)}")
                continue
            direction = directions.get(metric, "higher_is_better")
            if _signed(direction, fmean(chosen)) <= _signed(direction, fmean(control)):
                shortfalls.append(
                    f"{metric} did not improve on the reference control in {', '.join(scenarios)}"
                )
        if shortfalls:
            outcomes.append(
                NeedOutcome(
                    need=coverage.need,
                    status="evaluated_unsuccessfully",
                    explanation=f"For the selected design '{selected}': {'; '.join(shortfalls)}.",
                )
            )
        else:
            outcomes.append(
                NeedOutcome(
                    need=coverage.need,
                    status="addressed",
                    explanation=(
                        f"The selected design '{selected}' improved on the reference control for "
                        f"{', '.join(metrics)} in {', '.join(scenarios)} (modeled result)."
                    ),
                )
            )
    return tuple(outcomes)


# --------------------------------------------------------------------------
# Interpretation
# --------------------------------------------------------------------------

INTERPRETER_PROMPT = """\
You are writing the final interpretation of a completed study of a passive, battery-free \
hearing device (a printed horn). The experiment plan was fixed before evaluation, the \
evaluator has returned its results, and code has already computed every comparison and \
applied the plan's selection rule. The study ends with your report.

You receive the frozen plan, the research findings, the computed candidate comparison, the \
selection outcome, and the data for each hypothesis. Explain what these results show.

- Every number you mention must come from the data provided. Do not estimate, extrapolate, \
or convert a number into other units.
- The selection was made by the plan's rule. Explain it; do not change it or name a \
different winner. If no candidate was selected, say so plainly and give the reason from the data.
- For each hypothesis, compare its data with its own supports_if and contradicts_if \
conditions and give a verdict: supported, contradicted, or inconclusive. Use inconclusive \
when cases are missing or failed, or when the data do not clearly meet either condition.
- These are {result_description}. Describe them as results for a modeled hearing profile \
under the evaluator's declared assumptions. They are not a measurement of what a person \
hears and not a clinical outcome, and they do not show restored or normal hearing.
- List the limitations that matter for reading these results, including failed or missing \
cases, needs the evaluator could not test, and gaps in the evidence.
- You may propose up to three follow-up studies the user could choose to start later \
(refine_design, run_follow_up, or compare_use_case). They are suggestions only: this study \
is finished, nothing further will run because of them, and you cannot run experiments.\
"""


def interpretation_brief(
    package: StartingPackage,
    plan: StudyPlan,
    research: ResearchRecord,
    summaries: tuple[CandidateSummary, ...],
    selection: Selection,
    data: dict[str, tuple[tuple[HypothesisDataPoint, ...], bool]],
    needs: tuple[NeedOutcome, ...],
    records: list[ExperimentRecord],
) -> str:
    view = {
        "study_context": package.study_context.model_dump(mode="json"),
        "hearing_input": {
            "source": package.hearing_input.source,
            "target_ear": package.hearing_input.target_ear,
            "measurements": [m.model_dump(mode="json") for m in package.hearing_input.measurements],
        },
        "evaluator": plan.capability_snapshot.model_dump(mode="json"),
        "plan": {
            "rationale": plan.rationale,
            "candidates": [c.model_dump(mode="json") for c in plan.candidates],
            "scenario_ids": plan.scenario_ids,
            "selection_rule": plan.selection_rule.model_dump(mode="json"),
            "needs_coverage": [n.model_dump(mode="json") for n in plan.needs_coverage],
            "conflicting_goals": plan.conflicting_goals,
            "future_work": plan.future_work,
        },
        "findings": [
            {
                "finding_id": f.finding_id,
                "claim": f.claim,
                "limitations": f.limitations,
                "source_title": f.source_title,
            }
            for f in research.findings
        ],
        "research_gaps": [
            f"{b.investigator}: {b.status}" + (f" ({b.error})" if b.error else "")
            for b in research.branches
            if b.status != "completed"
        ],
        "candidate_comparison": [s.model_dump(mode="json") for s in summaries],
        "selection": selection.model_dump(mode="json"),
        "hypotheses": [
            {
                **h.model_dump(mode="json"),
                "data": [p.model_dump(mode="json") for p in data[h.hypothesis_id][0]],
                "data_complete": data[h.hypothesis_id][1],
            }
            for h in plan.hypotheses
        ],
        "needs_outcomes": [n.model_dump(mode="json") for n in needs],
        "cases_not_completed": [
            {"experiment_id": r.experiment_id, "outcome": r.outcome, "issues": r.issues}
            for r in records
            if r.outcome != "completed"
        ],
    }
    return "Study results:\n\n" + json.dumps(view, indent=1, ensure_ascii=False)


async def write_narrative(
    model: BaseChatModel, brief: str, *, study_id: str, plan_hash: str, is_fixture: bool
) -> ReportNarrative:
    """Ask the interpreter to explain the computed results. It has no tools."""
    description = (
        "development-fixture placeholder numbers, not simulation results, and the summary must say so"
        if is_fixture
        else "simulation results"
    )
    agent = create_agent(
        model,
        tools=[],
        system_prompt=INTERPRETER_PROMPT.format(result_description=description),
        middleware=[ModelRetryMiddleware(max_retries=2, on_failure="error")],
        response_format=ReportNarrative,
        name="results_interpreter",
    )
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": brief}]},
        config={
            "run_name": "results_interpreter",
            "recursion_limit": 12,
            "tags": ["interpretation"],
            "metadata": {"study_id": study_id, "component": "results_interpreter", "plan_hash": plan_hash},
        },
    )
    narrative = result.get("structured_response")
    if not isinstance(narrative, ReportNarrative):
        raise ValueError("The interpreter did not return a structured report.")
    return narrative


def build_report(
    package: StartingPackage,
    plan: StudyPlan,
    research: ResearchRecord,
    records: list[ExperimentRecord],
    summaries: tuple[CandidateSummary, ...],
    selection: Selection,
    data: dict[str, tuple[tuple[HypothesisDataPoint, ...], bool]],
    needs: tuple[NeedOutcome, ...],
    narrative: ReportNarrative | None,
    narrative_error: str | None = None,
) -> StudyReport:
    """Assemble the report. Code-owned facts always win over model text."""
    caps = package.capabilities
    is_fixture = caps.kind == "development_fixture"
    units = {m.name: m.unit for m in caps.metrics}
    verdicts = {v.hypothesis_id: v for v in (narrative.hypothesis_verdicts if narrative else [])}

    hypotheses: list[HypothesisOutcome] = []
    for hypothesis in plan.hypotheses:
        points, complete = data[hypothesis.hypothesis_id]
        given = verdicts.get(hypothesis.hypothesis_id)
        if not complete:
            verdict, explanation = (
                "inconclusive",
                "Some planned cases for this comparison did not complete, so it cannot be judged.",
            )
        elif given is None:
            verdict, explanation = "inconclusive", "No interpretation is available for this hypothesis."
        else:
            verdict, explanation = given.verdict, given.explanation
        hypotheses.append(
            HypothesisOutcome(
                hypothesis_id=hypothesis.hypothesis_id,
                metric=hypothesis.metric,
                unit=units.get(hypothesis.metric, ""),
                data=points,
                data_complete=complete,
                verdict=verdict,
                explanation=explanation,
            )
        )

    not_completed = tuple(r.experiment_id for r in records if r.outcome != "completed")
    limitations: list[str] = []
    if is_fixture:
        limitations.append(FIXTURE_NOTICE)
    limitations.append(
        "The hearing measurements were supplied by the user from an existing test and were not "
        "verified by this app. Results describe a modeled hearing profile under the evaluator's "
        "declared assumptions, not a diagnosis or a measurement of what a person hears."
    )
    if package.hearing_input.source == "synthetic_demo":
        limitations.append("The hearing profile is synthetic demo data, not a person's test results.")
    if package.study_context.is_default:
        limitations.append(
            f"No activities or needs were supplied, so the '{package.study_context.name}' study context was used."
        )
    if not_completed:
        limitations.append(
            f"{len(not_completed)} of {len(plan.experiments)} planned evaluation cases did not "
            f"complete: {', '.join(not_completed)}."
        )
    for branch in research.branches:
        if branch.status != "completed":
            limitations.append(
                f"The {branch.investigator.replace('_', ' ')} branch ended as '{branch.status}', "
                "so its evidence is partial."
            )
    untested = [n.need for n in needs if n.status == "untested"]
    if untested:
        limitations.append(f"Not tested by this study: {', '.join(untested)}.")
    if plan.conflicting_goals:
        limitations.append("Goals in tension: " + "; ".join(plan.conflicting_goals))
    if narrative is None:
        limitations.append(
            "The written interpretation could not be generated"
            + (f" ({narrative_error})" if narrative_error else "")
            + ". The computed comparison and selection are unaffected."
        )
    else:
        limitations.extend(text for text in narrative.limitations if text not in limitations)

    proposals = tuple(
        FollowUpProposal(
            proposal_id=f"FU{index}",
            kind=item.kind,
            title=item.title,
            description=item.description,
            rationale=item.rationale,
        )
        for index, item in enumerate(
            (narrative.follow_up_proposals if narrative else [])[:MAX_FOLLOW_UPS], start=1
        )
    )
    label = (
        "Development fixture output. Not simulation results."
        if is_fixture
        else "Simulation results for a modeled hearing profile under declared assumptions."
    )
    return StudyReport(
        study_id=package.study_id,
        parent_study_id=package.parent_study_id,
        result_kind=caps.kind,
        result_label=label,
        hearing_input=package.hearing_input,
        study_context=package.study_context,
        plan_hash=plan.plan_hash,
        evaluator_version=caps.evaluator_version,
        summary=narrative.summary if narrative else selection.explanation,
        candidates=summaries,
        selection=selection,
        selected_candidate_id=selection.selected_candidate_id,
        hypotheses=tuple(hypotheses),
        needs=needs,
        experiments_completed=len(records) - len(not_completed),
        experiments_not_completed=not_completed,
        limitations=tuple(limitations),
        inconclusive_findings=tuple(narrative.inconclusive_findings) if narrative else (),
        follow_up_proposals=proposals,
        narrative_source="model" if narrative else "unavailable",
    )
