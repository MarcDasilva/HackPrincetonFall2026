"""The real evaluator: the backend's hornsim pipeline behind the two evaluator calls.

    HORN_STUDY_REAL_EVALUATOR=horn_study.hornsim_evaluator

hornsim needs torch, pyclarity, and a mesh kernel, which this environment must
not depend on. So every numerical step runs in the backend's own interpreter
through `bridges/hornsim_bridge.py`, one short process per step, with JSON in
and JSON out. This module only decides which steps to run and maps their
answers onto the contract:

    describe   what the installed hornsim supports. Capabilities are built from it.
    context    once per (ear mesh, audiogram): ear world, canals, clips, references.
    build      once per (context, design numbers): the 3D aid and its insertion gain.
    score      once per experiment: HASPI v2 for one listening condition.

Nothing here normalizes a level, rescales a metric, or fills in a threshold.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from horn_study.evaluator_adapter import EvaluatorNotConfigured, TransientEvaluatorError

BACKEND_DIR_ENV = "HORNSIM_BACKEND_DIR"
EAR_MESH_ENV = "HORNSIM_EAR_MESH"
WORK_DIR_ENV = "HORNSIM_WORK_DIR"
PYTHON_ENV = "HORNSIM_PYTHON"
EAR_HEIGHT_ENV = "HORNSIM_EAR_HEIGHT_MM"
TIMEOUT_ENV = "HORNSIM_BRIDGE_TIMEOUT_SECONDS"
BRIDGE_ENV = "HORNSIM_BRIDGE"

EVALUATOR_NAME = "hornsim"
FAMILY_ID = "spiral_exponential_horn"
BASELINE_ID = "unaided"
CANAL_CONFIG_ID = "sampled_canals"
CALIBRATION_REF = "hornsim-reference-at-65-db-spl-v2"
FIDELITY = "plane_wave_1d"
HASPI_UNIT = "HASPI v2 (0-1)"
# Smallest HASPI difference treated as meaningful when a design is compared with the unaided
# control in one scenario. HASPI's seed-to-seed variation was measured at 0.002 or less; differences
# of 0.01 to 0.02 are within the clip-to-clip scatter. This value is a judgment call for the
# evaluator owner to confirm.
HASPI_RESOLUTION = 0.02
# A study must cover enough listening conditions that one noisy condition cannot decide it.
MINIMUM_SCENARIOS = 4
_PLANNING_NOTES = (
    "Evaluations are cheap here: building a candidate's geometry and scoring one scenario each take "
    "seconds. Use the budget to cover clean speech and speech in babble at every presentation level, "
    "with a handful of candidates, in preference to many candidates in few scenarios.",
    "A design is rejected if it scores below the unaided control in any scenario by more than the "
    "metric's resolution, so a design that only helps soft speech and harms loud speech cannot be selected.",
    "Where unaided speech is already at the HASPI ceiling a design can only tie, and a tie does not "
    "disqualify it.",
    "bore_length_mm is informational only. It is not a size, comfort, or quality measure and has no "
    "preferred direction.",
)

DEFAULT_BRIDGE = Path(__file__).resolve().parents[2] / "bridges" / "hornsim_bridge.py"
DEFAULT_TIMEOUT_SECONDS = 1800.0

# The server accepts thresholds in this range (create_patient in backend/app/main.py).
MIN_THRESHOLD_DB_HL = -10.0
MAX_THRESHOLD_DB_HL = 120.0

# Variables the bridge process may inherit. Model and tracing keys are not among them.
_PASSED_ENVIRONMENT = (
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "AUDIOEAR_DIR",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)

# Summary keys of hornsim.acoustics.evaluate, and the metric each one becomes.
_GAIN_BANDS = (
    ("mean_ig_500_1k_db", "insertion_gain_500_1000_hz_db", "500 to 1000 Hz"),
    ("mean_ig_1k_2k_db", "insertion_gain_1000_2000_hz_db", "1000 to 2000 Hz"),
    ("mean_ig_2k_4k_db", "insertion_gain_2000_4000_hz_db", "2000 to 4000 Hz"),
    ("mean_ig_4k_8k_db", "insertion_gain_4000_8000_hz_db", "4000 to 8000 Hz"),
)

_PARAMETER_NOTES = {
    "throat_mm2": (
        "mm^2",
        "Bore cross-section at the canal end, the area that runs through the canal tip. Must be smaller "
        "than mouth_mm2. In the acoustic model this is the strongest lever: a narrow throat acts as a "
        "low-pass filter above about 500 Hz, and widening it brings 1 to 4 kHz back toward the open ear. "
        "It has to pass the canal tip with a wall left, so the largest buildable value is "
        "pi * (canal diameter / 2 - tip_clearance_mm - min_wall_mm)^2: about 20.4 at the defaults and "
        "about 31 with the smallest tip clearance and wall. A throat above about 3 leaves no room for "
        "a vent beside it and needs vent_diameter_mm 0.",
    ),
    "mouth_mm2": (
        "mm^2",
        "Bore cross-section at the faceplate opening. Must be larger than throat_mm2. A larger mouth "
        "raises 2 to 8 kHz once the throat is wide. How large a mouth fits depends on the ear.",
    ),
    "vent_diameter_mm": (
        "mm",
        "Diameter of the straight vent from the faceplate to the canal tip. 0 means no vent, which is the "
        "right choice for a wide throat: the bore then vents the canal itself. A vent that cannot be "
        "routed with min_wall_mm of wall to the bore comes back as a failed case.",
    ),
    "min_wall_mm": ("mm", "Thinnest printed wall allowed around the bore and vent. A fit constraint."),
    "max_path_mm": (
        "mm",
        "Upper limit on the bore path inside the concha. The builder keeps the longest route that fits, "
        "up to this, so a small value forces a short bore.",
    ),
    "tip_clearance_mm": (
        "mm",
        "Gap left between the canal tip and the assumed canal wall. A smaller gap makes the tip wider, "
        "which makes room for a wider throat. A fit choice: the acoustic model treats the tip as sealed "
        "whatever this is.",
    ),
}

_CLIP_TYPE_NAMES = {"clean": "clean_speech", "babble": "speech_in_babble"}
_LEVEL_TAGS = {50: "soft_speech", 65: "conversational_speech", 80: "loud_speech"}

_UNSUPPORTED = (
    (
        "secure_retention",
        "No mechanical or retention model. The shell is only checked to fit inside the concha.",
    ),
    ("comfort", "No comfort or pressure model."),
    ("hearing_protection", "Attenuation of loud sound is not modeled or validated as protection."),
    ("music_quality", "The only perceptual metric is HASPI v2 speech intelligibility. No music metric."),
    ("loudness", "hornsim.score notes that loudness terms are not included yet."),
    ("occlusion_and_own_voice", "hornsim.score notes that occlusion terms are not included yet."),
    ("sound_localization", "One ear and a 1D plane-wave model. No directional or binaural cues."),
    ("reverberation_and_distance", "Clips are dry speech at a set level. No room or distance model."),
    ("wind_noise", "No flow or wind model."),
    ("compact_size", "The shell fills the concha for every design, so outer size does not vary."),
    ("glasses_compatibility", "No packaging model."),
    ("easy_removal", "No handling model."),
    ("durability", "No structural model beyond minimum wall thickness."),
)

BridgeRunner = Callable[[str, dict[str, Any]], dict[str, Any]]


class BridgeProcessError(TransientEvaluatorError):
    """The bridge process died or answered with something unreadable. Worth one identical retry."""


class BridgeTimeout(Exception):
    """A bridge step ran past its time limit."""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HornsimConfig:
    backend_dir: Path
    python: Path
    ear_mesh: Path
    work_dir: Path
    bridge: Path = DEFAULT_BRIDGE
    ear_height_mm: float | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> HornsimConfig:
        """Read the configuration, reporting every problem at once."""
        source = os.environ if env is None else env
        problems: list[str] = []

        def required(name: str, what: str) -> Path | None:
            value = source.get(name, "").strip()
            if not value:
                problems.append(f"{name} is not set ({what})")
                return None
            return Path(value).expanduser().resolve()

        def number(name: str, what: str) -> float | None:
            value = source.get(name, "").strip()
            if not value:
                return None
            try:
                parsed = float(value)
            except ValueError:
                parsed = math.nan
            if not math.isfinite(parsed) or parsed <= 0:
                problems.append(f"{name}='{value}' is not a positive number ({what})")
                return None
            return parsed

        backend_dir = required(BACKEND_DIR_ENV, "the repository's backend/ directory")
        ear_mesh = required(EAR_MESH_ENV, "the patient's ear mesh in mm, AudioEar topology")
        work_dir = required(WORK_DIR_ENV, "a directory for built contexts and aids")
        ear_height_mm = number(EAR_HEIGHT_ENV, "ear height in mm used to rescale the mesh")
        timeout_seconds = number(TIMEOUT_ENV, "seconds allowed per bridge step")

        python_value = source.get(PYTHON_ENV, "").strip()
        python: Path | None = None
        if python_value:
            python = Path(python_value).expanduser().absolute()
        elif backend_dir is not None:
            python = backend_dir / ".venv" / "bin" / "python"
        bridge_value = source.get(BRIDGE_ENV, "").strip()
        bridge = Path(bridge_value).expanduser().resolve() if bridge_value else DEFAULT_BRIDGE

        if backend_dir is not None and not (backend_dir / "hornsim").is_dir():
            problems.append(f"{BACKEND_DIR_ENV}='{backend_dir}' has no hornsim/ package")
        if python is not None and not python.is_file():
            problems.append(
                f"the backend interpreter '{python}' does not exist "
                f"(create backend/.venv as backend/README.md describes, or set {PYTHON_ENV})"
            )
        if ear_mesh is not None and not ear_mesh.is_file():
            problems.append(f"{EAR_MESH_ENV}='{ear_mesh}' is not a file")
        if not bridge.is_file():
            problems.append(f"the bridge script '{bridge}' does not exist (set {BRIDGE_ENV})")
        if problems or backend_dir is None or python is None or ear_mesh is None or work_dir is None:
            raise EvaluatorNotConfigured(
                "The hornsim evaluator is not configured: " + "; ".join(problems) + "."
            )
        return cls(
            backend_dir=backend_dir,
            python=python,
            ear_mesh=ear_mesh,
            work_dir=work_dir,
            bridge=bridge,
            ear_height_mm=ear_height_mm,
            timeout_seconds=timeout_seconds or DEFAULT_TIMEOUT_SECONDS,
        )


def process_runner(config: HornsimConfig) -> BridgeRunner:
    """Run one bridge command in the backend interpreter and return its JSON answer."""
    environment = {name: os.environ[name] for name in _PASSED_ENVIRONMENT if name in os.environ}
    environment["PYTHONPATH"] = str(config.backend_dir)
    environment["MPLBACKEND"] = "Agg"

    def run(command: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            done = subprocess.run(
                [str(config.python), str(config.bridge), command],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
                cwd=config.backend_dir,
                env=environment,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise BridgeTimeout(
                f"hornsim '{command}' did not finish within {config.timeout_seconds:g} seconds."
            ) from error
        except OSError as error:
            raise EvaluatorNotConfigured(f"Could not start the hornsim bridge: {error}") from error
        try:
            answer = json.loads(done.stdout)
        except json.JSONDecodeError:
            answer = None
        if not isinstance(answer, dict) or "ok" not in answer:
            tail = " | ".join(done.stderr.strip().splitlines()[-3:])
            raise BridgeProcessError(
                f"hornsim '{command}' exited with code {done.returncode} and no readable answer. {tail}"[:800]
            )
        return answer

    return run


class _Once:
    """Runs the work for each key once. Callers that arrive meanwhile wait for the first.

    A failed attempt (an exception) is not remembered, so a later call tries again.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[Any, threading.Lock] = {}
        self._values: dict[Any, dict[str, Any]] = {}

    def get(self, key: Any, work: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            if key not in self._values:
                self._values[key] = work()
            return self._values[key]


# --------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------


def _freq_text(frequencies: list[float]) -> str:
    return ", ".join(f"{f:g}" for f in frequencies)


def scenario_id(clip_type: str, level: float) -> str:
    return f"{_CLIP_TYPE_NAMES[clip_type]}_{level:g}_db_spl"


def _scenarios(described: Mapping[str, Any]) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for clip_type in ("clean", "babble"):
        clips = [clip for clip in described["clips"] if clip["type"] == clip_type]
        if not clips:
            continue
        many = len(clips) != 1
        count = f"{len(clips)} Harvard sentence{'s' if many else ''} from {'synthetic voices' if many else 'a synthetic voice'}"
        averaged = f" Values are means over the {len(clips)} clips." if len(clips) > 1 else ""
        for level in described["levels_db_spl"]:
            if clip_type == "clean":
                text = f"{count} in quiet, presented at {level:g} dB SPL.{averaged}"
                tags = ["speech", "quiet"]
            else:
                ratios = "/".join(dict.fromkeys(f"{clip['snr_db']:+g}" for clip in clips))
                text = (
                    f"{count} in {described['babble_talkers']}-talker babble at {ratios} dB "
                    f"signal-to-noise ratio, with the talker at {level:g} dB SPL.{averaged}"
                )
                tags = ["speech", "noise", "babble"]
            if level in _LEVEL_TAGS:
                tags.append(_LEVEL_TAGS[level])
            scenarios.append(
                {
                    "scenario_id": scenario_id(clip_type, level),
                    "description": text,
                    "source_level_db_spl": level,
                    "tags": tags,
                    "clip_type": clip_type,
                    "clips": [clip["name"] for clip in clips],
                }
            )
    return scenarios


def _metrics(described: Mapping[str, Any]) -> list[dict[str, Any]]:
    canal = described["canal"]
    spread = f"{canal['scored']} of the {canal['samples']} sampled ear canals, smallest to largest"
    metrics = [
        {
            "name": "haspi_v2_mean",
            "unit": HASPI_UNIT,
            "direction": "higher_is_better",
            "resolution": HASPI_RESOLUTION,
            "description": (
                f"HASPI v2 speech intelligibility index with the listener's audiogram, averaged over "
                f"{spread}, and over the scenario's clips. For the unaided control it is the score with "
                "a flat 0 dB response."
            ),
        },
        {
            "name": "haspi_v2_worst_canal",
            "unit": HASPI_UNIT,
            "direction": "higher_is_better",
            "resolution": HASPI_RESOLUTION,
            "description": (
                "HASPI v2 for the sampled ear canal with the lowest score (each canal averaged over "
                "the scenario's clips). Shows sensitivity to the unknown canal size."
            ),
        },
        {
            "name": "haspi_v2_improvement_over_unaided",
            "unit": HASPI_UNIT,
            "direction": "higher_is_better",
            "resolution": HASPI_RESOLUTION,
            "description": (
                "haspi_v2_mean minus the unaided score for the same clips and level, computed the "
                "same way. Negative means the device makes speech less intelligible than no device."
            ),
        },
    ]
    metrics += [
        {
            "name": name,
            "unit": "dB",
            "direction": "higher_is_better",
            "description": (
                f"Modeled insertion gain averaged over {band}: eardrum level with the aid relative to "
                f"the open ear, median over all {canal['samples']} sampled canals. Negative means the "
                "aid attenuates. The same for every scenario. 0 for the unaided control."
            ),
        }
        for _, name, band in _GAIN_BANDS
    ]
    metrics.append(
        {
            "name": "bore_length_mm",
            "unit": "mm",
            "direction": "informational",
            "description": (
                "Length of the bore that was actually routed in this ear, from design.json. It counts the "
                "mouth riser and the run through the canal tip, so it can exceed max_path_mm, which limits "
                "the path inside the concha only. Reported to describe the design, not as a goal: a longer "
                "bore lowers the estimated horn cutoff, while a wide bore is routed short and keeps more "
                "of the 2 to 4 kHz response. It is not a size or comfort measure: the shell fills the "
                "concha either way. 0 for the unaided control."
            ),
        }
    )
    return metrics


def _model_description(described: Mapping[str, Any]) -> str:
    canal = described["canal"]
    low, high = canal["residual_volume_cc"]
    mesh = described.get("ear_mesh", {})
    mesh_note = mesh.get("provenance", {}).get("source") or "a configured ear mesh of unrecorded origin."
    return " ".join(
        [
            "hornsim builds a passive in-ear aid in the configured ear mesh and models it.",
            "Geometry: a shell that fills the concha, a bore with exponential area flare that is coiled as a"
            " spiral when narrow and routed as a short uncoiled funnel when wide, and an optional straight vent.",
            "Acoustics: a 1D plane-wave transmission-line model with viscous and thermal wall losses,"
            " giving insertion gain at the eardrum relative to the open ear.",
            "Scoring: the insertion gain is applied to speech clips as a linear zero-phase filter and"
            f" HASPI v2 (pyclarity {described['dependencies']['pyclarity']}) is computed with the supplied audiogram.",
            "What the model shows about this family: with the concha filled, no bore that fits reaches the"
            " open ear at 2 to 4 kHz. The shell removes the concha's own boost there, and the added bore"
            " length moves the ear canal resonance down, which can add a few dB at 1 to 2 kHz.",
            "Stated simplifications:",
            "the eardrum is a series resistance-mass-compliance with values picked in the published adult range;",
            "the concha is one resonance bump approximating an average ear, removed in full because the shell fills it;",
            "the ear canal is not in the mesh, so its opening is placed at the deepest point of the concha with an"
            f" assumed {canal['assumed_diameter_mm']:g} mm diameter, and the residual canal volume is sampled from"
            f" {low:g} to {high:g} cc rather than measured;",
            "the gap around the canal tip is not modeled, so the tip is treated as sealed;",
            "speech is synthetic text-to-speech, and babble is synthetic talkers;",
            "HASPI on one two-second clip swings with level, so only the mean over a scenario's clips is"
            " meant for ranking designs;",
            "HASPI's internal noise is fixed with one seed so scores repeat.",
            "The model is linear and level-independent, has no head, room, or directional effects, and has not"
            " been validated against measurements on a printed device.",
            f"Ear mesh in use: {mesh_note}",
            "The mesh is taken to be the target ear.",
            "Results are model outputs, not clinical evidence.",
        ]
    )


def parameter_bounds(described: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """Bounds and defaults of the server's AidDesign model, as the installed backend reports them."""
    return {name: dict(bounds) for name, bounds in described["aid_design_fields"].items()}


def build_capabilities(described: Mapping[str, Any]) -> dict[str, Any]:
    """Turn what the installed hornsim reports about itself into the capability contract."""
    fields = parameter_bounds(described)
    parameters = []
    for name, bounds in fields.items():
        unit, note = _PARAMETER_NOTES.get(name, (None, ""))
        default = f" hornsim default {bounds['default']:g}." if "default" in bounds else ""
        parameters.append(
            {
                "name": name,
                "kind": "float",
                "unit": unit,
                "minimum": bounds.get("minimum"),
                "maximum": bounds.get("maximum"),
                "description": (note + default).strip(),
            }
        )
    fixed = {k: v for k, v in described["aid_defaults"].items() if k not in fields}
    required = [float(f) for f in described["haspi_frequencies_hz"]]
    canal = described["canal"]
    scenarios = _scenarios(described)
    return {
        "evaluator_name": EVALUATOR_NAME,
        "evaluator_version": described["version"],
        "kind": "real",
        "model_description": _model_description(described),
        "geometry_families": [
            {
                "family_id": FAMILY_ID,
                "description": (
                    "In-ear shell that fills the concha of the configured ear, with a bore whose area "
                    "flares exponentially from the throat at the canal tip to the mouth on the faceplate, "
                    "and an optional straight vent beside it. The builder keeps the longest route that "
                    "fits: a coiled spiral for a narrow bore, a short uncoiled funnel for a wide one. Bore "
                    "length is therefore an output, not an input. mouth_mm2 must be larger than "
                    "throat_mm2. Not every combination fits: a design that cannot be routed in this ear "
                    "comes back as a failed case with hornsim's reason, which makes that design "
                    "ineligible. The usual reasons are a throat too wide for the canal tip at the chosen "
                    "wall and tip clearance, a mouth too large for the concha, and a vent with no room "
                    "beside the bore. The hornsim defaults are a narrow, heavily attenuating starting "
                    "point. Building one design takes about ten seconds."
                ),
                "parameters": parameters,
            }
        ],
        "baselines": [
            {
                "baseline_id": BASELINE_ID,
                "kind": "unaided",
                "description": (
                    "No device: a flat 0 dB insertion gain sent through the same clips, levels, and HASPI "
                    "v2 call as the designs. The control."
                ),
            }
        ],
        "hearing_input": {
            "supported_measurement_types": ["air_conduction"],
            "required_frequencies_hz": required,
            "optional_frequencies_hz": [],
            "accepts_additional_frequencies": False,
            "min_threshold_db_hl": MIN_THRESHOLD_DB_HL,
            "max_threshold_db_hl": MAX_THRESHOLD_DB_HL,
            "accepts_no_response": False,
            "missing_data_rule": (
                f"HASPI v2 uses the audiogram at exactly {_freq_text(required)} Hz. A measured "
                "air-conduction threshold for the target ear is required at every one of them. pyclarity "
                "would interpolate or extend a missing value, so this evaluator refuses instead: nothing "
                "is interpolated, extrapolated, or defaulted. Thresholds at other frequencies are not "
                "used by the model."
            ),
        },
        "demo_profiles": [],
        "scenarios": scenarios,
        "required_scenario_tags": [
            tag for tag in ("quiet", "babble") if any(tag in sc["tags"] for sc in scenarios)
        ],
        "minimum_scenarios": min(MINIMUM_SCENARIOS, len(scenarios)),
        "planning_notes": list(_PLANNING_NOTES),
        "metrics": _metrics(described),
        "canal_configurations": [
            {
                "canal_config_id": CANAL_CONFIG_ID,
                "description": (
                    f"The patient context's {canal['samples']} sampled residual canal volumes "
                    f"({canal['residual_volume_cc'][0]:g} to {canal['residual_volume_cc'][1]:g} cc, assumed "
                    f"{canal['assumed_diameter_mm']:g} mm diameter). HASPI uses a spread of {canal['scored']} "
                    "of them, insertion gain summaries use all."
                ),
                "is_default": True,
            }
        ],
        "requires_ear_mesh": False,
        "calibration": {
            "calibration_ref": CALIBRATION_REF,
            "description": (
                "hornsim.scoring convention: the clean reference clip has RMS 1 and always stands for "
                f"{described['reference_db_spl']:g} dB SPL, the level HASPI's ear model expects its "
                "normal-hearing reference at."
            ),
            "source_level_convention": (
                "Each scenario's source_level_db_spl sets what the listener hears: hornsim scales the heard "
                f"signal by (level - {described['reference_db_spl']:g}) dB before HASPI and leaves the "
                "reference alone. In babble it is the level of the talker, with the babble added on top at "
                "the stated signal-to-noise ratio."
            ),
            "normalization": (
                "None by the adapter or bridge. Insertion gain is applied to what the listener hears, "
                "never to the HASPI reference. Clips are read the way hornsim.score reads them."
            ),
        },
        # hornsim fixes HASPI's internal noise with one seed (evaluation.haspi_seed) so that scores
        # repeat, and its unaided and ceiling references exist for that seed only. The seed is not a
        # source of physical variation, so repetitions would spend budget without testing the design.
        "supports_seeds": False,
        "max_repetitions": 1,
        "fidelity_levels": [FIDELITY],
        "default_fidelity": FIDELITY,
        "output_assets": [
            "design_json",
            "aid_glb",
            "aid_in_ear_glb",
            "aid_print_stl",
            "acoustics_json",
            "insertion_gain_png",
            "references_json",
            "canals_json",
        ],
        "unsupported_requirements": [
            {"requirement": requirement, "reason": reason} for requirement, reason in _UNSUPPORTED
        ],
        "references": [
            {
                "title": "pyclarity (Clarity Challenge toolkit)",
                "url": "https://github.com/claritychallenge/clarity",
                "note": "Source of the HASPI v2 implementation (Kates and Arehart, 2021) used for scoring.",
            },
            {
                "title": "AudioEar (Huang et al., AAAI 2023)",
                "url": "https://github.com/seanywang0408/AudioEar",
                "note": "Source of the ear shape model and landmarks behind the ear mesh.",
            },
        ],
        # Extra fields, kept with the capability snapshot.
        "haspi_seed": described["haspi_seed"],
        "fixed_design_values": fixed,
        "ear_mesh": described.get("ear_mesh"),
        "dependencies": described["dependencies"],
    }


# --------------------------------------------------------------------------
# Evaluator
# --------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


class HornsimEvaluator:
    """`get_evaluator_capabilities` and `evaluate_experiment` over the hornsim bridge.

    Safe to call from several threads. A patient context is built once per
    audiogram and an aid once per set of design numbers, however many
    scenarios ask for them and however they interleave.
    """

    def __init__(self, config: HornsimConfig, run_bridge: BridgeRunner | None = None) -> None:
        self._config = config
        self._run = run_bridge or process_runner(config)
        self._described: dict[str, Any] | None = None
        self._describe_lock = threading.Lock()
        self._contexts = _Once()
        self._builds = _Once()

    # -- capabilities ------------------------------------------------------

    def _describe(self, *, refresh: bool) -> dict[str, Any]:
        with self._describe_lock:
            if refresh or self._described is None:
                answer = self._run("describe", {"ear_mesh": str(self._config.ear_mesh)})
                if not answer["ok"]:
                    raise EvaluatorNotConfigured(
                        f"hornsim could not describe itself: {answer['error']['message']}"
                    )
                self._described = answer
            return self._described

    def get_evaluator_capabilities(self) -> dict[str, Any]:
        """Ask the installed hornsim what it supports. Read fresh each time a study starts."""
        try:
            described = self._describe(refresh=True)
        except (BridgeProcessError, BridgeTimeout) as error:
            raise EvaluatorNotConfigured(f"The hornsim backend is not usable: {error}") from error
        return build_capabilities(described)

    # -- evaluation --------------------------------------------------------

    def evaluate_experiment(self, spec: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        described = self._describe(refresh=False)
        version = described["version"]

        def finish(status: str, *, used_version: str = version, **fields: Any) -> dict[str, Any]:
            return self._result(spec, started, status, used_version, described, **fields)

        scenario = next(
            (s for s in _scenarios(described) if s["scenario_id"] == spec.get("scenario_id")), None
        )
        problem = self._unsupported_reason(spec, described, scenario)
        audiogram = self._audiogram(spec, described)
        if problem is None and isinstance(audiogram, str):
            problem = {"code": "missing_thresholds", "message": audiogram}
        if problem is not None or scenario is None or isinstance(audiogram, str):
            return finish("unsupported", error=problem)

        ear = spec["hearing_input"]["target_ear"]
        try:
            context = self._contexts.get(
                (version, ear, tuple(sorted(audiogram.items()))),
                lambda: self._step(
                    "context",
                    {
                        "work_dir": str(self._config.work_dir),
                        "ear_mesh": str(self._config.ear_mesh),
                        "ear_height_mm": self._config.ear_height_mm,
                        "side": ear,
                        "audiogram_db_hl": audiogram,
                    },
                ),
            )
            if not context["ok"]:
                return finish("failed", error=context["error"])

            build: dict[str, Any] | None = None
            if spec["candidate_kind"] == "design":
                parameters = {name: float(value) for name, value in spec["parameters"].items()}
                build = self._builds.get(
                    (context["context_dir"], tuple(sorted(parameters.items()))),
                    lambda: self._step(
                        "build",
                        {
                            "work_dir": str(self._config.work_dir),
                            "context_dir": context["context_dir"],
                            "parameters": parameters,
                        },
                    ),
                )
                if not build["ok"]:
                    return finish(
                        "failed", used_version=context["version"], error=build["error"], context=context
                    )
                if not build["fits"]:
                    return finish(
                        "failed",
                        used_version=build["version"],
                        error={
                            "code": "geometry_does_not_fit",
                            "message": f"This design cannot be built in this ear: {build['error']}.",
                        },
                        context=context,
                    )
                vent_wall = _number(build["design"].get("vent_wall_to_bore_mm"))
                if vent_wall is not None and vent_wall < 0:
                    # hornsim.aid now refuses a vent it cannot route clear of the bore. This guards a
                    # backend that still keeps an overlapping route: the acoustic model would score two
                    # separate channels that the printed part does not have.
                    return finish(
                        "failed",
                        used_version=build["version"],
                        error={
                            "code": "vent_intersects_bore",
                            "message": (
                                "hornsim built this design, but its own fit check shows the vent cutting "
                                f"into the bore (vent_wall_to_bore_mm = {vent_wall:g}). The acoustic model "
                                "assumes separate channels, so no score is reported. Try a smaller vent."
                            ),
                        },
                        context=context,
                        build=build,
                    )

            score = self._step(
                "score",
                {
                    "context_dir": context["context_dir"],
                    "candidate_dir": build["candidate_dir"] if build else None,
                    "clip_type": scenario["clip_type"],
                    "level_db_spl": scenario["source_level_db_spl"],
                },
            )
            if not score["ok"]:
                return finish(
                    "failed", used_version=context["version"], error=score["error"], context=context
                )
        except BridgeTimeout as error:
            return finish("failed", error={"code": "timeout", "message": str(error)})
        return finish("completed", used_version=score["version"], context=context, build=build, score=score)

    def _step(self, step: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one bridge step. An error it reports becomes a failed case, never a number.

        Reported context and build errors are remembered with the step, so an
        identical build is not repeated for every scenario only to
        fail the same way. A process that dies is not remembered (see _Once).
        """
        answer = self._run(step, payload)
        if answer["ok"]:
            return answer
        message = f"hornsim {step} step failed: {answer['error']['message']}"[:800]
        return {"ok": False, "error": {"code": f"{step}_failed", "message": message}}

    def _unsupported_reason(
        self, spec: Mapping[str, Any], described: Mapping[str, Any], scenario: Mapping[str, Any] | None
    ) -> dict[str, str] | None:
        def no(code: str, message: str) -> dict[str, str]:
            return {"code": code, "message": message}

        if scenario is None:
            return no("unsupported_scenario", f"Unknown scenario '{spec.get('scenario_id')}'.")
        if spec.get("canal_config_id") not in (None, CANAL_CONFIG_ID):
            return no("unsupported_canal_config", f"Unknown canal configuration '{spec['canal_config_id']}'.")
        if spec.get("fidelity") != FIDELITY:
            return no("unsupported_fidelity", f"Unknown fidelity '{spec.get('fidelity')}'.")
        if spec.get("calibration_ref") != CALIBRATION_REF:
            return no(
                "calibration_mismatch",
                f"The spec names calibration '{spec.get('calibration_ref')}', not '{CALIBRATION_REF}'.",
            )
        if spec.get("seed") is not None:
            return no("seeds_unsupported", "hornsim fixes the HASPI seed. Seeds cannot be set per case.")
        mesh_ref = spec.get("ear_mesh_ref")
        if mesh_ref is not None and Path(mesh_ref).expanduser().resolve() != self._config.ear_mesh.resolve():
            return no(
                "ear_mesh_mismatch",
                f"The spec names ear mesh '{mesh_ref}', but this evaluator is configured through "
                f"{EAR_MESH_ENV} and does not take a mesh per request.",
            )
        if spec.get("candidate_kind") == "baseline":
            if spec.get("baseline_id") != BASELINE_ID:
                return no("unsupported_baseline", f"Unknown baseline '{spec.get('baseline_id')}'.")
            return None
        if spec.get("family_id") != FAMILY_ID:
            return no("unsupported_family", f"Unknown geometry family '{spec.get('family_id')}'.")
        fields = parameter_bounds(described)
        given = spec.get("parameters", {})
        unknown = sorted(set(given) - set(fields))
        if unknown:
            return no("bad_parameter", f"Not parameters of '{FAMILY_ID}': {', '.join(unknown)}.")
        for name, bounds in fields.items():
            value = _number(given.get(name))
            if value is None:
                return no("bad_parameter", f"'{name}' must be a number.")
            if "minimum" in bounds and value < bounds["minimum"]:
                return no("out_of_bounds", f"{name}={value:g} is below the minimum {bounds['minimum']:g}.")
            if "maximum" in bounds and value > bounds["maximum"]:
                return no("out_of_bounds", f"{name}={value:g} is above the maximum {bounds['maximum']:g}.")
        if {"mouth_mm2", "throat_mm2"} <= set(fields) and given["mouth_mm2"] <= given["throat_mm2"]:
            # The same rule the server applies before rebuilding an aid (backend/app/main.py).
            return no("out_of_bounds", "mouth_mm2 must be larger than throat_mm2.")
        return None

    @staticmethod
    def _audiogram(spec: Mapping[str, Any], described: Mapping[str, Any]) -> dict[str, float] | str:
        """The supplied thresholds at the frequencies HASPI uses, or why they cannot be used.

        Values pass through as given. A missing frequency is an error, never a gap to fill.
        """
        hearing = spec.get("hearing_input") or {}
        ear = hearing.get("target_ear")
        required = [float(f) for f in described["haspi_frequencies_hz"]]
        supplied: dict[float, float] = {}
        for item in hearing.get("measurements", ()):
            threshold = _number(item.get("threshold_db_hl"))
            if (
                item.get("ear") != ear
                or item.get("measurement_type") != "air_conduction"
                or item.get("status") != "measured"
                or threshold is None
            ):
                continue
            frequency = float(item["frequency_hz"])
            if frequency in supplied:
                return f"More than one threshold was supplied at {frequency:g} Hz."
            supplied[frequency] = threshold
        missing = [f for f in required if f not in supplied]
        if missing:
            return (
                f"HASPI v2 needs measured thresholds at {_freq_text(required)} Hz. "
                f"Missing: {_freq_text(missing)} Hz. Nothing was interpolated or filled in."
            )
        return {f"{f:g}": supplied[f] for f in required}

    def _result(
        self,
        spec: Mapping[str, Any],
        started: float,
        status: str,
        version: str,
        described: Mapping[str, Any],
        *,
        error: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        build: Mapping[str, Any] | None = None,
        score: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        hearing = spec.get("hearing_input") or {}
        config: dict[str, Any] = {
            "scenario_id": spec.get("scenario_id"),
            "canal_config_id": spec.get("canal_config_id"),
            "fidelity": spec.get("fidelity"),
            "calibration_ref": spec.get("calibration_ref"),
            "hearing_profile_id": hearing.get("profile_id"),
            "target_ear": hearing.get("target_ear"),
            "ear_mesh_path": str(self._config.ear_mesh),
            "ear_height_mm": self._config.ear_height_mm,
        }
        assets: list[dict[str, str]] = []
        extra: dict[str, Any] = {}
        if context is not None:
            config["audiogram_db_hl"] = context["audiogram_db_hl"]
            config["ear_mesh"] = context["ear_mesh"]
            config["context_dir"] = context["context_dir"]
            assets += [{"kind": kind, "ref": ref} for kind, ref in context["assets"].items()]
        if build is not None and build.get("fits"):
            config["candidate_dir"] = build["candidate_dir"]
            assets = [{"kind": kind, "ref": ref} for kind, ref in build["assets"].items()] + assets
            extra["design"] = build["design"]
            extra["acoustics_summary"] = build["acoustics_summary"]
            extra["build_seconds"] = build["build_seconds"]
        metrics: list[dict[str, Any]] = []
        if score is not None:
            config["clip_type"] = score["clip_type"]
            config["level_db_spl"] = score["level_db_spl"]
            config["canals_used_cc"] = score["canals_used_cc"]
            config["haspi_seed"] = score["haspi_seed"]
            extra["haspi_per_clip"] = score["per_clip"]
            extra["score_seconds"] = score["seconds"]
            metrics = [
                {"name": "haspi_v2_mean", "value": score["haspi_mean"], "unit": HASPI_UNIT},
                {"name": "haspi_v2_worst_canal", "value": score["haspi_worst_canal"], "unit": HASPI_UNIT},
                {
                    "name": "haspi_v2_improvement_over_unaided",
                    "value": score["haspi_mean"] - score["unaided_haspi_mean"],
                    "unit": HASPI_UNIT,
                },
            ]
            # With no device, insertion gain is 0 dB by definition and there is no bore.
            summary = build["acoustics_summary"] if build else {key: 0.0 for key, _, _ in _GAIN_BANDS}
            metrics += [{"name": name, "value": summary[key], "unit": "dB"} for key, name, _ in _GAIN_BANDS]
            length = build["design"]["bore_length_mm"] if build else 0.0
            metrics.append({"name": "bore_length_mm", "value": length, "unit": "mm"})
        mesh = described.get("ear_mesh", {})
        mesh_note = mesh.get("provenance", {}).get("source") or f"configured mesh {mesh.get('file_name')}"
        return {
            "candidate_id": spec.get("candidate_id"),
            "experiment_id": spec.get("experiment_id"),
            "spec_hash": spec.get("spec_hash"),
            "status": status,
            "parameters": dict(spec.get("parameters") or {}),
            "evaluation_config": config,
            "metrics": metrics,
            "assets": assets,
            "evaluator_version": version,
            "seed": None,
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "provenance": {
                "kind": "real",
                "evaluator_name": EVALUATOR_NAME,
                "evaluator_version": version,
                "produced_at": datetime.now(UTC).isoformat(),
                "notes": (
                    "hornsim 1D acoustic model and HASPI v2 "
                    f"(pyclarity {described['dependencies']['pyclarity']}). Ear mesh: {mesh_note}"
                ),
            },
            "error": dict(error) if error is not None else None,
            **extra,
        }


# --------------------------------------------------------------------------
# Module-level entry points, for HORN_STUDY_REAL_EVALUATOR=horn_study.hornsim_evaluator
# --------------------------------------------------------------------------

_default: HornsimEvaluator | None = None
_default_lock = threading.Lock()


def _evaluator() -> HornsimEvaluator:
    """One evaluator per process, so builds are shared by every study the process runs."""
    global _default
    with _default_lock:
        if _default is None:
            _default = HornsimEvaluator(HornsimConfig.from_env())
        return _default


def get_evaluator_capabilities() -> dict[str, Any]:
    return _evaluator().get_evaluator_capabilities()


def evaluate_experiment(spec: dict[str, Any]) -> dict[str, Any]:
    return _evaluator().evaluate_experiment(spec)
