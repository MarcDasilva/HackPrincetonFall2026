"""The real evaluator: the backend's hornsim pipeline behind the two evaluator calls.

    HORN_STUDY_REAL_EVALUATOR=horn_study.hornsim_evaluator

hornsim needs torch, pyclarity, and a mesh kernel, which this environment must
not depend on. So every numerical step runs in the backend's own interpreter
through `bridges/hornsim_bridge.py`, one short process per step, with JSON in
and JSON out. This module only decides which steps to run and maps their
answers onto the contract:

    describe         what the installed hornsim supports, and what the configured ear can hold.
                     Capabilities are built from it.
    context          once per (ear mesh, audiogram): ear world, canals, clips, references.
    build            once per (context, design numbers): the coiled aid and its insertion gain.
    build-earpiece   once per (context, design numbers): the in-concha earpiece and its insertion gain.
    score            once per experiment: HASPI v2 for one listening condition.

Two geometry families are declared: the coiled aid of `hornsim.aid` and the
in-concha earpiece of `hornsim.earpiece`. Both go through the same scenarios,
canal sample, HASPI call, and unaided control.

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
from dataclasses import asdict, dataclass
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
EARPIECE_FAMILY_ID = "concha_horn_earpiece"
# The two scalar dials a study uses to ask for a collector. hornsim.earpiece takes a collector as a
# spine and cross-sections, which `earpiece_builder_parameters` writes from these.
COLLECTOR_REACH = "collector_reach_mm"
COLLECTOR_MOUTH = "collector_mouth_mm2"
# Dials a study sets on hornsim.earpiece under the builder's own names. Every other dial of the
# builder shapes or holds the piece without changing what the acoustic model is given, and stays
# at the builder's default.
_EARPIECE_BUILDER_DIALS = ("throat_mm2", "mouth_mm2", "canal_stem_mm")
# Radii per cross-section in hornsim.earpiece's collector format.
_COLLECTOR_SECTION_POINTS = 12
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
    "protrusion_mm reports how far each built part stands out past the concha rim. It is informational "
    "too. When the user wants a small or discreet device, put a max constraint on it: that is the only "
    "way a size preference enters the selection.",
)
_EARPIECE_PLANNING_NOTES = (
    "Two device families are declared. spiral_exponential_horn is a shell that fills the concha, with "
    "a coiled or funnel bore and an optional vent, and its mouth sits flush on the faceplate. "
    "concha_horn_earpiece is a seat with a short horn carved inside it, an optional canal stem, and an "
    "optional collector that carries the horn outward past the faceplate. It is the only family that "
    "can have an opening larger than the concha opening, and only through its two collector dials.",
    "Model prediction, not a measured fact: on a template ear with one example sloping loss, every "
    "spiral design that was evaluated fell below the unaided control in at least one scenario, and an "
    "acoustic-only sweep of the 1D model (no builds, no HASPI) suggested that a wide throat with an "
    "opening larger than the concha opening, a protruding collector of around 450 mm^2, stays at or "
    "above the unaided ear in every listening condition. Nothing has been measured on a printed device. "
    "A study can test this by comparing concha_horn_earpiece candidates that have canal_stem_mm 0, a "
    "wide throat, and a collector with candidates that have none.",
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

_EARPIECE_PARAMETER_NOTES = {
    "throat_mm2": (
        "mm^2",
        "Bore area at the seat floor, the end toward the canal. Must be smaller than mouth_mm2. A wider "
        "throat passes more of 2 to 8 kHz. With a canal stem the bore runs inside the stem, so on this ear "
        "{stem_throat}",
    ),
    "mouth_mm2": (
        "mm^2",
        "Mouth area on the faceplate, with an outline that follows this ear's concha opening. Must be "
        "larger than throat_mm2. The builder's own range reaches {builder_mouth_max:g}, but the mouth "
        "has to fit the concha opening, and the maximum declared here is the largest that "
        "hornsim.target found this ear holds. A large mouth on a narrow throat can still be rejected "
        "when the flare breaks through the seat wall. For an opening larger than this, add a collector.",
    ),
    "canal_stem_mm": (
        "mm",
        "Length of the soft stem into the canal that holds the piece in. 0 means no stem: the piece then "
        "relies on its fit in the concha alone, and the throat may be wider. In the acoustic model the "
        "stem is a tube at the throat area, and a longer stem leaves less of the canal behind it.",
    ),
    COLLECTOR_REACH: (
        "mm",
        "How far the collector's rim sits out from the mouth centre, straight along the faceplate "
        "normal. 0 together with collector_mouth_mm2 0 means no collector and a flush faceplate. The "
        "builder rejects a collector that touches the ear or the head, or that has any point more than "
        "{max_reach:g} mm from the mouth centre, which counts the rim's radius and wall as well as this "
        "distance.",
    ),
    COLLECTOR_MOUTH: (
        "mm^2",
        "Area of the collector's round outer opening. 0 together with collector_reach_mm 0 means no "
        "collector. It may be larger than the concha opening, which is what a collector is for. The "
        "builder takes a rim radius of {radius_low:g} to {radius_high:g} mm, so an area below "
        "{area_low:.3g} is refused.",
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
    ("glasses_compatibility", "No packaging model."),
    ("easy_removal", "No handling model."),
    ("durability", "No structural model beyond minimum wall thickness."),
)

# Declared only while the spiral family is the only one. With the earpiece, outer size varies and
# protrusion_mm reports it.
_COMPACT_SIZE_UNSUPPORTED = (
    "compact_size",
    "The shell fills the concha for every design, so outer size does not vary.",
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
    earpiece = earpiece_available(described)
    open_ear = (
        " The open ear is an average concha resonance for spiral_exponential_horn and the configured "
        "ear's own concha for concha_horn_earpiece."
        if earpiece
        else ""
    )
    earpiece_length = (
        " For concha_horn_earpiece it is the flare inside the seat, from the seat floor to the faceplate "
        "mouth, and counts neither the canal stem nor a collector."
        if earpiece
        else ""
    )
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
                "aid attenuates. The same for every scenario. 0 for the unaided control." + open_ear
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
                "concha either way. 0 for the unaided control." + earpiece_length
            ),
        }
    )
    metrics.append(
        {
            "name": "protrusion_mm",
            "unit": "mm",
            "direction": "informational",
            "description": (
                "How far the built part stands out past the plane of the concha rim, along the rim normal, "
                "measured on the print solid. hornsim.earpiece reports it as proud_of_concha_mm, and the "
                "same measure is taken on the spiral family's print. It counts the removal tab and any "
                "collector. It has no better or worse direction of its own, but a selection constraint can "
                "cap it when the user wants a small or discreet device. 0 for the unaided control."
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
            *(
                [
                    "A second device, the in-concha earpiece of hornsim.earpiece, is a seat with the horn carved"
                    " inside it and an optional collector beyond the faceplate. It goes through the same acoustic"
                    " model, clips, and HASPI call, with the configured ear's own concha as its open-ear"
                    " reference. Its family description says what the model is given and what it does not see.",
                ]
                if earpiece_available(described)
                else []
            ),
            "Acoustics: a 1D plane-wave transmission-line model with viscous and thermal wall losses,"
            " giving insertion gain at the eardrum relative to the open ear.",
            "Scoring: the insertion gain is applied to speech clips as a linear zero-phase filter and"
            f" HASPI v2 (pyclarity {described['dependencies']['pyclarity']}) is computed with the supplied audiogram.",
            "What the model shows about the spiral family: with the concha filled, no bore that fits reaches the"
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


def earpiece_available(described: Mapping[str, Any]) -> bool:
    """Whether the backend has the earpiece builder and the configured ear can hold an earpiece."""
    earpiece = described.get("earpiece") or {}
    return bool(earpiece.get("available") and earpiece.get("boxes"))


def earpiece_bounds(described: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """What hornsim.earpiece accepts on any ear, for the dials a study sets.

    Read from the builder each time: its PARAMS table, its reach limit, and the section radii its
    collector check accepts. The collector dials start at 0, which means no collector.
    """
    earpiece = described["earpiece"]
    fields = {
        name: {key: float(earpiece["params"][name][key]) for key in ("minimum", "maximum", "default")}
        for name in _EARPIECE_BUILDER_DIALS
    }
    collector = earpiece["collector"]
    fields[COLLECTOR_REACH] = {"minimum": 0.0, "maximum": float(collector["max_reach_mm"]), "default": 0.0}
    fields[COLLECTOR_MOUTH] = {
        "minimum": 0.0,
        "maximum": _floor_tenth(math.pi * float(collector["section_radius_mm"][1]) ** 2),
        "default": 0.0,
    }
    return fields


def _floor_tenth(value: float) -> float:
    """Round a limit down to one decimal, so a value read from its printed form is still inside it."""
    return math.floor(float(value) * 10 + 1e-9) / 10


@dataclass(frozen=True)
class EarpieceEarLimits:
    """What `hornsim.target.earpiece_boxes` found the configured ear can hold, rounded down to 0.1.

    Each box is one variant that built in this ear: with a canal stem (the throat has to fit inside
    it) or without one. `throat_with_stem_mm2` is None when no variant with a stem built.
    """

    mouth_mm2: float
    throat_mm2: float
    canal_stem_mm: float
    throat_with_stem_mm2: float | None


def earpiece_ear_limits(described: Mapping[str, Any]) -> EarpieceEarLimits:
    boxes = described["earpiece"]["boxes"]
    with_stem = [box["throat_mm2"][1] for box in boxes if box["canal_stem_mm"][1] > 0]
    return EarpieceEarLimits(
        mouth_mm2=_floor_tenth(max(box["mouth_mm2"][1] for box in boxes)),
        throat_mm2=_floor_tenth(max(box["throat_mm2"][1] for box in boxes)),
        canal_stem_mm=_floor_tenth(max(box["canal_stem_mm"][1] for box in boxes)),
        throat_with_stem_mm2=_floor_tenth(max(with_stem)) if with_stem else None,
    )


def earpiece_fixed_dials(described: Mapping[str, Any]) -> dict[str, float]:
    """The builder dials a study does not set, at the builder's defaults."""
    return {
        name: spec["default"]
        for name, spec in described["earpiece"]["params"].items()
        if name not in _EARPIECE_BUILDER_DIALS
    }


def earpiece_builder_parameters(parameters: Mapping[str, float]) -> dict[str, Any]:
    """A study's earpiece parameters as hornsim.earpiece takes them.

    The three builder dials pass through under their own names. The two collector dials become
    the builder's collector: one spine point `collector_reach_mm` straight out from the mouth
    centre along the faceplate normal, with a round cross-section of area `collector_mouth_mm2`.
    The builder blends the mouth outline into that circle. Both 0 means no collector.
    """
    sent: dict[str, Any] = {name: float(parameters[name]) for name in _EARPIECE_BUILDER_DIALS}
    reach, opening = float(parameters[COLLECTOR_REACH]), float(parameters[COLLECTOR_MOUTH])
    if reach > 0 and opening > 0:
        radius = math.sqrt(opening / math.pi)
        sent["collector"] = {
            "spine": [[reach, 0.0, 0.0]],
            "sections": [[radius] * _COLLECTOR_SECTION_POINTS],
        }
    return sent


def _earpiece_family(described: Mapping[str, Any]) -> dict[str, Any]:
    earpiece = described["earpiece"]
    bounds = earpiece_bounds(described)
    limits = earpiece_ear_limits(described)
    collector = earpiece["collector"]
    radius_low, radius_high = collector["section_radius_mm"]
    stem_limit = limits.throat_with_stem_mm2
    if stem_limit is None:
        stem_throat = "no stem fits and canal_stem_mm must be 0."
    elif stem_limit < limits.throat_mm2:
        stem_throat = (
            f"the throat can be at most {stem_limit:g} with a stem, and a wider throat needs canal_stem_mm 0."
        )
    else:
        stem_throat = f"the throat can be at most {stem_limit:g}."
    words = {
        "stem_throat": stem_throat,
        "builder_mouth_max": bounds["mouth_mm2"]["maximum"],
        "max_reach": collector["max_reach_mm"],
        "radius_low": radius_low,
        "radius_high": radius_high,
        "area_low": math.pi * radius_low**2,
    }
    # The ear's own limits where it has them, and the builder's bounds for everything else.
    declared_maximum = {
        **{name: field["maximum"] for name, field in bounds.items()},
        "mouth_mm2": min(bounds["mouth_mm2"]["maximum"], limits.mouth_mm2),
        "throat_mm2": min(bounds["throat_mm2"]["maximum"], limits.throat_mm2),
        "canal_stem_mm": min(bounds["canal_stem_mm"]["maximum"], limits.canal_stem_mm),
    }
    parameters = []
    for name, field in bounds.items():
        unit, note = _EARPIECE_PARAMETER_NOTES[name]
        default = f" Builder default {field['default']:g}." if name in _EARPIECE_BUILDER_DIALS else ""
        if field["default"] > declared_maximum[name]:
            default += " That default is more than this ear holds."
        parameters.append(
            {
                "name": name,
                "kind": "float",
                "unit": unit,
                "minimum": field["minimum"],
                "maximum": declared_maximum[name],
                "description": note.format(**words) + default,
            }
        )
    fixed = ", ".join(f"{name} {value:g}" for name, value in earpiece_fixed_dials(described).items())
    whole_canal = earpiece["whole_canal_is_sample_plus_mm"]
    return {
        "family_id": EARPIECE_FAMILY_ID,
        "description": (
            "In-concha earpiece built by hornsim.earpiece: a seat cast from the concha of the configured "
            "ear with the horn carved inside it, flaring from the throat at the seat floor to a mouth on "
            "the faceplate, an optional soft stem into the canal, and an optional collector that carries "
            "the horn outward past the faceplate. It has no vent. "
            "What a study can ask for: the throat area, the faceplate mouth area, the stem length, and a "
            "collector. mouth_mm2 is always the mouth on the faceplate, which this ear's concha opening "
            f"limits to {declared_maximum['mouth_mm2']:g} mm^2. A larger opening is asked for with "
            "collector_reach_mm and collector_mouth_mm2, which are written into the builder's collector as "
            "one straight section: a spine point collector_reach_mm out from the mouth centre along the "
            "faceplate normal, with a round cross-section of area collector_mouth_mm2, and the builder "
            "blends the mouth outline into that circle. Both 0 means no collector. One without the other "
            "is refused. "
            "What a study cannot ask for: a bent or scooped collector, one that faces the talker, a "
            "cross-section that is not round, more than one section, a hood, a vent, or any other dial "
            f"of the builder. Those stay at the builder's defaults ({fixed}). "
            "Every design is built once and checked by the builder. A design it rejects comes back as a "
            "failed case with the builder's reasons and no score, which makes it ineligible: a mouth "
            "larger than the faceplate allows, a throat too wide for the canal stem, a flare that breaks "
            "through the seat wall, or a collector that touches the ear or the head or reaches too far. "
            "Bounds say what the builder and this ear accept one dial at a time, so a design can be in "
            "bounds and still be rejected. "
            "Acoustics: the profile door of hornsim.acoustics with unified settings. The model is given "
            "the area along the bore as it was built, from the collector's rim (or the faceplate mouth) to "
            "the seat floor, then the stem as a tube at the throat area, with this ear's ear_params, so the "
            "open-ear reference is this ear's own concha, and the same sampled canals as the other family. "
            f"One setting is not the default: the whole canal is each canal sample plus {whole_canal:g} mm, "
            "the canal the spiral family's open ear already has, so both families are compared with the "
            "same open canal and a shorter stem leaves more of it behind the piece. If the builder reports "
            "no area profile, the dial door is used with the same settings, and a collector cannot be scored. "
            "What the model does not see: the direction a collector faces and any directional gain, the "
            "shape of a cross-section (only its area), bends, the head and pinna around a protruding "
            "collector, the open neck between the seat floor and the canal opening (the builder reports "
            "its height as seat_floor_mm, and with a stem the bore runs through it), the removal tab, and "
            "any leak around the seat, which is treated as sealed. "
            "The spiral family's insertion gain is relative to an average concha resonance, not this "
            "ear's concha, so read insertion gain across the two families with that in mind. "
            "Building one design takes a few seconds."
        ),
        "parameters": parameters,
    }


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
    earpiece = earpiece_available(described)
    planning_notes: list[str] = list(_PLANNING_NOTES)
    unsupported: list[tuple[str, str]] = list(_UNSUPPORTED)
    earpiece_assets: list[str] = []
    earpiece_record: dict[str, Any] = dict(described.get("earpiece") or {"available": False})
    if earpiece:
        limits = earpiece_ear_limits(described)
        stem_limit = limits.throat_with_stem_mm2
        planning_notes += list(_EARPIECE_PLANNING_NOTES)
        planning_notes.append(
            f"On the configured ear the earpiece's faceplate mouth can be at most {limits.mouth_mm2:g} "
            "mm^2, and "
            + (
                "no canal stem fits."
                if stem_limit is None
                else f"a throat above {stem_limit:g} mm^2 needs canal_stem_mm 0."
            )
            + " A design the ear cannot hold comes back as a failed case, so keep at least one candidate "
            "well inside these limits."
        )
        earpiece_assets = [
            "earpiece_glb",
            "earpiece_in_ear_glb",
            "earpiece_print_stl",
            "earpiece_preview_png",
        ]
        earpiece_record["ear_limits"] = asdict(limits)
        earpiece_record["fixed_dials"] = earpiece_fixed_dials(described)
    else:
        unsupported.append(_COMPACT_SIZE_UNSUPPORTED)
        if described.get("earpiece") and not earpiece_record.get("reason"):
            earpiece_record["reason"] = "Neither probe build of hornsim.target.earpiece_boxes fits this ear."
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
            },
            *([_earpiece_family(described)] if earpiece else []),
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
        "planning_notes": planning_notes,
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
            *earpiece_assets,
        ],
        "unsupported_requirements": [
            {"requirement": requirement, "reason": reason} for requirement, reason in unsupported
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
        "earpiece": earpiece_record,
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


def _reason_text(reason: Mapping[str, Any]) -> str:
    """One of hornsim.earpiece's reasons as a sentence: the check, its message, and what it says to move."""
    hints: list[str] = []
    move = reason.get("move")
    if isinstance(move, Mapping) and move.get("dial"):
        hints.append(f"move {move['dial']} {move.get('direction') or ''}".strip())
    for name in ("max_ok_mm2", "value_mm", "limit_mm"):
        value = _number(reason.get(name))
        if value is not None:
            hints.append(f"{name} {value:g}")
    if reason.get("alternatives"):
        hints.append("or " + ", ".join(str(item) for item in reason["alternatives"]))
    text = f"{reason.get('check', 'check')}: {reason.get('message', '')}".strip()
    return f"{text} ({'; '.join(hints)})" if hints else text


class HornsimEvaluator:
    """`get_evaluator_capabilities` and `evaluate_experiment` over the hornsim bridge.

    Safe to call from several threads. A patient context is built once per
    audiogram and a device once per family and set of design numbers, however
    many scenarios ask for them and however they interleave.
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
                answer = self._run(
                    "describe",
                    {
                        "ear_mesh": str(self._config.ear_mesh),
                        # With these the bridge can also say what this ear's earpiece limits are.
                        "work_dir": str(self._config.work_dir),
                        "ear_height_mm": self._config.ear_height_mm,
                    },
                )
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
                is_earpiece = spec["family_id"] == EARPIECE_FAMILY_ID
                step = "build-earpiece" if is_earpiece else "build"
                payload = {
                    "work_dir": str(self._config.work_dir),
                    "context_dir": context["context_dir"],
                    "parameters": earpiece_builder_parameters(parameters) if is_earpiece else parameters,
                }
                build = self._builds.get(
                    (context["context_dir"], spec["family_id"], tuple(sorted(parameters.items()))),
                    lambda: self._step(step, payload),
                )
                if not build["ok"]:
                    return finish(
                        "failed", used_version=context["version"], error=build["error"], context=context
                    )
                if is_earpiece and not build["fits"]:
                    refused = any(reason.get("check") == "params" for reason in build["reasons"])
                    reasons = "; ".join(_reason_text(reason) for reason in build["reasons"])
                    return finish(
                        "unsupported" if refused else "failed",
                        used_version=build["version"],
                        error={
                            "code": "bad_parameter" if refused else "geometry_does_not_fit",
                            "message": (
                                f"hornsim.earpiece does not accept these values: {reasons}."
                                if refused
                                else f"This design cannot be built in this ear: {reasons}."
                            )[:1500],
                        },
                        context=context,
                        build=build,
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
                vent_wall = None if is_earpiece else _number(build["design"].get("vent_wall_to_bore_mm"))
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
        # Both build steps report `build_failed`. The message names which one.
        return {"ok": False, "error": {"code": f"{step.partition('-')[0]}_failed", "message": message}}

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
        family_id = spec.get("family_id")
        if family_id == FAMILY_ID:
            fields = parameter_bounds(described)
        elif family_id == EARPIECE_FAMILY_ID and earpiece_available(described):
            # The builder's own bounds. A value inside them that this ear cannot hold goes to the
            # builder and comes back as a failed case with its reasons.
            fields = earpiece_bounds(described)
        else:
            return no("unsupported_family", f"Unknown geometry family '{family_id}'.")
        given = spec.get("parameters", {})
        unknown = sorted(set(given) - set(fields))
        if unknown:
            return no("bad_parameter", f"Not parameters of '{family_id}': {', '.join(unknown)}.")
        for name, bounds in fields.items():
            value = _number(given.get(name))
            if value is None:
                return no("bad_parameter", f"'{name}' must be a number.")
            if "minimum" in bounds and value < bounds["minimum"]:
                return no("out_of_bounds", f"{name}={value:g} is below the minimum {bounds['minimum']:g}.")
            if "maximum" in bounds and value > bounds["maximum"]:
                return no("out_of_bounds", f"{name}={value:g} is above the maximum {bounds['maximum']:g}.")
        if {"mouth_mm2", "throat_mm2"} <= set(fields) and given["mouth_mm2"] <= given["throat_mm2"]:
            # The same rule the server applies before rebuilding an aid (backend/app/main.py), and
            # hornsim.earpiece before building an earpiece.
            return no("out_of_bounds", "mouth_mm2 must be larger than throat_mm2.")
        if family_id == EARPIECE_FAMILY_ID and (given[COLLECTOR_REACH] > 0) != (given[COLLECTOR_MOUTH] > 0):
            return no(
                "bad_parameter",
                f"{COLLECTOR_REACH} and {COLLECTOR_MOUTH} must both be 0 (no collector) or both be above 0.",
            )
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
        if spec.get("family_id") is not None:
            config["family_id"] = spec["family_id"]
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
            if "acoustic_door" in build:
                config["acoustic_door"] = build["acoustic_door"]
        elif build is not None and "reasons" in build:
            # The earpiece builder's own account of why it refused, as it gave it.
            config["candidate_dir"] = build["candidate_dir"]
            extra["build_reasons"] = build["reasons"]
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
            # The earpiece's report nests its geometry, so the bridge names its bore length directly.
            length = build.get("bore_length_mm", build["design"].get("bore_length_mm")) if build else 0.0
            metrics.append({"name": "bore_length_mm", "value": length, "unit": "mm"})
            protrusion = build["protrusion_mm"] if build else 0.0
            metrics.append({"name": "protrusion_mm", "value": protrusion, "unit": "mm"})
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
