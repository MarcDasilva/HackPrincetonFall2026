"""The evaluator boundary.

Everything numerical lives behind two calls:

    get_evaluator_capabilities() -> EvaluatorCapabilities
    evaluate_experiment(spec: ExperimentSpec) -> ExperimentResult

The adapter passes specs through and returns results exactly as produced.
It does not normalize levels, rescale metrics, or fill in missing values.
The amplitude and calibration convention is the evaluator owner's to define.
"""

from __future__ import annotations

import hashlib
import importlib
import math
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from horn_study.contracts import (
    AssetRef,
    BaselineCondition,
    CalibrationConvention,
    CanalConfig,
    DemoProfile,
    ErrorInfo,
    EvaluationMode,
    EvaluatorCapabilities,
    ExperimentResult,
    ExperimentSpec,
    GeometryFamily,
    HearingInputSpec,
    HearingMeasurement,
    MetricSpec,
    MetricValue,
    ParameterSpec,
    Reference,
    ResultProvenance,
    ScenarioSpec,
    UnsupportedRequirement,
)

REAL_EVALUATOR_ENV = "HORN_STUDY_REAL_EVALUATOR"


class TransientEvaluatorError(Exception):
    """An operational failure worth retrying with the identical spec."""


@runtime_checkable
class Evaluator(Protocol):
    def get_evaluator_capabilities(self) -> EvaluatorCapabilities: ...

    def evaluate_experiment(self, spec: ExperimentSpec) -> ExperimentResult: ...


class EvaluatorNotConfigured(Exception):
    pass


# --------------------------------------------------------------------------
# Real evaluator: a thin wrapper around the numerical owner's code
# --------------------------------------------------------------------------


class CallableEvaluator:
    """Wraps two plain functions that speak JSON-compatible dicts or contract models.

    This is the seam for the real acoustic and auditory evaluator.
    The functions may accept and return dicts so the numerical code does not
    have to import this package.
    """

    def __init__(
        self,
        get_capabilities: Callable[[], Any],
        evaluate: Callable[[dict[str, Any]], Any],
    ) -> None:
        self._get_capabilities = get_capabilities
        self._evaluate = evaluate

    def get_evaluator_capabilities(self) -> EvaluatorCapabilities:
        return EvaluatorCapabilities.model_validate(_as_plain(self._get_capabilities()))

    def evaluate_experiment(self, spec: ExperimentSpec) -> ExperimentResult:
        payload = spec.model_dump(mode="json")
        payload["spec_hash"] = spec.spec_hash()
        return ExperimentResult.model_validate(_as_plain(self._evaluate(payload)))


def _as_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def load_evaluator(path: str) -> Evaluator:
    """Load the real evaluator from 'package.module:attribute'.

    The attribute (or the module itself when no attribute is given) must expose
    `get_evaluator_capabilities()` and `evaluate_experiment(spec)`.
    A class or zero-argument factory is called once to obtain that object.
    `evaluate_experiment` receives the spec as a JSON-compatible dict that also
    carries `spec_hash`, and may return a dict or an ExperimentResult.
    """
    module_name, _, attribute = path.partition(":")
    if not module_name:
        raise EvaluatorNotConfigured(f"'{path}' is not of the form 'package.module:attribute'")
    try:
        module = importlib.import_module(module_name)
        loaded: Any = getattr(module, attribute) if attribute else module
    except (ImportError, AttributeError) as exc:
        raise EvaluatorNotConfigured(f"Could not load the evaluator at '{path}': {exc}") from exc
    is_factory = isinstance(loaded, type) or (callable(loaded) and not hasattr(loaded, "evaluate_experiment"))
    target: Any = loaded() if is_factory else loaded
    if not (hasattr(target, "get_evaluator_capabilities") and hasattr(target, "evaluate_experiment")):
        raise EvaluatorNotConfigured(
            f"'{path}' does not provide get_evaluator_capabilities and evaluate_experiment"
        )
    return CallableEvaluator(target.get_evaluator_capabilities, target.evaluate_experiment)


def evaluator_for(mode: EvaluationMode, env: Mapping[str, str] | None = None) -> Evaluator:
    """Resolve the evaluator a request asked for. Never falls back silently."""
    if mode == "development_fixture":
        return DevelopmentFixtureEvaluator()
    path = (env if env is not None else os.environ).get(REAL_EVALUATOR_ENV)
    if not path:
        raise EvaluatorNotConfigured(
            f"evaluation_mode 'real' needs {REAL_EVALUATOR_ENV}='package.module:attribute' "
            "pointing at the real evaluator. No real evaluator is configured."
        )
    return load_evaluator(path)


# --------------------------------------------------------------------------
# Development fixture: NOT a simulation
# --------------------------------------------------------------------------

FIXTURE_NAME = "horn-study-development-fixture"
FIXTURE_VERSION = "fixture-0.1"
FIXTURE_NOTICE = (
    "DEVELOPMENT FIXTURE. These numbers come from a placeholder formula used to exercise "
    "the workflow. They are not acoustic or auditory simulation results and support no "
    "scientific or clinical claim."
)

_FIXTURE_FREQUENCIES = (500.0, 1000.0, 2000.0, 4000.0)


def _fixture_capabilities() -> EvaluatorCapabilities:
    length = ParameterSpec(
        name="length_mm",
        kind="float",
        unit="mm",
        minimum=20,
        maximum=120,
        description="Acoustic path length of the horn.",
    )
    throat = ParameterSpec(
        name="throat_diameter_mm",
        kind="float",
        unit="mm",
        minimum=2,
        maximum=8,
        description="Diameter at the canal end.",
    )
    return EvaluatorCapabilities(
        evaluator_name=FIXTURE_NAME,
        evaluator_version=FIXTURE_VERSION,
        kind="development_fixture",
        model_description=FIXTURE_NOTICE,
        geometry_families=(
            GeometryFamily(
                family_id="conical_horn_fixture",
                description="Placeholder straight-walled horn family.",
                parameters=(
                    length,
                    throat,
                    ParameterSpec(
                        name="mouth_diameter_mm",
                        kind="float",
                        unit="mm",
                        minimum=10,
                        maximum=60,
                        description="Diameter at the open end.",
                    ),
                ),
            ),
            GeometryFamily(
                family_id="exponential_horn_fixture",
                description="Placeholder exponentially flared horn family.",
                parameters=(
                    length,
                    throat,
                    ParameterSpec(
                        name="flare_rate_per_m",
                        kind="float",
                        unit="1/m",
                        minimum=10,
                        maximum=120,
                        description="Exponential flare constant.",
                    ),
                ),
            ),
        ),
        baselines=(
            BaselineCondition(baseline_id="unaided", kind="unaided", description="No device. The control."),
            BaselineCondition(
                baseline_id="generic_device",
                kind="generic_device",
                description="A fixed, non-personalized placeholder device.",
            ),
        ),
        hearing_input=HearingInputSpec(
            supported_measurement_types=("air_conduction",),
            required_frequencies_hz=_FIXTURE_FREQUENCIES,
            optional_frequencies_hz=(250.0, 3000.0, 6000.0, 8000.0),
            min_threshold_db_hl=-10,
            max_threshold_db_hl=120,
            accepts_no_response=False,
            missing_data_rule=(
                "Measured air-conduction thresholds for the target ear are required at "
                "500, 1000, 2000, and 4000 Hz. Values marked no_response, missing, or "
                "unreadable are not accepted at required frequencies and are never "
                "replaced with numbers. Optional frequencies may be absent."
            ),
        ),
        demo_profiles=(
            DemoProfile(
                profile_id="demo_sloping_high_frequency",
                description="Synthetic sloping profile for demos. Not a real person's data.",
                target_ear="right",
                measurements=tuple(
                    HearingMeasurement(ear="right", frequency_hz=f, threshold_db_hl=t)
                    for f, t in (
                        (250, 15),
                        (500, 20),
                        (1000, 30),
                        (2000, 45),
                        (4000, 55),
                        (8000, 50),
                    )
                ),
            ),
        ),
        scenarios=(
            ScenarioSpec(
                scenario_id="quiet_conversation",
                description="One talker at conversational level in quiet.",
                source_level_db_spl=60,
                tags=("speech", "quiet"),
            ),
            ScenarioSpec(
                scenario_id="speech_in_babble",
                description="One talker with several competing talkers.",
                source_level_db_spl=65,
                tags=("speech", "noise", "restaurant", "classroom"),
            ),
            ScenarioSpec(
                scenario_id="distant_talker",
                description="One talker at a distance, lower level at the ear.",
                source_level_db_spl=50,
                tags=("speech", "distance", "coach", "lecture"),
            ),
        ),
        metrics=(
            MetricSpec(
                name="fixture_audible_speech_fraction",
                unit="fraction",
                direction="higher_is_better",
                description="Placeholder share of the speech band above the modeled threshold.",
            ),
            MetricSpec(
                name="fixture_target_band_gain_db",
                unit="dB",
                direction="higher_is_better",
                description="Placeholder gain weighted toward frequencies with higher thresholds.",
            ),
            MetricSpec(
                name="fixture_device_length_mm",
                unit="mm",
                direction="lower_is_better",
                description="Length of the candidate. Zero for the unaided control.",
            ),
        ),
        canal_configurations=(
            CanalConfig(canal_config_id="default_canal", description="Permitted default.", is_default=True),
            CanalConfig(canal_config_id="short_canal", description="Shorter placeholder canal."),
        ),
        requires_ear_mesh=False,
        calibration=CalibrationConvention(
            calibration_ref="fixture-cal-v1",
            description="Levels are dB SPL at the horn mouth.",
            source_level_convention="Each scenario declares its own source level.",
            normalization="None. Outputs are not level-normalized per stimulus.",
        ),
        supports_seeds=True,
        max_repetitions=3,
        fidelity_levels=("fixture",),
        default_fidelity="fixture",
        output_assets=("response_curve",),
        unsupported_requirements=(
            UnsupportedRequirement(requirement="secure_retention", reason="No mechanical or fit model."),
            UnsupportedRequirement(requirement="comfort", reason="No comfort model."),
            UnsupportedRequirement(requirement="glasses_compatibility", reason="No packaging model."),
            UnsupportedRequirement(requirement="easy_removal", reason="No handling model."),
            UnsupportedRequirement(
                requirement="hearing_protection", reason="Attenuation is not modeled or validated."
            ),
            UnsupportedRequirement(requirement="music_quality", reason="No music quality metric."),
        ),
        references=(
            Reference(
                title="brucezilany package documentation",
                url="https://pypi.org/project/brucezilany/",
                note="Auditory model and stimulus-loading behavior planned for the real evaluator.",
            ),
            Reference(
                title="Human Audiometric Thresholds do not Predict Specific Cellular Damage in the Inner Ear",
                url="https://pmc.ncbi.nlm.nih.gov/articles/PMC5970796/",
                note="Limits of audiogram-based cellular inference.",
            ),
            Reference(
                title="Chen et al., 2005",
                url="https://pubmed.ncbi.nlm.nih.gov/16212766/",
                note="Prior model-based hearing-compensation optimization.",
            ),
        ),
    )


def _unit_noise(*parts: Any) -> float:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 - 0.5


class DevelopmentFixtureEvaluator:
    """Deterministic stand-in with the same contract as the real evaluator.

    It exists so research, planning, execution, and reporting can be built and
    tested before the numerical packages are ready. Every result is labeled
    'development_fixture'.
    """

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self._capabilities = _fixture_capabilities()
        self._delay_seconds = delay_seconds

    def get_evaluator_capabilities(self) -> EvaluatorCapabilities:
        return self._capabilities

    def evaluate_experiment(self, spec: ExperimentSpec) -> ExperimentResult:
        started = time.perf_counter()
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        problem = self._unsupported_reason(spec)
        if problem is not None:
            return self._result(spec, started, status="unsupported", error=problem)

        thresholds = {
            m.frequency_hz: m.threshold_db_hl
            for m in spec.hearing_input.measurements
            if m.threshold_db_hl is not None
        }
        scenario = next(s for s in self._capabilities.scenarios if s.scenario_id == spec.scenario_id)
        source_level = scenario.source_level_db_spl or 60.0
        masking = 8.0 if "noise" in scenario.tags else 0.0
        canal_shift = 0.92 if spec.canal_config_id == "short_canal" else 1.0

        gains = {f: self._gain_db(spec, f * canal_shift) for f in _FIXTURE_FREQUENCIES}
        audible: list[float] = []
        for frequency in _FIXTURE_FREQUENCIES:
            margin = source_level + gains[frequency] - (thresholds[frequency] + 25.0 + masking)
            audible.append(min(1.0, max(0.0, 0.5 + margin / 30.0)))
        weights = [max(thresholds[f], 5.0) for f in _FIXTURE_FREQUENCIES]
        band_gain = sum(gains[f] * w for f, w in zip(_FIXTURE_FREQUENCIES, weights, strict=True)) / sum(
            weights
        )

        jitter = _unit_noise(spec.evaluation_key(), spec.seed) if spec.seed is not None else 0.0
        fraction = min(1.0, max(0.0, sum(audible) / len(audible) + 0.01 * jitter))
        length = float(spec.parameters.get("length_mm", 0.0)) if spec.candidate_kind == "design" else 0.0
        if spec.baseline_id == "generic_device":
            length = 45.0

        metrics = (
            MetricValue(name="fixture_audible_speech_fraction", value=round(fraction, 4), unit="fraction"),
            MetricValue(
                name="fixture_target_band_gain_db", value=round(band_gain + 0.2 * jitter, 3), unit="dB"
            ),
            MetricValue(name="fixture_device_length_mm", value=length, unit="mm"),
        )
        return self._result(spec, started, status="completed", metrics=metrics)

    def _gain_db(self, spec: ExperimentSpec, frequency_hz: float) -> float:
        if spec.candidate_kind == "baseline":
            return 5.0 if spec.baseline_id == "generic_device" else 0.0
        params = spec.parameters
        length = float(params["length_mm"])
        throat = float(params["throat_diameter_mm"])
        if spec.family_id == "conical_horn_fixture":
            mouth = float(params["mouth_diameter_mm"])
        else:
            mouth = throat * math.exp(float(params["flare_rate_per_m"]) * length / 2000.0)
        peak = min(18.0, 10.0 * math.log10(max(mouth / throat, 1.0) ** 2))
        center = 343_000.0 / (4.0 * length)
        octaves = math.log2(frequency_hz / center)
        return peak * math.exp(-(octaves**2) / (2 * 0.9**2))

    def _unsupported_reason(self, spec: ExperimentSpec) -> ErrorInfo | None:
        caps = self._capabilities
        if not any(s.scenario_id == spec.scenario_id for s in caps.scenarios):
            return ErrorInfo(code="unsupported_scenario", message=f"Unknown scenario '{spec.scenario_id}'.")
        usable = {m.frequency_hz for m in spec.hearing_input.measurements if m.threshold_db_hl is not None}
        missing = [f for f in _FIXTURE_FREQUENCIES if f not in usable]
        if missing:
            return ErrorInfo(code="missing_thresholds", message=f"Missing thresholds at {missing} Hz.")
        if spec.candidate_kind == "baseline":
            if caps.baseline(spec.baseline_id or "") is None:
                return ErrorInfo(
                    code="unsupported_baseline", message=f"Unknown baseline '{spec.baseline_id}'."
                )
            return None
        family = caps.family(spec.family_id or "")
        if family is None:
            return ErrorInfo(code="unsupported_family", message=f"Unknown family '{spec.family_id}'.")
        for parameter in family.parameters:
            value = spec.parameters.get(parameter.name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return ErrorInfo(code="bad_parameter", message=f"'{parameter.name}' must be a number.")
            if parameter.minimum is not None and value < parameter.minimum:
                return ErrorInfo(code="out_of_bounds", message=f"'{parameter.name}' below minimum.")
            if parameter.maximum is not None and value > parameter.maximum:
                return ErrorInfo(code="out_of_bounds", message=f"'{parameter.name}' above maximum.")
        return None

    def _result(
        self,
        spec: ExperimentSpec,
        started: float,
        *,
        status: str,
        metrics: tuple[MetricValue, ...] = (),
        error: ErrorInfo | None = None,
    ) -> ExperimentResult:
        return ExperimentResult.model_validate(
            {
                "candidate_id": spec.candidate_id,
                "experiment_id": spec.experiment_id,
                "spec_hash": spec.spec_hash(),
                "status": status,
                "parameters": dict(spec.parameters),
                "evaluation_config": {
                    "scenario_id": spec.scenario_id,
                    "canal_config_id": spec.canal_config_id,
                    "fidelity": spec.fidelity,
                    "calibration_ref": spec.calibration_ref,
                    "hearing_profile_id": spec.hearing_input.profile_id,
                    "target_ear": spec.hearing_input.target_ear,
                },
                "metrics": metrics,
                "assets": (
                    (
                        AssetRef(
                            kind="response_curve",
                            ref=f"fixture://response_curve/{spec.evaluation_key()[:16]}",
                            description="Placeholder reference. No file is produced by the fixture.",
                        ),
                    )
                    if status == "completed"
                    else ()
                ),
                "evaluator_version": FIXTURE_VERSION,
                "seed": spec.seed,
                "runtime_seconds": round(time.perf_counter() - started, 6),
                "provenance": ResultProvenance(
                    kind="development_fixture",
                    evaluator_name=FIXTURE_NAME,
                    evaluator_version=FIXTURE_VERSION,
                    produced_at=datetime.now(UTC),
                    notes=FIXTURE_NOTICE,
                ),
                "error": error,
            }
        )
