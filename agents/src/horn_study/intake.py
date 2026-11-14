"""Profile intake: format and completeness validation of supplied inputs.

This checks whether the data a user supplied can be used by the evaluator.
It never judges whether a clinical result is correct, never fills gaps, and
never substitutes demo data, the other ear, or normal hearing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from horn_study.contracts import (
    EvaluatorCapabilities,
    EvaluatorHearingInput,
    HearingMeasurement,
    HearingProfile,
    InputIssue,
    NeedsProfile,
    PriorStudyContext,
    StartingPackage,
    StudyContext,
    StudyRequest,
)

DEFAULT_CONTEXT_NAME = "default_everyday_listening"
PERSONALIZED_CONTEXT_NAME = "user_supplied_needs"


class InputRejected(Exception):
    """The request cannot start a study. Carries every problem found."""

    def __init__(self, issues: list[InputIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{i.field}: {i.message}" for i in issues))


def normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def _normalize_needs(needs: NeedsProfile) -> NeedsProfile:
    def norm(values: tuple[str, ...]) -> tuple[str, ...]:
        seen: list[str] = []
        for value in values:
            token = normalize_token(value)
            if token and token not in seen:
                seen.append(token)
        return tuple(seen)

    return NeedsProfile(
        activities=norm(needs.activities),
        goals=norm(needs.goals),
        priorities=norm(needs.priorities),
        requirements=norm(needs.requirements),
        free_text=needs.free_text.strip(),
    )


def build_study_context(needs: NeedsProfile | None) -> StudyContext:
    """Keep the user's words next to the normalized form, or name the default."""
    if needs is None or needs.is_empty():
        empty = NeedsProfile()
        return StudyContext(name=DEFAULT_CONTEXT_NAME, is_default=True, needs=empty, normalized_needs=empty)
    return StudyContext(
        name=PERSONALIZED_CONTEXT_NAME,
        is_default=False,
        needs=needs,
        normalized_needs=_normalize_needs(needs),
    )


def parse_request(raw: Mapping[str, Any]) -> StudyRequest:
    """Parse a raw request, turning schema errors into actionable issues."""
    try:
        return StudyRequest.model_validate(raw)
    except ValidationError as exc:
        issues = [
            InputIssue(
                code=f"schema.{error['type']}",
                field=".".join(str(part) for part in error["loc"]) or "request",
                message=error["msg"],
            )
            for error in exc.errors()
        ]
        raise InputRejected(issues) from exc


def _resolve_profile(
    request: StudyRequest, capabilities: EvaluatorCapabilities, issues: list[InputIssue]
) -> HearingProfile | None:
    profile = request.hearing_profile
    if request.mode == "personalized":
        if request.demo_profile_id is not None:
            issues.append(
                InputIssue(
                    code="demo.not_selected",
                    field="demo_profile_id",
                    message=(
                        "A demo profile was referenced but mode is 'personalized'. "
                        "Demo data is only used when mode is explicitly 'demo'."
                    ),
                )
            )
        if profile is None:
            issues.append(
                InputIssue(
                    code="hearing.missing_profile",
                    field="hearing_profile",
                    message=(
                        "Personalized evaluation needs results from an existing hearing test. "
                        "Enter the thresholds from your report, or explicitly choose a demo profile."
                    ),
                )
            )
            return None
        if profile.source == "synthetic_demo":
            issues.append(
                InputIssue(
                    code="hearing.synthetic_in_personalized",
                    field="hearing_profile.source",
                    message=(
                        "Synthetic demo data cannot be used in personalized mode. "
                        "Supply existing test results or switch mode to 'demo'."
                    ),
                )
            )
            return None
        return profile

    # Demo mode: explicitly selected, always labeled synthetic.
    if profile is not None:
        if profile.source != "synthetic_demo":
            issues.append(
                InputIssue(
                    code="demo.source_mismatch",
                    field="hearing_profile.source",
                    message=(
                        "Demo mode only accepts profiles labeled 'synthetic_demo'. "
                        "Use mode 'personalized' for a user's own test results."
                    ),
                )
            )
            return None
        return profile
    if request.demo_profile_id is None:
        available = ", ".join(p.profile_id for p in capabilities.demo_profiles) or "none"
        issues.append(
            InputIssue(
                code="demo.no_profile",
                field="demo_profile_id",
                message=f"Demo mode needs a demo_profile_id. Available: {available}.",
            )
        )
        return None
    demo = next((p for p in capabilities.demo_profiles if p.profile_id == request.demo_profile_id), None)
    if demo is None:
        available = ", ".join(p.profile_id for p in capabilities.demo_profiles) or "none"
        issues.append(
            InputIssue(
                code="demo.unknown_profile",
                field="demo_profile_id",
                message=(
                    f"The evaluator does not declare a demo profile named "
                    f"'{request.demo_profile_id}'. Available: {available}."
                ),
            )
        )
        return None
    return HearingProfile(
        profile_id=demo.profile_id,
        source="synthetic_demo",
        target_ear=demo.target_ear,
        measurements=demo.measurements,
        user_notes="",
    )


def _freq_label(frequency_hz: float) -> str:
    return f"{frequency_hz:g} Hz"


def _check_hearing(
    profile: HearingProfile, capabilities: EvaluatorCapabilities, issues: list[InputIssue]
) -> tuple[tuple[HearingMeasurement, ...], tuple[HearingMeasurement, ...]]:
    """Return (measurements the evaluator will use, retained but unused)."""
    spec = capabilities.hearing_input
    ear = profile.target_ear
    supported = set(spec.supported_measurement_types)
    known_frequencies = set(spec.required_frequencies_hz) | set(spec.optional_frequencies_hz)

    used: list[HearingMeasurement] = []
    unused: list[HearingMeasurement] = []
    seen: dict[tuple[float, str], HearingMeasurement] = {}

    for index, m in enumerate(profile.measurements):
        field = f"hearing_profile.measurements.{index}"
        if m.ear != ear or m.measurement_type not in supported:
            unused.append(m)
            continue
        key = (m.frequency_hz, m.measurement_type)
        if key in seen:
            issues.append(
                InputIssue(
                    code="hearing.duplicate_measurement",
                    field=field,
                    message=(
                        f"More than one {m.measurement_type} value for the {ear} ear at "
                        f"{_freq_label(m.frequency_hz)}. Keep the one from your report."
                    ),
                )
            )
            continue
        seen[key] = m
        if m.frequency_hz not in known_frequencies and not spec.accepts_additional_frequencies:
            unused.append(m)
            continue
        if m.status == "measured":
            assert m.threshold_db_hl is not None
            if not spec.min_threshold_db_hl <= m.threshold_db_hl <= spec.max_threshold_db_hl:
                issues.append(
                    InputIssue(
                        code="hearing.threshold_out_of_range",
                        field=f"{field}.threshold_db_hl",
                        message=(
                            f"{m.threshold_db_hl:g} dB HL at {_freq_label(m.frequency_hz)} is "
                            f"outside the range the evaluator accepts "
                            f"({spec.min_threshold_db_hl:g} to {spec.max_threshold_db_hl:g} dB HL). "
                            "Check the value and its unit against your report."
                        ),
                    )
                )
                continue
            used.append(m)
        elif m.status == "no_response" and spec.accepts_no_response:
            used.append(m)
        else:
            unused.append(m)

    usable = {m.frequency_hz for m in used}
    for frequency in spec.required_frequencies_hz:
        if frequency in usable:
            continue
        marker = next(
            (
                m
                for m in profile.measurements
                if m.ear == ear
                and m.frequency_hz == frequency
                and m.measurement_type in supported
                and m.status != "measured"
            ),
            None,
        )
        types = " or ".join(t.replace("_", " ") for t in spec.supported_measurement_types)
        if marker is not None:
            message = (
                f"The {ear} ear value at {_freq_label(frequency)} is marked "
                f"'{marker.status}', and the evaluator needs a measured {types} threshold there. "
                "It was not replaced with a number."
            )
            code = "hearing.required_frequency_unusable"
        else:
            message = (
                f"Missing the {ear} ear {types} threshold at {_freq_label(frequency)}. "
                "Enter it from your existing test results."
            )
            code = "hearing.required_frequency_missing"
        issues.append(InputIssue(code=code, field="hearing_profile.measurements", message=message))

    return tuple(used), tuple(unused)


def validate_request(
    request: StudyRequest,
    capabilities: EvaluatorCapabilities,
    prior_study: PriorStudyContext | None = None,
) -> StartingPackage:
    """Check a request against the evaluator's declared inputs.

    Raises InputRejected listing every problem. On success returns the
    immutable package shared by all investigators and the coordinator.
    """
    issues: list[InputIssue] = []

    if capabilities.kind != request.evaluation_mode:
        issues.append(
            InputIssue(
                code="evaluation.mode_mismatch",
                field="evaluation_mode",
                message=(
                    f"The request asks for '{request.evaluation_mode}' evaluation but the "
                    f"configured evaluator is '{capabilities.kind}'."
                ),
            )
        )

    if capabilities.requires_ear_mesh and not request.anatomy.ear_mesh_ref:
        issues.append(
            InputIssue(
                code="anatomy.mesh_required",
                field="anatomy.ear_mesh_ref",
                message="This evaluator needs an ear model reference and none was supplied.",
            )
        )

    if request.parent_study_id and prior_study is None:
        issues.append(
            InputIssue(
                code="follow_up.parent_not_found",
                field="parent_study_id",
                message=f"No saved study named '{request.parent_study_id}' was found.",
            )
        )

    profile = _resolve_profile(request, capabilities, issues)
    used: tuple[HearingMeasurement, ...] = ()
    unused: tuple[HearingMeasurement, ...] = ()
    if profile is not None:
        used, unused = _check_hearing(profile, capabilities, issues)

    if issues or profile is None:
        raise InputRejected(issues)

    hearing_input = EvaluatorHearingInput(
        profile_id=profile.profile_id,
        source=profile.source,
        target_ear=profile.target_ear,
        tested_on=profile.tested_on,
        original_report_ref=profile.original_report_ref,
        measurements=used,
        retained_but_unused=unused,
        development_fixture_label=request.development_fixture_label,
    )
    return StartingPackage(
        study_id=request.study_id,
        parent_study_id=request.parent_study_id,
        mode=request.mode,
        evaluation_mode=request.evaluation_mode,
        hearing_input=hearing_input,
        anatomy=request.anatomy,
        study_context=build_study_context(request.needs_profile),
        capabilities=capabilities,
        budget=request.budget,
        prior_study=prior_study,
    )


def user_needs(context: StudyContext) -> tuple[str, ...]:
    """Every structured need the plan must account for, in normalized form."""
    needs = context.normalized_needs
    ordered: list[str] = []
    for value in (*needs.activities, *needs.goals, *needs.priorities, *needs.requirements):
        if value not in ordered:
            ordered.append(value)
    return tuple(ordered)
