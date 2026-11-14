"""Typed application contracts for a study.

These models are the boundary between the agent workflow, the evaluator owner,
and the frontend. Three kinds of data are kept apart on purpose:

- hearing input: measurements the user supplied from an existing test (or an
  explicitly selected synthetic demo profile),
- needs: what the user wants, in their own words,
- modeled conditions: what the evaluator actually computes.

Nothing in this module conducts a hearing test or derives a diagnosis.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1"

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$"

Ear = Literal["left", "right"]
MeasurementType = Literal["air_conduction", "bone_conduction", "other"]
MeasurementStatus = Literal["measured", "no_response", "missing", "unreadable"]
HearingSource = Literal["user_entered_test_results", "uploaded_test_report", "synthetic_demo"]
StudyMode = Literal["personalized", "demo"]
EvaluationMode = Literal["development_fixture", "real"]
ParameterValue = float | str


def canonical_json(value: Any) -> str:
    """Serialize deterministically so hashes are stable across runs."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class Contract(BaseModel):
    """Strict, immutable base for contracts this workstream authors."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExternalContract(BaseModel):
    """Immutable base for data authored by the evaluator owner.

    Unknown fields are preserved rather than dropped, so a newer evaluator can
    return more than this workstream understands without losing data.
    """

    model_config = ConfigDict(extra="allow", frozen=True)


# --------------------------------------------------------------------------
# Study request
# --------------------------------------------------------------------------


class HearingMeasurement(Contract):
    """One value from an existing hearing test, exactly as supplied."""

    ear: Ear
    frequency_hz: float = Field(gt=0)
    threshold_db_hl: float | None = None
    measurement_type: MeasurementType = "air_conduction"
    reported_type: str | None = Field(
        default=None, description="Original test label when measurement_type is 'other'."
    )
    status: MeasurementStatus = "measured"
    no_response_at_db_hl: float | None = Field(
        default=None,
        description="Highest level presented without a response. Not a threshold.",
    )
    extraction_confidence: float | None = Field(
        default=None, ge=0, le=1, description="Only for values read from an uploaded report."
    )
    note: str | None = None

    @model_validator(mode="after")
    def _status_matches_value(self) -> HearingMeasurement:
        if self.status == "measured" and self.threshold_db_hl is None:
            raise ValueError("a 'measured' value needs threshold_db_hl")
        if self.status != "measured" and self.threshold_db_hl is not None:
            raise ValueError(
                f"status '{self.status}' cannot carry a numeric threshold; "
                "keep the marker and leave threshold_db_hl empty"
            )
        return self


class HearingProfile(Contract):
    profile_id: str = Field(pattern=ID_PATTERN)
    source: HearingSource
    target_ear: Ear
    tested_on: date | None = None
    original_report_ref: str | None = None
    measurements: tuple[HearingMeasurement, ...] = ()
    user_notes: str = ""
    clinician_notes: str = Field(
        default="",
        description="Existing clinician-provided information, retained as context only.",
    )


class Anatomy(Contract):
    ear_mesh_ref: str | None = None
    source: str = "not_supplied"
    units: str | None = None
    assumptions: tuple[str, ...] = ()


class NeedsProfile(Contract):
    activities: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    priorities: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    free_text: str = ""

    def is_empty(self) -> bool:
        return not (
            self.activities or self.goals or self.priorities or self.requirements or self.free_text.strip()
        )


class Budget(Contract):
    max_evaluation_cases: int = Field(default=12, ge=1, le=500)
    max_parallel_evaluations: int = Field(default=2, ge=1, le=32)
    max_research_tool_calls_per_agent: int = Field(default=6, ge=1, le=40)
    max_attempts_per_experiment: int = Field(default=2, ge=1, le=5)
    max_plan_revisions: int = Field(default=2, ge=0, le=5)
    max_run_seconds: float = Field(default=1800, gt=0, le=6 * 3600)


StartAction = Literal["start_study", "refine_design", "run_follow_up", "compare_use_case"]


class StartRequest(Contract):
    """The explicit user action that authorizes this one study."""

    initiated_by: Literal["user"]
    action: StartAction = "start_study"
    follow_up_proposal_id: str | None = None
    requested_at: datetime | None = None


class StudyRequest(Contract):
    schema_version: Literal["1"] = SCHEMA_VERSION
    study_id: str = Field(pattern=ID_PATTERN)
    parent_study_id: str | None = Field(default=None, pattern=ID_PATTERN)
    mode: StudyMode
    evaluation_mode: EvaluationMode
    start: StartRequest
    hearing_profile: HearingProfile | None = None
    demo_profile_id: str | None = Field(
        default=None,
        description="Synthetic profile declared by the evaluator. Demo mode only.",
    )
    anatomy: Anatomy = Anatomy()
    needs_profile: NeedsProfile | None = None
    budget: Budget = Budget()
    development_fixture_label: str | None = Field(
        default=None,
        description="Set when the request itself is a development fixture, not a user's data.",
    )


# --------------------------------------------------------------------------
# Evaluator capability contract (authored by the evaluator owner)
# --------------------------------------------------------------------------


class ParameterSpec(ExternalContract):
    name: str
    kind: Literal["float", "int", "choice"] = "float"
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    description: str = ""


class GeometryFamily(ExternalContract):
    family_id: str
    description: str = ""
    parameters: tuple[ParameterSpec, ...]


class BaselineCondition(ExternalContract):
    baseline_id: str
    kind: Literal["unaided", "generic_device"]
    description: str = ""


class HearingInputSpec(ExternalContract):
    supported_measurement_types: tuple[MeasurementType, ...]
    required_frequencies_hz: tuple[float, ...]
    optional_frequencies_hz: tuple[float, ...] = ()
    accepts_additional_frequencies: bool = False
    frequency_unit: Literal["Hz"] = "Hz"
    threshold_unit: Literal["dB HL"] = "dB HL"
    min_threshold_db_hl: float = -10
    max_threshold_db_hl: float = 120
    accepts_no_response: bool = False
    missing_data_rule: str = ""


class DemoProfile(ExternalContract):
    profile_id: str
    description: str = ""
    target_ear: Ear
    measurements: tuple[HearingMeasurement, ...]


class ScenarioSpec(ExternalContract):
    scenario_id: str
    description: str = ""
    source_level_db_spl: float | None = None
    tags: tuple[str, ...] = ()


class MetricSpec(ExternalContract):
    name: str
    unit: str
    direction: Literal["higher_is_better", "lower_is_better"]
    description: str = ""


class CanalConfig(ExternalContract):
    canal_config_id: str
    description: str = ""
    is_default: bool = False


class CalibrationConvention(ExternalContract):
    calibration_ref: str
    description: str = ""
    source_level_convention: str = ""
    normalization: str = ""


class UnsupportedRequirement(ExternalContract):
    requirement: str
    reason: str = ""


class Reference(ExternalContract):
    title: str
    url: str
    note: str = ""


class EvaluatorCapabilities(ExternalContract):
    evaluator_name: str
    evaluator_version: str
    kind: EvaluationMode
    model_description: str = ""
    geometry_families: tuple[GeometryFamily, ...]
    baselines: tuple[BaselineCondition, ...] = ()
    hearing_input: HearingInputSpec
    demo_profiles: tuple[DemoProfile, ...] = ()
    scenarios: tuple[ScenarioSpec, ...]
    metrics: tuple[MetricSpec, ...]
    canal_configurations: tuple[CanalConfig, ...] = ()
    requires_ear_mesh: bool = False
    calibration: CalibrationConvention
    supports_seeds: bool = False
    max_repetitions: int = 1
    fidelity_levels: tuple[str, ...] = ("default",)
    default_fidelity: str = "default"
    output_assets: tuple[str, ...] = ()
    unsupported_requirements: tuple[UnsupportedRequirement, ...] = ()
    references: tuple[Reference, ...] = ()

    def snapshot_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    def metric(self, name: str) -> MetricSpec | None:
        return next((m for m in self.metrics if m.name == name), None)

    def family(self, family_id: str) -> GeometryFamily | None:
        return next((f for f in self.geometry_families if f.family_id == family_id), None)

    def baseline(self, baseline_id: str) -> BaselineCondition | None:
        return next((b for b in self.baselines if b.baseline_id == baseline_id), None)

    def default_canal_config_id(self) -> str | None:
        for canal in self.canal_configurations:
            if canal.is_default:
                return canal.canal_config_id
        return self.canal_configurations[0].canal_config_id if self.canal_configurations else None


# --------------------------------------------------------------------------
# Validated inputs handed to research, planning, and evaluation
# --------------------------------------------------------------------------


class EvaluatorHearingInput(Contract):
    """The supplied measurements the evaluator will use, unmodified.

    Only target-ear values of a supported measurement type are included.
    Nothing is interpolated, copied from the other ear, or filled in.
    """

    profile_id: str
    source: HearingSource
    target_ear: Ear
    tested_on: date | None = None
    original_report_ref: str | None = None
    measurements: tuple[HearingMeasurement, ...]
    retained_but_unused: tuple[HearingMeasurement, ...] = ()
    development_fixture_label: str | None = None


class StudyContext(Contract):
    """How the user's needs enter the study. A default is always named as one."""

    name: str
    is_default: bool
    needs: NeedsProfile
    normalized_needs: NeedsProfile


class PriorStudyContext(Contract):
    """Read-only summary of the parent study for a user-requested follow-up."""

    parent_study_id: str
    follow_up_proposal: dict[str, Any] | None = None
    selected_candidate_id: str | None = None
    selected_candidate: dict[str, Any] | None = None
    hypothesis_verdicts: tuple[dict[str, Any], ...] = ()
    summary: str = ""


class StartingPackage(Contract):
    """The immutable context every investigator and the coordinator receive."""

    study_id: str
    parent_study_id: str | None
    mode: StudyMode
    evaluation_mode: EvaluationMode
    hearing_input: EvaluatorHearingInput
    anatomy: Anatomy
    study_context: StudyContext
    capabilities: EvaluatorCapabilities
    budget: Budget
    prior_study: PriorStudyContext | None = None


class InputIssue(Contract):
    code: str
    field: str
    message: str


# --------------------------------------------------------------------------
# Research
# --------------------------------------------------------------------------

InvestigatorName = Literal["hearing_research", "use_context_research", "acoustic_design_research"]


class SourceRecord(Contract):
    source_id: str
    url: str
    final_url: str
    title: str
    content_type: str
    retrieved_at: datetime
    content_sha256: str
    char_count: int
    first_read_by: InvestigatorName


class ResearchFinding(Contract):
    finding_id: str
    investigator: InvestigatorName
    question: str
    source_id: str
    source_url: str
    source_title: str
    claim: str
    evidence_passage: str = Field(description="Verbatim excerpt, verified against the read text.")
    applicability: str
    limitations: str
    related_user_goal: str
    motivates: str


class SuggestedHypothesis(BaseModel):
    statement: str
    supporting_finding_ids: list[str] = Field(default_factory=list)
    suggested_comparison: str = ""


class InvestigatorOutput(BaseModel):
    """Structured final answer of one investigator (produced by the model)."""

    summary: str
    candidate_hypotheses: list[SuggestedHypothesis] = Field(default_factory=list)
    suggested_scenario_ids: list[str] = Field(default_factory=list)
    suggested_metric_names: list[str] = Field(default_factory=list)
    suggested_comparisons: list[str] = Field(default_factory=list)
    model_limitations: list[str] = Field(default_factory=list)
    untested_needs: list[str] = Field(default_factory=list)
    conflicting_goals: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    future_work: list[str] = Field(default_factory=list)


class BranchResult(Contract):
    investigator: InvestigatorName
    status: Literal["completed", "incomplete", "failed"]
    started_at: datetime
    ended_at: datetime
    output: InvestigatorOutput | None = None
    finding_ids: tuple[str, ...] = ()
    research_tool_calls: int = 0
    rejected_findings: int = 0
    error: str | None = None


class ResearchRecord(Contract):
    """Everything the research phase produced (research.json)."""

    study_id: str
    branches: tuple[BranchResult, ...]
    findings: tuple[ResearchFinding, ...]
    sources: tuple[SourceRecord, ...]


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------


class Candidate(Contract):
    candidate_id: str = Field(pattern=ID_PATTERN)
    kind: Literal["design", "baseline"]
    family_id: str | None = None
    baseline_id: str | None = None
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)
    label: str = ""
    rationale: str = ""


class Hypothesis(Contract):
    hypothesis_id: str = Field(pattern=ID_PATTERN)
    statement: str
    supporting_finding_ids: tuple[str, ...]
    user_goals: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...]
    metric: str
    varied_parameter: str | None = None
    scenario_ids: tuple[str, ...]
    supports_if: str
    contradicts_if: str


class NeedCoverage(Contract):
    need: str
    classification: Literal["modeled", "untested"]
    scenario_ids: tuple[str, ...] = ()
    metric_names: tuple[str, ...] = ()
    explanation: str = ""


class MetricConstraint(Contract):
    metric: str
    bound: Literal["max", "min"]
    value: float


class SelectionRule(Contract):
    """Fixed before execution. Applied in code, never by a model."""

    primary_metric: str
    direction: Literal["higher_is_better", "lower_is_better"]
    aggregation: Literal["mean_over_cases"] = "mean_over_cases"
    reference_candidate_id: str
    minimum_improvement: float = Field(default=0.0, ge=0)
    tie_breaker_metrics: tuple[str, ...] = ()
    constraints: tuple[MetricConstraint, ...] = ()
    require_all_cases_completed: Literal[True] = True


class ExperimentSpec(Contract):
    """One evaluation case for one candidate."""

    study_id: str
    experiment_id: str
    candidate_id: str
    candidate_kind: Literal["design", "baseline"]
    family_id: str | None = None
    baseline_id: str | None = None
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)
    hearing_input: EvaluatorHearingInput
    scenario_id: str
    canal_config_id: str | None = None
    ear_mesh_ref: str | None = None
    seed: int | None = None
    fidelity: str
    calibration_ref: str

    def spec_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    def evaluation_key(self) -> str:
        """Hash of what is computed, without study-specific identifiers.

        Two specs with the same key ask the evaluator the same question, so a
        completed result can be reused.
        """
        payload = self.model_dump(mode="json", exclude={"study_id", "experiment_id", "candidate_id"})
        return content_hash(payload)


class CapabilitySnapshot(Contract):
    evaluator_name: str
    evaluator_version: str
    kind: EvaluationMode
    capabilities_hash: str


class StudyPlan(Contract):
    study_id: str
    plan_version: int
    capability_snapshot: CapabilitySnapshot
    study_context_name: str
    rationale: str
    hypotheses: tuple[Hypothesis, ...]
    candidates: tuple[Candidate, ...]
    experiments: tuple[ExperimentSpec, ...]
    scenario_ids: tuple[str, ...]
    canal_config_ids: tuple[str | None, ...]
    seeds: tuple[int | None, ...]
    fidelity: str
    calibration_ref: str
    metric_names: tuple[str, ...]
    selection_rule: SelectionRule
    needs_coverage: tuple[NeedCoverage, ...]
    conflicting_goals: tuple[str, ...] = ()
    future_work: tuple[str, ...] = ()
    plan_hash: str = ""
    frozen_at: datetime | None = None

    def compute_hash(self) -> str:
        return content_hash(self.model_dump(mode="json", exclude={"plan_hash", "frozen_at"}))

    def candidate(self, candidate_id: str) -> Candidate | None:
        return next((c for c in self.candidates if c.candidate_id == candidate_id), None)

    @property
    def is_frozen(self) -> bool:
        return bool(self.plan_hash) and self.frozen_at is not None


# --------------------------------------------------------------------------
# Results (authored by the evaluator) and execution records (authored here)
# --------------------------------------------------------------------------


class MetricValue(ExternalContract):
    name: str
    value: float
    unit: str


class AssetRef(ExternalContract):
    kind: str
    ref: str
    description: str = ""


class ErrorInfo(ExternalContract):
    code: str
    message: str
    transient: bool = False


class ResultProvenance(ExternalContract):
    kind: EvaluationMode
    evaluator_name: str
    evaluator_version: str
    produced_at: datetime | None = None
    notes: str = ""


class ExperimentResult(ExternalContract):
    """What the evaluator returned for one spec. Never edited after receipt."""

    candidate_id: str
    experiment_id: str
    spec_hash: str
    status: Literal["completed", "failed", "unsupported"]
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)
    evaluation_config: dict[str, Any] = Field(default_factory=dict)
    metrics: tuple[MetricValue, ...] = ()
    assets: tuple[AssetRef, ...] = ()
    evaluator_version: str
    seed: int | None = None
    runtime_seconds: float | None = None
    provenance: ResultProvenance
    error: ErrorInfo | None = None


AttemptOutcome = Literal["completed", "failed", "unsupported", "transient_error", "error", "invalid"]


class AttemptRecord(Contract):
    attempt: int
    started_at: datetime
    ended_at: datetime
    outcome: AttemptOutcome
    error: str | None = None


ExperimentOutcome = Literal["completed", "failed", "unsupported", "invalid"]


class ExperimentRecord(Contract):
    """Bookkeeping around one frozen spec: attempts, cache use, and the raw result."""

    experiment_id: str
    candidate_id: str
    spec_hash: str
    outcome: ExperimentOutcome
    result: ExperimentResult | None = None
    attempts: tuple[AttemptRecord, ...] = ()
    cache_hit: bool = False
    issues: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


class MetricAggregate(Contract):
    name: str
    unit: str
    mean: float
    minimum: float
    maximum: float
    n_cases: int


class CandidateSummary(Contract):
    candidate_id: str
    kind: Literal["design", "baseline"]
    label: str
    n_planned: int
    n_completed: int
    all_cases_completed: bool
    metrics: tuple[MetricAggregate, ...] = ()
    primary_metric_mean: float | None = None
    improvement_over_reference: float | None = Field(
        default=None,
        description="Signed so that positive means better than the reference control.",
    )
    eligible: bool = False
    ineligibility_reasons: tuple[str, ...] = ()
    rank: int | None = None


class Selection(Contract):
    selected_candidate_id: str | None
    reason_code: Literal[
        "selected",
        "no_eligible_candidate",
        "reference_incomplete",
        "tie",
    ]
    explanation: str


class HypothesisDataPoint(Contract):
    candidate_id: str
    varied_parameter_value: ParameterValue | None = None
    mean: float | None = None
    n_completed: int
    n_planned: int


class HypothesisOutcome(Contract):
    hypothesis_id: str
    metric: str
    unit: str
    data: tuple[HypothesisDataPoint, ...]
    data_complete: bool
    verdict: Literal["supported", "contradicted", "inconclusive"]
    explanation: str


class NeedOutcome(Contract):
    need: str
    status: Literal["addressed", "evaluated_unsuccessfully", "untested"]
    explanation: str


class FollowUpProposal(Contract):
    """Report content only. It has no authority to start anything."""

    proposal_id: str
    kind: Literal["refine_design", "run_follow_up", "compare_use_case"]
    title: str
    description: str
    rationale: str


class StudyReport(Contract):
    study_id: str
    parent_study_id: str | None
    result_kind: EvaluationMode
    result_label: str
    hearing_input: EvaluatorHearingInput
    study_context: StudyContext
    plan_hash: str
    evaluator_version: str
    summary: str
    candidates: tuple[CandidateSummary, ...]
    selection: Selection
    selected_candidate_id: str | None
    hypotheses: tuple[HypothesisOutcome, ...]
    needs: tuple[NeedOutcome, ...]
    experiments_completed: int
    experiments_not_completed: tuple[str, ...]
    limitations: tuple[str, ...]
    inconclusive_findings: tuple[str, ...]
    follow_up_proposals: tuple[FollowUpProposal, ...]
    narrative_source: Literal["model", "unavailable"]


# --------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------


class StudyState(StrEnum):
    CREATED = "CREATED"
    RESEARCHING = "RESEARCHING"
    PLANNING = "PLANNING"
    PLAN_FROZEN = "PLAN_FROZEN"
    EVALUATING = "EVALUATING"
    INTERPRETING = "INTERPRETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({StudyState.COMPLETED, StudyState.FAILED, StudyState.CANCELLED})

_FORWARD: dict[StudyState, StudyState] = {
    StudyState.CREATED: StudyState.RESEARCHING,
    StudyState.RESEARCHING: StudyState.PLANNING,
    StudyState.PLANNING: StudyState.PLAN_FROZEN,
    StudyState.PLAN_FROZEN: StudyState.EVALUATING,
    StudyState.EVALUATING: StudyState.INTERPRETING,
    StudyState.INTERPRETING: StudyState.COMPLETED,
}


def allowed_transitions(state: StudyState) -> frozenset[StudyState]:
    """The only moves a study can make. There is no way back to an earlier phase."""
    if state in TERMINAL_STATES:
        return frozenset()
    return frozenset({_FORWARD[state], StudyState.FAILED, StudyState.CANCELLED})
