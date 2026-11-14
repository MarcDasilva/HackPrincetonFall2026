"""The hornsim evaluator: the real pipeline behind the contract, with the bridge process stubbed.

These tests need no backend environment. `FakeBridge` answers the five bridge
commands the way `bridges/hornsim_bridge.py` does. The two tests that run the
real pipeline are skipped unless the backend variables are set.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from helpers import Harness, coordinator_responder, make_request, need, valid_draft

import horn_study.hornsim_evaluator as hornsim_evaluator
from horn_study import earpiece as final_step
from horn_study.contracts import (
    EvaluatorCapabilities,
    EvaluatorHearingInput,
    ExperimentSpec,
    HearingMeasurement,
    StudyState,
)
from horn_study.evaluator_adapter import (
    REAL_EVALUATOR_ENV,
    CallableEvaluator,
    EvaluatorNotConfigured,
    TransientEvaluatorError,
    evaluator_for,
)
from horn_study.hornsim_evaluator import (
    BACKEND_DIR_ENV,
    BASELINE_ID,
    CALIBRATION_REF,
    COLLECTOR_MOUTH,
    COLLECTOR_REACH,
    EAR_MESH_ENV,
    EARPIECE_FAMILY_ID,
    FAMILY_ID,
    FIDELITY,
    WORK_DIR_ENV,
    BridgeProcessError,
    HornsimConfig,
    HornsimEvaluator,
    process_runner,
)
from horn_study.intake import InputRejected, parse_request, validate_request
from horn_study.planner import PlanDraft, build_plan
from horn_study.runner import check_result
from horn_study.workflow import run_study

VERSION = "hornsim-abc1234"
THRESHOLDS = {250: 15, 500: 20, 1000: 30, 2000: 45, 4000: 55, 6000: 55}
DEFAULT_DESIGN = {
    "throat_mm2": 1.0,
    "mouth_mm2": 22.2,
    "vent_diameter_mm": 0.8,
    "min_wall_mm": 0.6,
    "max_path_mm": 130.0,
    "tip_clearance_mm": 0.6,
}
# A design the first version could not build: a wide throat, a large mouth, and no vent.
WIDE_DESIGN = {**DEFAULT_DESIGN, "throat_mm2": 20.0, "mouth_mm2": 150.0, "vent_diameter_mm": 0.0}
# The in-concha earpiece at the builder's defaults, with no collector.
EARPIECE_DEFAULT = {
    "throat_mm2": 27.0,
    "mouth_mm2": 150.0,
    "canal_stem_mm": 5.0,
    COLLECTOR_REACH: 0.0,
    COLLECTOR_MOUTH: 0.0,
}
# What the acoustic sweep pointed at: a wide throat, no stem, and a collector beyond the faceplate.
EARPIECE_COLLECTOR = {
    "throat_mm2": 60.0,
    "mouth_mm2": 300.0,
    "canal_stem_mm": 0.0,
    COLLECTOR_REACH: 10.0,
    COLLECTOR_MOUTH: 450.0,
}
# hornsim.earpiece's own words for a mouth the faceplate cannot hold and a throat too wide for the stem.
MOUTH_FIT = {
    "check": "mouth_fit",
    "message": "the mouth is larger than this concha's opening allows",
    "max_ok_mm2": 304.8,
    "alternatives": ["rim_conformity +"],
    "move": {"dial": "mouth_mm2", "direction": "-"},
}
STEM_THROAT = {
    "check": "stem_throat",
    "message": "the throat does not fit inside the canal stem",
    "max_ok_mm2": 27.3,
    "alternatives": ["canal_stem_mm 0 (no stem: the piece then relies on its fit alone)"],
    "move": {"dial": "throat_mm2", "direction": "-"},
}
BRIDGE = Path(__file__).resolve().parents[1] / "bridges" / "hornsim_bridge.py"

# What `hornsim_bridge.py describe` printed for the backend this adapter was written against.
DESCRIBED: dict[str, Any] = {
    "ok": True,
    "version": VERSION,
    "dependencies": {"pyclarity": "0.9.0"},
    "aid_design_fields": {
        "throat_mm2": {"default": 1.0, "minimum": 0.3, "maximum": 31},
        "mouth_mm2": {"default": 22.2, "minimum": 2, "maximum": 200},
        "vent_diameter_mm": {"default": 0.8, "minimum": 0, "maximum": 2.5},
        "min_wall_mm": {"default": 0.6, "minimum": 0.4, "maximum": 2},
        "max_path_mm": {"default": 130, "minimum": 20, "maximum": 300},
        "tip_clearance_mm": {"default": 0.6, "minimum": 0.2, "maximum": 1.5},
    },
    "aid_defaults": {
        "throat_mm2": 1.0,
        "mouth_mm2": 22.2,
        "max_path_mm": 130,
        "min_wall_mm": 0.6,
        "tip_length_mm": 9.0,
        "tip_clearance_mm": 0.6,
        "vent_diameter_mm": 0.8,
        "vent_offset_mm": 2.2,
    },
    "levels_db_spl": [50, 65, 80],
    "clips": [
        {"name": "clean_1", "type": "clean"},
        {"name": "clean_2", "type": "clean"},
        {"name": "clean_3", "type": "clean"},
        {"name": "babble_1", "type": "babble", "snr_db": 5},
        {"name": "babble_2", "type": "babble", "snr_db": 5},
        {"name": "babble_3", "type": "babble", "snr_db": 5},
        {"name": "babble_4", "type": "babble", "snr_db": 5},
    ],
    "babble_talkers": 6,
    "haspi_seed": 0,
    "reference_db_spl": 65.0,
    "haspi_frequencies_hz": [250.0, 500.0, 1000.0, 2000.0, 4000.0, 6000.0],
    "hornsim_haspi_frequencies_hz": [250.0, 500.0, 1000.0, 2000.0, 4000.0, 6000.0],
    "ceiling_prescriptions": ["nal_r", "half_gain", "full_gain"],
    "canal": {"residual_volume_cc": [0.5, 0.9], "samples": 32, "scored": 5, "assumed_diameter_mm": 7.5},
    "ear_mesh": {
        "file_name": "ear.ply",
        "sha256": "f" * 64,
        "provenance": {"source": "AudioEar average ear. A template, not a person's ear."},
    },
    # hornsim.earpiece.PARAMS (a few of its shaping dials are left out here), and what
    # hornsim.target.earpiece_boxes found on the template ear.
    "earpiece": {
        "available": True,
        "family": "concha_horn_earpiece",
        "params": {
            "throat_mm2": {
                "minimum": 7.0,
                "maximum": 60.0,
                "default": 27.0,
                "meaning": "bore area at the canal",
            },
            "mouth_mm2": {"minimum": 20.0, "maximum": 1500.0, "default": 150.0, "meaning": "mouth area"},
            "hood_mm": {"minimum": 0.0, "maximum": 5.0, "default": 0.0, "meaning": "hood height"},
            "flare_mid1": {"minimum": 0.0, "maximum": 1.0, "default": 0.15, "meaning": "flare"},
            "flare_mid2": {"minimum": 0.0, "maximum": 1.0, "default": 0.45, "meaning": "flare"},
            "wall_mm": {"minimum": 0.8, "maximum": 3.0, "default": 1.2, "meaning": "minimum shell wall"},
            "canal_stem_mm": {"minimum": 0.0, "maximum": 8.0, "default": 5.0, "meaning": "soft stem"},
            "tab_mm": {"minimum": 0.0, "maximum": 6.0, "default": 4.0, "meaning": "removal tab length"},
        },
        "collector": {"max_reach_mm": 35.0, "section_radius_mm": [1.0, 30.0], "clearance_mm": 1.0},
        "stem_wall_mm": 0.8,
        "boxes": [
            {
                "throat_mm2": [7.0, 27.339710067865177],
                "mouth_mm2": [20.0, 304.76],
                "length_mm": [12.4, 12.4],
                "canal_stem_mm": [0.0, 8.0],
            },
            {
                "throat_mm2": [7.0, 60.0],
                "mouth_mm2": [20.0, 304.76],
                "length_mm": [8.9, 8.9],
                "canal_stem_mm": [0.0, 0.0],
            },
        ],
        "ear": {
            "opening_area_mm2": 419.0,
            "concha_depth_mm": 12.0,
            "bowl_volume_cc": 3.37,
            "canal_diameter_mm": 7.5,
        },
        "whole_canal_is_sample_plus_mm": 9.0,
    },
}


class FakeBridge:
    """Answers bridge commands in memory and records every call."""

    def __init__(self, *, build_delay: float = 0.0) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.build_delay = build_delay
        self.does_not_fit: set[float] = set()  # mouth areas that cannot be routed
        self.crashes: set[float] = set()  # mouth areas whose build raises inside a library
        self.vent_wall_to_bore_mm = 0.74
        self.version = VERSION
        # Faceplate mouth areas hornsim.earpiece rejects, with the reasons it gives.
        self.earpiece_rejections: dict[float, list[dict[str, Any]]] = {}
        # What `describe` says about the earpiece. None stands for a bridge that says nothing.
        self.earpiece: dict[str, Any] | None = copy.deepcopy(DESCRIBED["earpiece"])
        # HASPI gained over unaided, by built folder. A collector scores best, the coiled aid next.
        self.gain_over_unaided: dict[str, float] = {}
        self._lock = threading.Lock()

    def count(self, command: str) -> int:
        return sum(1 for name, _ in self.calls if name == command)

    def payloads(self, command: str) -> list[dict[str, Any]]:
        return [payload for name, payload in self.calls if name == command]

    def __call__(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.calls.append((command, copy.deepcopy(payload)))
        return getattr(self, f"_{command.replace('-', '_')}")(payload)

    def _describe(self, payload: dict[str, Any]) -> dict[str, Any]:
        described = {**copy.deepcopy(DESCRIBED), "version": self.version, "earpiece": self.earpiece}
        if self.earpiece is None:
            del described["earpiece"]
        return described

    def _context(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        folder = f"{payload['work_dir']}/contexts/{key}"
        return {
            "ok": True,
            "version": self.version,
            "context_key": key,
            "context_dir": folder,
            "reused": False,
            "seconds": 60.0,
            "audiogram_db_hl": {k: float(v) for k, v in payload["audiogram_db_hl"].items()},
            "ear_mesh": DESCRIBED["ear_mesh"],
            "ear_world": {"bowl_volume_cc": 3.4},
            "assets": {
                "references_json": f"{folder}/references.json",
                "canals_json": f"{folder}/canals.json",
            },
        }

    def _build(self, payload: dict[str, Any]) -> dict[str, Any]:
        time.sleep(self.build_delay)
        parameters = payload["parameters"]
        mouth = parameters["mouth_mm2"]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        folder = f"{payload['work_dir']}/candidates/{key}"
        answer: dict[str, Any] = {
            "ok": True,
            "version": self.version,
            "candidate_key": key,
            "candidate_dir": folder,
            "reused": False,
            "seconds": 120.0,
            "build_seconds": 120.0,
        }
        if mouth in self.crashes:
            return {"ok": False, "error": {"code": "bridge_crashed", "message": "ValueError: boom"}}
        if mouth in self.does_not_fit:
            return {**answer, "fits": False, "error": "no bore route fits this concha with these areas"}
        return {
            **answer,
            "fits": True,
            "design": {
                "bore_length_mm": 50.0 + mouth,
                "printable_solid_watertight": True,
                # hornsim.aid writes null here for a design with no vent.
                "vent_wall_to_bore_mm": self.vent_wall_to_bore_mm if parameters["vent_diameter_mm"] else None,
                **parameters,
            },
            "acoustics_summary": {
                "mean_ig_500_1k_db": -10.5,
                "mean_ig_1k_2k_db": -20.2,
                "mean_ig_2k_4k_db": -25.2,
                "mean_ig_4k_8k_db": -22.5,
                "peak_ig_db": 7.3,
                "peak_ig_hz": 285,
            },
            "protrusion_mm": 2.3,
            "assets": {
                "design_json": f"{folder}/aid/design.json",
                "aid_glb": f"{folder}/aid/aid.glb",
                "aid_print_stl": f"{folder}/aid/aid_print.stl",
                "acoustics_json": f"{folder}/aid/acoustics.json",
            },
        }

    def _build_earpiece(self, payload: dict[str, Any]) -> dict[str, Any]:
        time.sleep(self.build_delay)
        parameters = payload["parameters"]
        mouth = parameters["mouth_mm2"]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        folder = f"{payload['work_dir']}/candidates/{key}"
        answer: dict[str, Any] = {
            "ok": True,
            "version": self.version,
            "candidate_key": key,
            "candidate_dir": folder,
            "family": "concha_horn_earpiece",
            "reused": False,
            "seconds": 3.0,
            "build_seconds": 3.0,
        }
        if mouth in self.crashes:
            return {"ok": False, "error": {"code": "bridge_crashed", "message": "ValueError: boom"}}
        if mouth in self.earpiece_rejections:
            return {**answer, "fits": False, "reasons": copy.deepcopy(self.earpiece_rejections[mouth])}
        collector = parameters.get("collector")
        reach = collector["spine"][-1][0] if collector else 0.0
        opening = math.pi * collector["sections"][-1][0] ** 2 if collector else mouth
        with self._lock:
            self.gain_over_unaided[folder] = 0.25 if collector else 0.0625
        out = f"{folder}/aid/earpiece"
        return {
            **answer,
            "fits": True,
            # hornsim.earpiece's report, without the mouth outline.
            "design": {
                "design_id": "earpiece",
                "family": "concha_horn_earpiece",
                "params": {"flare_mid1": 0.15, "flare_mid2": 0.45, "tab_mm": 4.0, **parameters},
                "ok": True,
                "warnings": [],
                "checks": {"bore_wall_mm": 1.41, "watertight": True},
                "seat_floor_mm": 5.5,
                "geometry": {
                    "mouth_mm2": mouth,
                    "mouth_mm2_max": 320.8,
                    "throat_mm2": parameters["throat_mm2"],
                    "bore_length_mm": 8.9,
                    "canal_stem_mm": parameters["canal_stem_mm"],
                    "proud_of_concha_mm": 5.9 + reach,
                    "collector": bool(collector),
                    "collector_mouth_mm2": round(opening, 1),
                },
                "area_profile_mm2": [[0.0, parameters["throat_mm2"]], [8.9, mouth]],
            },
            "acoustics_summary": {
                "mean_ig_500_1k_db": 0.2,
                "mean_ig_1k_2k_db": 0.8,
                "mean_ig_2k_4k_db": 0.4,
                "mean_ig_4k_8k_db": -0.3,
                "peak_ig_db": 3.4,
                "peak_ig_hz": 8000,
            },
            "acoustic_door": "profile",
            "bore_length_mm": 8.9,
            "protrusion_mm": 5.9 + reach,
            "assets": {
                "design_json": f"{out}/design.json",
                "earpiece_glb": f"{out}/earpiece.glb",
                "earpiece_in_ear_glb": f"{out}/earpiece_in_ear.glb",
                "earpiece_print_stl": f"{out}/earpiece_print.stl",
                "earpiece_preview_png": f"{out}/preview.png",
                "acoustics_json": f"{out}/acoustics.json",
            },
        }

    def _score(self, payload: dict[str, Any]) -> dict[str, Any]:
        # The bridge scores every clip of the type and reports their mean.
        clips = [clip["name"] for clip in DESCRIBED["clips"] if clip["type"] == payload["clip_type"]]
        unaided = 0.5 if payload["clip_type"] == "clean" else 0.25
        gain = self.gain_over_unaided.get(payload["candidate_dir"], 0.125)
        aided = unaided if payload["candidate_dir"] is None else unaided + gain
        return {
            "ok": True,
            "version": self.version,
            "clip_type": payload["clip_type"],
            "level_db_spl": payload["level_db_spl"],
            "haspi_mean": aided,
            "haspi_worst_canal": aided - (0.0 if payload["candidate_dir"] is None else 0.03125),
            "unaided_haspi_mean": unaided,
            "canals_used_cc": [0.5, 0.6, 0.7, 0.8, 0.9],
            "haspi_seed": 0,
            "per_clip": [{"clip": name, "unaided_haspi": unaided} for name in clips],
            "seconds": 5.0,
        }


def make_config(tmp_path: Path) -> HornsimConfig:
    return HornsimConfig(
        backend_dir=tmp_path / "backend",
        python=tmp_path / "backend" / ".venv" / "bin" / "python",
        ear_mesh=tmp_path / "ear.ply",
        work_dir=tmp_path / "work",
    )


def make_evaluator(tmp_path: Path, bridge: FakeBridge | None = None) -> tuple[HornsimEvaluator, FakeBridge]:
    bridge = bridge or FakeBridge()
    return HornsimEvaluator(make_config(tmp_path), run_bridge=bridge), bridge


def hearing(thresholds: dict[int, float] | None = None) -> EvaluatorHearingInput:
    return EvaluatorHearingInput(
        profile_id="entered_test_example",
        source="user_entered_test_results",
        target_ear="right",
        measurements=tuple(
            HearingMeasurement(ear="right", frequency_hz=f, threshold_db_hl=t)
            for f, t in (thresholds or THRESHOLDS).items()
        ),
    )


def make_spec(
    candidate_id: str = "default_horn",
    scenario_id: str = "clean_speech_65_db_spl",
    *,
    parameters: dict[str, float] | None = None,
    baseline: bool = False,
    thresholds: dict[int, float] | None = None,
    family: str = FAMILY_ID,
) -> ExperimentSpec:
    return ExperimentSpec(
        study_id="study_test_001",
        experiment_id=f"{candidate_id}--{scenario_id}",
        candidate_id=candidate_id,
        candidate_kind="baseline" if baseline else "design",
        family_id=None if baseline else family,
        baseline_id=BASELINE_ID if baseline else None,
        parameters={} if baseline else dict(parameters or DEFAULT_DESIGN),
        hearing_input=hearing(thresholds),
        scenario_id=scenario_id,
        canal_config_id="sampled_canals",
        fidelity=FIDELITY,
        calibration_ref=CALIBRATION_REF,
    )


def earpiece_spec(
    candidate_id: str = "earpiece_default",
    scenario_id: str = "clean_speech_65_db_spl",
    *,
    parameters: dict[str, float] | None = None,
) -> ExperimentSpec:
    return make_spec(
        candidate_id, scenario_id, parameters=parameters or EARPIECE_DEFAULT, family=EARPIECE_FAMILY_ID
    )


def as_contract(evaluator: HornsimEvaluator) -> CallableEvaluator:
    """Wrap the evaluator the way `load_evaluator` does."""
    return CallableEvaluator(evaluator.get_evaluator_capabilities, evaluator.evaluate_experiment)


# --------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------


def test_capabilities_validate_against_the_contract_and_come_from_the_backend(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    capabilities = as_contract(evaluator).get_evaluator_capabilities()

    assert capabilities.kind == "real"
    assert capabilities.evaluator_version == VERSION
    # The work directory and ear height let the bridge probe what this ear holds.
    assert bridge.payloads("describe") == [
        {"ear_mesh": str(tmp_path / "ear.ply"), "work_dir": str(tmp_path / "work"), "ear_height_mm": None}
    ]

    family, _ = capabilities.geometry_families
    assert family.family_id == FAMILY_ID
    assert {p.name: (p.minimum, p.maximum, p.unit) for p in family.parameters} == {
        "throat_mm2": (0.3, 31, "mm^2"),
        "mouth_mm2": (2, 200, "mm^2"),
        # 0 is a design with no vent, which hornsim.aid builds.
        "vent_diameter_mm": (0, 2.5, "mm"),
        "min_wall_mm": (0.4, 2, "mm"),
        "max_path_mm": (20, 300, "mm"),
        "tip_clearance_mm": (0.2, 1.5, "mm"),
    }
    assert all(p.description for p in family.parameters)
    assert [(b.baseline_id, b.kind) for b in capabilities.baselines] == [("unaided", "unaided")]

    assert capabilities.hearing_input.required_frequencies_hz == (250, 500, 1000, 2000, 4000, 6000)
    assert capabilities.hearing_input.optional_frequencies_hz == ()
    assert not capabilities.hearing_input.accepts_additional_frequencies
    assert not capabilities.hearing_input.accepts_no_response
    assert capabilities.demo_profiles == ()

    assert [s.scenario_id for s in capabilities.scenarios] == [
        "clean_speech_50_db_spl",
        "clean_speech_65_db_spl",
        "clean_speech_80_db_spl",
        "speech_in_babble_50_db_spl",
        "speech_in_babble_65_db_spl",
        "speech_in_babble_80_db_spl",
    ]
    assert [s.source_level_db_spl for s in capabilities.scenarios] == [50, 65, 80, 50, 65, 80]
    babble = capabilities.scenarios[4].description
    assert babble.startswith("4 Harvard sentences")
    assert "at +5 dB" in babble
    assert "means over the 4 clips" in babble
    names = [m.name for m in capabilities.metrics]
    assert len(names) == len(set(names))
    assert names[:3] == ["haspi_v2_mean", "haspi_v2_worst_canal", "haspi_v2_improvement_over_unaided"]
    assert all(m.unit and m.direction for m in capabilities.metrics)
    informational = [m.name for m in capabilities.metrics if m.direction == "informational"]
    assert informational == ["bore_length_mm", "protrusion_mm"]

    assert not capabilities.supports_seeds
    assert capabilities.calibration.calibration_ref == CALIBRATION_REF
    assert "65 dB SPL" in capabilities.calibration.description
    assert "(level - 65) dB" in capabilities.calibration.source_level_convention
    assert capabilities.default_fidelity in capabilities.fidelity_levels
    unsupported = {u.requirement for u in capabilities.unsupported_requirements}
    assert {"secure_retention", "comfort", "hearing_protection", "music_quality"} <= unsupported
    for simplification in ("eardrum", "concha", "assumed 7.5 mm diameter"):
        assert simplification in capabilities.model_description

    # The mesh identity is part of the snapshot, so cached results never cross ears.
    dumped = capabilities.model_dump(mode="json")
    assert dumped["ear_mesh"]["sha256"] == "f" * 64
    assert dumped["fixed_design_values"] == {"tip_length_mm": 9.0, "vent_offset_mm": 2.2}


def test_capabilities_follow_the_backend_when_it_changes(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    assert evaluator.get_evaluator_capabilities()["evaluator_version"] == VERSION
    bridge.version = "hornsim-def5678"
    assert evaluator.get_evaluator_capabilities()["evaluator_version"] == "hornsim-def5678"


def test_written_text_has_no_em_dash(tmp_path):
    evaluator, _ = make_evaluator(tmp_path)
    assert chr(0x2014) not in json.dumps(evaluator.get_evaluator_capabilities(), ensure_ascii=False)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


def test_design_and_control_results_pass_the_runner_checks(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()
    declared = {m.name: m.unit for m in capabilities.metrics}

    for spec in (make_spec(), make_spec("unaided", baseline=True)):
        result = contract.evaluate_experiment(spec)
        assert check_result(spec, result, capabilities) == []
        assert result.status == "completed"
        assert (result.experiment_id, result.candidate_id, result.spec_hash) == (
            spec.experiment_id,
            spec.candidate_id,
            spec.spec_hash(),
        )
        assert {m.name: m.unit for m in result.metrics} == declared
        assert all(math.isfinite(m.value) for m in result.metrics)
        assert result.provenance.kind == "real"
        assert result.seed is None

    design = contract.evaluate_experiment(make_spec())
    values = {m.name: m.value for m in design.metrics}
    assert values["haspi_v2_mean"] == 0.625
    assert values["haspi_v2_worst_canal"] == 0.59375
    assert values["haspi_v2_improvement_over_unaided"] == 0.125
    assert values["insertion_gain_2000_4000_hz_db"] == -25.2
    assert values["bore_length_mm"] == 72.2
    assert values["protrusion_mm"] == 2.3
    kinds = {a.kind: a.ref for a in design.assets}
    assert kinds["design_json"].endswith("/aid/design.json")
    assert kinds["aid_print_stl"].endswith("/aid/aid_print.stl")
    assert kinds["acoustics_json"].endswith("/aid/acoustics.json")
    assert kinds["references_json"].endswith("/references.json")
    assert design.evaluation_config["level_db_spl"] == 65
    assert design.evaluation_config["haspi_seed"] == 0

    control = contract.evaluate_experiment(make_spec("unaided", baseline=True))
    values = {m.name: m.value for m in control.metrics}
    assert values["haspi_v2_mean"] == values["haspi_v2_worst_canal"] == 0.5
    assert values["haspi_v2_improvement_over_unaided"] == 0
    assert values["insertion_gain_2000_4000_hz_db"] == 0
    assert values["bore_length_mm"] == values["protrusion_mm"] == 0
    assert bridge.payloads("score")[-1]["candidate_dir"] is None


def test_a_wide_throat_design_with_no_vent_is_built_and_scored(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()
    spec = make_spec("wide_funnel", "speech_in_babble_65_db_spl", parameters=WIDE_DESIGN)
    result = contract.evaluate_experiment(spec)

    assert check_result(spec, result, capabilities) == []
    assert result.status == "completed", result.error
    assert bridge.payloads("build")[0]["parameters"] == WIDE_DESIGN
    saved = result.model_dump(mode="json")
    assert saved["design"]["vent_wall_to_bore_mm"] is None
    # A babble scenario is the mean over every babble clip, like a clean one over the clean clips.
    assert [entry["clip"] for entry in saved["haspi_per_clip"]] == [
        "babble_1",
        "babble_2",
        "babble_3",
        "babble_4",
    ]
    assert bridge.payloads("score")[0]["clip_type"] == "babble"
    assert {m.name: m.value for m in result.metrics}["haspi_v2_improvement_over_unaided"] == 0.125


def test_supplied_thresholds_reach_the_model_unmodified(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    odd = {250: 12.5, 500: 20, 1000: 33, 2000: 47.5, 4000: 55, 6000: 61}
    as_contract(evaluator).evaluate_experiment(make_spec("unaided", baseline=True, thresholds=odd))
    (sent,) = bridge.payloads("context")
    assert sent["audiogram_db_hl"] == {
        "250": 12.5,
        "500": 20,
        "1000": 33,
        "2000": 47.5,
        "4000": 55,
        "6000": 61,
    }
    assert sent["side"] == "right"
    assert sent["ear_mesh"] == str(tmp_path / "ear.ply")


def test_a_spec_without_every_haspi_frequency_is_refused_not_filled_in(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    partial = {f: t for f, t in THRESHOLDS.items() if f != 6000}
    spec = make_spec("unaided", baseline=True, thresholds=partial)
    result = as_contract(evaluator).evaluate_experiment(spec)

    assert result.status == "unsupported"
    assert result.error is not None
    assert result.error.code == "missing_thresholds"
    assert "6000" in result.error.message
    assert result.metrics == ()
    assert bridge.count("context") == bridge.count("score") == 0


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"scenario_id": "quiet_conversation"}, "unsupported_scenario"),
        ({"seed": 3}, "seeds_unsupported"),
        ({"calibration_ref": "fixture-cal-v1"}, "calibration_mismatch"),
        ({"ear_mesh_ref": "/somewhere/else.ply"}, "ear_mesh_mismatch"),
        ({"family_id": "conical_horn_fixture"}, "unsupported_family"),
        ({"parameters": {**DEFAULT_DESIGN, "throat_mm2": 0.1}}, "out_of_bounds"),
        ({"parameters": {**DEFAULT_DESIGN, "throat_mm2": 40.0, "mouth_mm2": 150.0}}, "out_of_bounds"),
        ({"parameters": {**DEFAULT_DESIGN, "vent_diameter_mm": -0.1}}, "out_of_bounds"),
        ({"parameters": {**DEFAULT_DESIGN, "tip_clearance_mm": 0.05}}, "out_of_bounds"),
        ({"parameters": {**DEFAULT_DESIGN, "mouth_mm2": 2.0, "throat_mm2": 5.0}}, "out_of_bounds"),
        ({"parameters": {k: v for k, v in DEFAULT_DESIGN.items() if k != "max_path_mm"}}, "bad_parameter"),
    ],
)
def test_specs_outside_the_declared_capabilities_are_unsupported(tmp_path, change, code):
    evaluator, bridge = make_evaluator(tmp_path)
    spec = make_spec().model_copy(update=change)
    result = as_contract(evaluator).evaluate_experiment(spec)

    assert result.status == "unsupported"
    assert result.error is not None
    assert result.error.code == code
    assert bridge.count("build") == 0


# --------------------------------------------------------------------------
# One build per candidate
# --------------------------------------------------------------------------


def test_each_candidate_is_built_once_across_scenarios_and_threads(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path, FakeBridge(build_delay=0.05))
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()
    wide = {**DEFAULT_DESIGN, "mouth_mm2": 40.0}
    specs = [make_spec("unaided", s.scenario_id, baseline=True) for s in capabilities.scenarios]
    specs += [make_spec("default_horn", s.scenario_id) for s in capabilities.scenarios]
    specs += [make_spec("wide_mouth", s.scenario_id, parameters=wide) for s in capabilities.scenarios]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(contract.evaluate_experiment, specs))

    assert all(
        check_result(spec, result, capabilities) == [] for spec, result in zip(specs, results, strict=True)
    )
    assert [r.status for r in results] == ["completed"] * 18
    assert bridge.count("context") == 1
    assert bridge.count("build") == 2
    assert sorted(p["parameters"]["mouth_mm2"] for p in bridge.payloads("build")) == [22.2, 40.0]
    assert bridge.count("score") == 18
    lengths = {r.candidate_id: {m.name: m.value for m in r.metrics}["bore_length_mm"] for r in results}
    assert lengths == {"unaided": 0, "default_horn": 72.2, "wide_mouth": 90.0}


def test_a_different_audiogram_gets_its_own_context(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    contract = as_contract(evaluator)
    contract.evaluate_experiment(make_spec("unaided", baseline=True))
    contract.evaluate_experiment(make_spec("unaided", "speech_in_babble_65_db_spl", baseline=True))
    contract.evaluate_experiment(make_spec("unaided", baseline=True, thresholds={**THRESHOLDS, 4000: 60}))
    assert bridge.count("context") == 2


# --------------------------------------------------------------------------
# Failures stay failures
# --------------------------------------------------------------------------


def test_a_design_that_does_not_fit_the_ear_is_a_failed_case_with_no_score(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    bridge.does_not_fit.add(60.0)
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()
    too_big = {**DEFAULT_DESIGN, "mouth_mm2": 60.0}

    results = []
    for scenario in ("clean_speech_65_db_spl", "speech_in_babble_65_db_spl"):
        spec = make_spec("too_big", scenario, parameters=too_big)
        result = contract.evaluate_experiment(spec)
        assert check_result(spec, result, capabilities) == []
        results.append(result)

    for result in results:
        assert result.status == "failed"
        assert result.metrics == ()
        assert result.error is not None
        assert result.error.code == "geometry_does_not_fit"
        assert "no bore route fits this concha" in result.error.message
        assert not result.error.transient
    assert bridge.count("build") == 1
    assert bridge.count("score") == 0


def test_a_vent_that_cuts_into_the_bore_is_a_failed_case_with_no_score(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    bridge.vent_wall_to_bore_mm = -0.97
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()
    spec = make_spec("vent_large", parameters={**DEFAULT_DESIGN, "vent_diameter_mm": 2.0})
    result = contract.evaluate_experiment(spec)

    assert check_result(spec, result, capabilities) == []
    assert result.status == "failed"
    assert result.metrics == ()
    assert result.error is not None
    assert result.error.code == "vent_intersects_bore"
    assert "-0.97" in result.error.message
    assert bridge.count("score") == 0
    # The built files are still referenced, so the overlap can be inspected.
    assert "design_json" in {asset.kind for asset in result.assets}


def test_a_build_that_crashes_is_a_failed_case_and_is_not_repeated(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    bridge.crashes.add(30.0)
    contract = as_contract(evaluator)
    spec = make_spec("crashing", parameters={**DEFAULT_DESIGN, "mouth_mm2": 30.0})
    first = contract.evaluate_experiment(spec)
    second = contract.evaluate_experiment(spec)

    assert first.status == second.status == "failed"
    assert first.error is not None
    assert first.error.code == "build_failed"
    assert "boom" in first.error.message
    assert bridge.count("build") == 1


def test_a_backend_that_changed_under_a_frozen_plan_is_caught_by_the_runner(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()
    bridge.version = "hornsim-def5678"
    spec = make_spec("unaided", baseline=True)
    issues = check_result(spec, contract.evaluate_experiment(spec), capabilities)
    assert any("evaluator version 'hornsim-def5678'" in issue for issue in issues)


# --------------------------------------------------------------------------
# The in-concha earpiece family
# --------------------------------------------------------------------------


def test_the_earpiece_family_is_declared_with_the_builders_dials_and_this_ears_limits(tmp_path):
    evaluator, _ = make_evaluator(tmp_path)
    capabilities = as_contract(evaluator).get_evaluator_capabilities()

    assert [f.family_id for f in capabilities.geometry_families] == [FAMILY_ID, EARPIECE_FAMILY_ID]
    family = capabilities.family(EARPIECE_FAMILY_ID)
    assert family is not None
    assert {p.name: (p.minimum, p.maximum, p.unit) for p in family.parameters} == {
        # The builder's own range.
        "throat_mm2": (7, 60, "mm^2"),
        # The builder allows 1500. This ear's faceplate holds 304.76, declared rounded down.
        "mouth_mm2": (20, 304.7, "mm^2"),
        "canal_stem_mm": (0, 8, "mm"),
        # The builder's reach limit, and the area of its largest section radius (30 mm).
        COLLECTOR_REACH: (0, 35, "mm"),
        COLLECTOR_MOUTH: (0, 2827.4, "mm^2"),
    }
    described = {p.name: p.description for p in family.parameters}
    assert "at most 27.3 with a stem" in described["throat_mm2"]
    assert "Builder default 150" in described["mouth_mm2"]
    assert "means no collector" in described[COLLECTOR_MOUTH]

    # The family says how a collector is asked for, which door scores it, and what the model misses.
    for phrase in (
        "one straight section",
        "Both 0 means no collector",
        "What a study cannot ask for",
        "hood_mm 0",
        "profile door of hornsim.acoustics",
        "canal sample plus 9 mm",
        "What the model does not see",
        "direction a collector faces",
        "failed case with the builder's reasons",
    ):
        assert phrase in family.description, phrase

    notes = " ".join(capabilities.planning_notes)
    assert "the only family that can have an opening larger than the concha opening" in notes
    assert "Model prediction, not a measured fact" in notes
    assert "at most 304.7 mm^2" in notes
    assert "protrusion_mm" in notes

    # Outer size now varies and is reported, so a size preference is no longer out of reach.
    assert "compact_size" not in {u.requirement for u in capabilities.unsupported_requirements}
    assert capabilities.metric("protrusion_mm").direction == "informational"
    assert {"earpiece_print_stl", "earpiece_glb", "design_json"} <= set(capabilities.output_assets)

    dumped = capabilities.model_dump(mode="json")
    assert dumped["earpiece"]["ear_limits"] == {
        "mouth_mm2": 304.7,
        "throat_mm2": 60.0,
        "canal_stem_mm": 8.0,
        "throat_with_stem_mm2": 27.3,
    }
    assert dumped["earpiece"]["fixed_dials"]["tab_mm"] == 4.0
    assert "throat_mm2" not in dumped["earpiece"]["fixed_dials"]


def test_the_ears_limits_follow_what_the_probe_builds_found(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    assert bridge.earpiece is not None
    # An ear where only the variant with a stem built: no wide throat, and a smaller opening.
    bridge.earpiece["boxes"] = [
        {"throat_mm2": [7.0, 21.24], "mouth_mm2": [20.0, 188.09], "canal_stem_mm": [0.0, 8.0]}
    ]
    capabilities = as_contract(evaluator).get_evaluator_capabilities()
    family = capabilities.family(EARPIECE_FAMILY_ID)
    assert family is not None
    bounds = {p.name: (p.minimum, p.maximum) for p in family.parameters}
    assert bounds["throat_mm2"] == (7, 21.2)
    assert bounds["mouth_mm2"] == (20, 188)
    described = {p.name: p.description for p in family.parameters}
    assert "the throat can be at most 21.2." in described["throat_mm2"]
    assert "That default is more than this ear holds." in described["throat_mm2"]


@pytest.mark.parametrize(
    ("earpiece", "reason"),
    [
        (None, None),
        (
            {"available": False, "reason": "ModuleNotFoundError: No module named 'hornsim.earpiece'"},
            "hornsim.earpiece",
        ),
        ({**DESCRIBED["earpiece"], "boxes": []}, "Neither probe build"),
    ],
)
def test_without_a_usable_earpiece_builder_only_the_spiral_family_is_declared(tmp_path, earpiece, reason):
    evaluator, bridge = make_evaluator(tmp_path)
    bridge.earpiece = earpiece
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()

    assert [f.family_id for f in capabilities.geometry_families] == [FAMILY_ID]
    assert "compact_size" in {u.requirement for u in capabilities.unsupported_requirements}
    assert "concha_horn_earpiece" not in " ".join(capabilities.planning_notes)
    saved = capabilities.model_dump(mode="json")["earpiece"]
    assert saved["available"] is False or saved["boxes"] == []
    if reason is not None:
        assert reason in saved["reason"]

    result = contract.evaluate_experiment(earpiece_spec())
    assert result.status == "unsupported"
    assert result.error is not None
    assert result.error.code == "unsupported_family"
    assert bridge.count("build-earpiece") == 0


def test_an_earpiece_result_passes_the_runner_checks(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()
    spec = earpiece_spec()
    result = contract.evaluate_experiment(spec)

    assert check_result(spec, result, capabilities) == []
    assert result.status == "completed", result.error
    assert {m.name: m.unit for m in result.metrics} == {m.name: m.unit for m in capabilities.metrics}
    values = {m.name: m.value for m in result.metrics}
    assert values["haspi_v2_mean"] == 0.5625
    assert values["haspi_v2_improvement_over_unaided"] == 0.0625
    assert values["insertion_gain_2000_4000_hz_db"] == 0.4
    # The builder's own numbers: the flare inside the seat, and how far the print stands proud.
    assert values["bore_length_mm"] == 8.9
    assert values["protrusion_mm"] == 5.9

    # With no collector asked for, the builder is sent its three dials and nothing else.
    (sent,) = bridge.payloads("build-earpiece")
    assert sent["parameters"] == {"throat_mm2": 27.0, "mouth_mm2": 150.0, "canal_stem_mm": 5.0}
    assert sent["work_dir"] == str(tmp_path / "work")
    assert bridge.count("build") == 0
    # The score step is pointed at the folder that build made.
    assert bridge.payloads("score")[0]["candidate_dir"] == result.evaluation_config["candidate_dir"]

    kinds = {a.kind: a.ref for a in result.assets}
    assert kinds["design_json"].endswith("/aid/earpiece/design.json")
    assert kinds["earpiece_print_stl"].endswith("/aid/earpiece/earpiece_print.stl")
    assert kinds["earpiece_in_ear_glb"].endswith("/aid/earpiece/earpiece_in_ear.glb")
    assert kinds["acoustics_json"].endswith("/aid/earpiece/acoustics.json")
    assert kinds["references_json"].endswith("/references.json")
    assert result.evaluation_config["family_id"] == EARPIECE_FAMILY_ID
    assert result.evaluation_config["acoustic_door"] == "profile"
    saved = result.model_dump(mode="json")
    assert saved["design"]["checks"] == {"bore_wall_mm": 1.41, "watertight": True}
    assert saved["design"]["geometry"]["mouth_mm2_max"] == 320.8
    assert saved["build_seconds"] == 3.0


def test_the_collector_dials_become_the_builders_collector(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()
    spec = earpiece_spec("collector", parameters=EARPIECE_COLLECTOR)
    result = contract.evaluate_experiment(spec)

    assert check_result(spec, result, capabilities) == []
    assert result.status == "completed", result.error
    (sent,) = bridge.payloads("build-earpiece")
    collector = sent["parameters"].pop("collector")
    assert sent["parameters"] == {"throat_mm2": 60.0, "mouth_mm2": 300.0, "canal_stem_mm": 0.0}
    # One spine point straight out from the mouth centre, and twelve equal radii: a round rim.
    assert collector["spine"] == [[10.0, 0.0, 0.0]]
    (section,) = collector["sections"]
    assert len(section) == 12
    assert len(set(section)) == 1
    assert math.pi * section[0] ** 2 == pytest.approx(450.0)
    # The reported parameters stay the study's own, and the collector shows in how far it protrudes.
    assert result.parameters == EARPIECE_COLLECTOR
    assert {m.name: m.value for m in result.metrics}["protrusion_mm"] == 15.9
    assert result.model_dump(mode="json")["design"]["geometry"]["collector"] is True


@pytest.mark.parametrize(
    ("change", "code"),
    [
        # Outside what hornsim.earpiece accepts on any ear.
        ({"throat_mm2": 70.0}, "out_of_bounds"),
        ({"throat_mm2": 5.0}, "out_of_bounds"),
        ({"mouth_mm2": 2000.0}, "out_of_bounds"),
        ({"canal_stem_mm": 9.0}, "out_of_bounds"),
        ({COLLECTOR_REACH: 40.0, COLLECTOR_MOUTH: 450.0}, "out_of_bounds"),
        ({COLLECTOR_REACH: 10.0, COLLECTOR_MOUTH: 3000.0}, "out_of_bounds"),
        ({"mouth_mm2": 25.0}, "out_of_bounds"),  # not larger than the throat
        # Half a collector.
        ({COLLECTOR_REACH: 10.0}, "bad_parameter"),
        ({COLLECTOR_MOUTH: 450.0}, "bad_parameter"),
        # A dial of the other family, and a missing one.
        ({"vent_diameter_mm": 0.8}, "bad_parameter"),
        ({COLLECTOR_REACH: None}, "bad_parameter"),
    ],
)
def test_earpiece_specs_the_builder_could_never_take_are_unsupported(tmp_path, change, code):
    evaluator, bridge = make_evaluator(tmp_path)
    parameters = {name: value for name, value in {**EARPIECE_DEFAULT, **change}.items() if value is not None}
    result = as_contract(evaluator).evaluate_experiment(earpiece_spec(parameters=parameters))

    assert result.status == "unsupported"
    assert result.error is not None
    assert result.error.code == code
    assert result.metrics == ()
    assert bridge.count("build-earpiece") == 0


def test_each_earpiece_is_built_once_across_scenarios_and_threads(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path, FakeBridge(build_delay=0.05))
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()
    scenarios = [s.scenario_id for s in capabilities.scenarios]
    specs = [make_spec("unaided", s, baseline=True) for s in scenarios]
    specs += [make_spec("default_horn", s) for s in scenarios]
    specs += [earpiece_spec("earpiece_default", s) for s in scenarios]
    specs += [earpiece_spec("collector", s, parameters=EARPIECE_COLLECTOR) for s in scenarios]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(contract.evaluate_experiment, specs))

    assert all(
        check_result(spec, result, capabilities) == [] for spec, result in zip(specs, results, strict=True)
    )
    assert [r.status for r in results] == ["completed"] * 24
    assert bridge.count("context") == 1
    assert bridge.count("build") == 1
    assert bridge.count("build-earpiece") == 2
    assert bridge.count("score") == 24
    # Every scenario of a candidate was scored on that candidate's one build.
    folders: dict[str, set[Any]] = {}
    for result in results:
        folders.setdefault(result.candidate_id, set()).add(result.evaluation_config.get("candidate_dir"))
    assert all(len(found) == 1 for found in folders.values())
    assert len({next(iter(found)) for found in folders.values()}) == 4
    protrusion = {r.candidate_id: {m.name: m.value for m in r.metrics}["protrusion_mm"] for r in results}
    assert protrusion == {"unaided": 0, "default_horn": 2.3, "earpiece_default": 5.9, "collector": 15.9}


def test_the_same_numbers_in_another_family_are_another_build(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    contract = as_contract(evaluator)
    contract.evaluate_experiment(earpiece_spec())
    contract.evaluate_experiment(earpiece_spec("again", "speech_in_babble_65_db_spl"))
    contract.evaluate_experiment(
        earpiece_spec("no_stem", parameters={**EARPIECE_DEFAULT, "canal_stem_mm": 0.0})
    )
    assert bridge.count("build-earpiece") == 2
    assert bridge.count("build") == 0


@pytest.mark.parametrize(
    ("parameters", "reasons", "expected"),
    [
        # Inside the builder's range, beyond what this ear's faceplate holds.
        (
            {**EARPIECE_DEFAULT, "mouth_mm2": 400.0},
            [MOUTH_FIT],
            "mouth_fit: the mouth is larger than this concha's opening allows "
            "(move mouth_mm2 -; max_ok_mm2 304.8; or rim_conformity +)",
        ),
        (
            {**EARPIECE_DEFAULT, "throat_mm2": 30.0, "mouth_mm2": 151.0},
            [STEM_THROAT],
            "stem_throat: the throat does not fit inside the canal stem (move throat_mm2 -; max_ok_mm2 27.3; "
            "or canal_stem_mm 0 (no stem: the piece then relies on its fit alone))",
        ),
        (
            {**EARPIECE_COLLECTOR, "mouth_mm2": 299.0, COLLECTOR_REACH: 30.0},
            [
                {
                    "check": "collector_reach",
                    "message": "the collector reaches too far from the ear",
                    "value_mm": 36.2,
                    "limit_mm": 35.0,
                    "move": {"dial": "collector", "direction": "shorten the spine or shrink the sections"},
                },
                {"check": "collector_clearance", "message": "the collector touches the ear on its back side"},
            ],
            "collector_reach: the collector reaches too far from the ear (move collector shorten the spine or "
            "shrink the sections; value_mm 36.2; limit_mm 35); collector_clearance: the collector touches "
            "the ear on its back side",
        ),
    ],
)
def test_an_earpiece_the_builder_rejects_is_a_failed_case_with_its_reasons(
    tmp_path, parameters, reasons, expected
):
    evaluator, bridge = make_evaluator(tmp_path)
    bridge.earpiece_rejections[parameters["mouth_mm2"]] = reasons
    contract = as_contract(evaluator)
    capabilities = contract.get_evaluator_capabilities()

    results = []
    for scenario in ("clean_speech_65_db_spl", "speech_in_babble_65_db_spl"):
        spec = earpiece_spec("rejected", scenario, parameters=parameters)
        result = contract.evaluate_experiment(spec)
        assert check_result(spec, result, capabilities) == []
        results.append(result)

    for result in results:
        assert result.status == "failed"
        assert result.metrics == ()
        assert result.error is not None
        assert result.error.code == "geometry_does_not_fit"
        assert result.error.message == f"This design cannot be built in this ear: {expected}."
        assert not result.error.transient
        # The builder's reasons are kept as it gave them, for whoever plans the next study.
        assert result.model_dump(mode="json")["build_reasons"] == reasons
    assert bridge.count("build-earpiece") == 1
    assert bridge.count("score") == 0


def test_values_the_earpiece_builder_refuses_are_unsupported_not_failed(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    tiny = {**EARPIECE_COLLECTOR, COLLECTOR_MOUTH: 2.0}
    bridge.earpiece_rejections[tiny["mouth_mm2"]] = [
        {"check": "params", "message": "each section is 12 inner radii in mm, each within 1..30"}
    ]
    contract = as_contract(evaluator)
    spec = earpiece_spec("tiny_rim", parameters=tiny)
    result = contract.evaluate_experiment(spec)

    assert check_result(spec, result, contract.get_evaluator_capabilities()) == []
    assert result.status == "unsupported"
    assert result.error is not None
    assert result.error.code == "bad_parameter"
    assert "each within 1..30" in result.error.message
    assert result.metrics == ()
    assert bridge.count("score") == 0


def test_an_earpiece_build_that_crashes_is_a_failed_case_and_is_not_repeated(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path)
    bridge.crashes.add(200.0)
    contract = as_contract(evaluator)
    spec = earpiece_spec("crashing", parameters={**EARPIECE_DEFAULT, "mouth_mm2": 200.0})
    first = contract.evaluate_experiment(spec)
    second = contract.evaluate_experiment(spec)

    assert first.status == second.status == "failed"
    assert first.error is not None
    assert first.error.code == "build_failed"
    assert "hornsim build-earpiece step failed" in first.error.message
    assert "boom" in first.error.message
    assert first.metrics == ()
    assert bridge.count("build-earpiece") == 1
    assert bridge.count("score") == 0


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_missing_configuration_names_every_variable(monkeypatch):
    with pytest.raises(EvaluatorNotConfigured) as raised:
        HornsimConfig.from_env({})
    message = str(raised.value)
    for name in (BACKEND_DIR_ENV, EAR_MESH_ENV, WORK_DIR_ENV):
        assert name in message


def test_configuration_that_points_nowhere_says_what_is_wrong(tmp_path):
    env = {
        BACKEND_DIR_ENV: str(tmp_path / "backend"),
        EAR_MESH_ENV: str(tmp_path / "ear.ply"),
        WORK_DIR_ENV: str(tmp_path / "work"),
    }
    with pytest.raises(EvaluatorNotConfigured) as raised:
        HornsimConfig.from_env(env)
    message = str(raised.value)
    assert "has no hornsim/ package" in message
    assert "backend interpreter" in message
    assert "is not a file" in message


def test_complete_configuration_is_read_from_the_environment(tmp_path):
    backend = tmp_path / "backend"
    (backend / "hornsim").mkdir(parents=True)
    (backend / ".venv" / "bin").mkdir(parents=True)
    (backend / ".venv" / "bin" / "python").write_text("")
    (tmp_path / "ear.ply").write_text("ply")
    config = HornsimConfig.from_env(
        {
            BACKEND_DIR_ENV: str(backend),
            EAR_MESH_ENV: str(tmp_path / "ear.ply"),
            WORK_DIR_ENV: str(tmp_path / "work"),
            "HORNSIM_EAR_HEIGHT_MM": "62",
        }
    )
    assert config.python == backend.resolve() / ".venv" / "bin" / "python"
    assert config.ear_height_mm == 62
    assert config.bridge == BRIDGE


def test_the_module_loads_by_path_and_reports_missing_configuration(monkeypatch):
    for name in (BACKEND_DIR_ENV, EAR_MESH_ENV, WORK_DIR_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(hornsim_evaluator, "_default", None)
    evaluator = evaluator_for("real", env={REAL_EVALUATOR_ENV: "horn_study.hornsim_evaluator"})
    with pytest.raises(EvaluatorNotConfigured, match="HORNSIM_BACKEND_DIR is not set"):
        evaluator.get_evaluator_capabilities()


# --------------------------------------------------------------------------
# Intake and the whole workflow with the real capabilities
# --------------------------------------------------------------------------


def hornsim_request(thresholds: dict[int, float], **overrides: Any) -> dict[str, Any]:
    request = make_request(evaluation_mode="real", needs=False, **overrides)
    request["hearing_profile"]["measurements"] = [
        {
            "ear": "right",
            "frequency_hz": frequency,
            "threshold_db_hl": threshold,
            "measurement_type": "air_conduction",
            "status": "measured",
        }
        for frequency, threshold in thresholds.items()
    ]
    return request


def test_a_request_missing_a_required_frequency_is_rejected_at_intake(tmp_path):
    evaluator, _ = make_evaluator(tmp_path)
    capabilities = as_contract(evaluator).get_evaluator_capabilities()

    # The usual clinical set, which stops short of what HASPI needs.
    without_6000 = {250: 15, 500: 20, 1000: 30, 2000: 45, 4000: 55, 8000: 50}
    with pytest.raises(InputRejected) as raised:
        validate_request(parse_request(hornsim_request(without_6000)), capabilities)
    (issue,) = raised.value.issues
    assert issue.code == "hearing.required_frequency_missing"
    assert "6000 Hz" in issue.message

    package = validate_request(parse_request(hornsim_request({**THRESHOLDS, 8000: 50})), capabilities)
    assert [m.frequency_hz for m in package.hearing_input.measurements] == [250, 500, 1000, 2000, 4000, 6000]
    assert [m.threshold_db_hl for m in package.hearing_input.measurements] == [15, 20, 30, 45, 55, 55]
    assert [m.frequency_hz for m in package.hearing_input.retained_but_unused] == [8000]


def hornsim_draft() -> dict[str, Any]:
    def design(candidate_id: str, mouth: float) -> dict[str, Any]:
        values = {**DEFAULT_DESIGN, "mouth_mm2": mouth}
        return {
            "candidate_id": candidate_id,
            "kind": "design",
            "family_id": FAMILY_ID,
            "baseline_id": "",
            "parameters": [{"name": name, "value": value, "choice": ""} for name, value in values.items()],
            "label": f"Mouth {mouth:g} mm^2",
            "rationale": "Mouth area sweep.",
        }

    draft = valid_draft(needs=False)
    draft["hypotheses"][0].update(
        candidate_ids=["mouth22", "mouth40"],
        metric="haspi_v2_mean",
        varied_parameter="mouth_mm2",
    )
    draft["candidates"] = [draft["candidates"][0], design("mouth22", 22.2), design("mouth40", 40.0)]
    draft["scenario_ids"] = [
        "clean_speech_50_db_spl",
        "clean_speech_65_db_spl",
        "speech_in_babble_50_db_spl",
        "speech_in_babble_65_db_spl",
    ]
    draft["selection"] = {
        "primary_metric": "haspi_v2_mean",
        "reference_candidate_id": "unaided",
        "tie_breaker_metrics": ["haspi_v2_worst_canal"],
        "constraints": [],
    }
    return draft


async def test_a_study_runs_end_to_end_on_the_hornsim_evaluator(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path, FakeBridge(build_delay=0.02))
    harness = Harness(
        tmp_path / "studies",
        evaluator=as_contract(evaluator),
        coordinator=coordinator_responder(hornsim_draft()),
    )
    outcome = await run_study(hornsim_request(THRESHOLDS), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert bridge.count("context") == 1
    assert bridge.count("build") == 2
    assert bridge.count("score") == 12  # 3 candidates x 4 scenarios
    report = outcome.report
    assert report is not None
    assert report.result_kind == "real"
    assert report.evaluator_version == VERSION
    assert report.experiments_completed == 12
    # The stub scores both designs identically, and bore length is informational, so nothing in
    # the plan can separate them: the study reports a tie instead of forcing a winner.
    assert report.selected_candidate_id is None
    assert report.selection.reason_code == "tie"
    saved = json.loads((outcome.directory / "experiment_results.json").read_text())
    assert all(record["outcome"] == "completed" for record in saved["records"])
    assert saved["records"][-1]["result"]["design"]["printable_solid_watertight"] is True


def both_families_draft() -> dict[str, Any]:
    def candidate(candidate_id: str, family: str, values: dict[str, float], label: str) -> dict[str, Any]:
        return {
            "candidate_id": candidate_id,
            "kind": "design",
            "family_id": family,
            "baseline_id": "",
            "parameters": [{"name": name, "value": value, "choice": ""} for name, value in values.items()],
            "label": label,
            "rationale": "Compare a flush mouth with a collector, next to the coiled aid.",
        }

    draft = valid_draft(needs=False)
    draft["hypotheses"][0].update(
        candidate_ids=["earpiece_flush", "earpiece_collector"],
        metric="haspi_v2_mean",
        varied_parameter=COLLECTOR_MOUTH,
    )
    draft["candidates"] = [
        draft["candidates"][0],
        candidate("wide_funnel", FAMILY_ID, WIDE_DESIGN, "Coiled aid, wide funnel"),
        candidate("earpiece_flush", EARPIECE_FAMILY_ID, EARPIECE_DEFAULT, "Earpiece, flush mouth"),
        candidate("earpiece_collector", EARPIECE_FAMILY_ID, EARPIECE_COLLECTOR, "Earpiece with a collector"),
    ]
    draft["scenario_ids"] = [
        "clean_speech_50_db_spl",
        "clean_speech_80_db_spl",
        "speech_in_babble_50_db_spl",
        "speech_in_babble_80_db_spl",
    ]
    draft["selection"] = {
        "primary_metric": "haspi_v2_mean",
        "reference_candidate_id": "unaided",
        "tie_breaker_metrics": ["haspi_v2_worst_canal"],
        "constraints": [{"metric": "protrusion_mm", "bound": "max", "value": 20}],
    }
    return draft


def both_families_request(**overrides: Any) -> dict[str, Any]:
    budget = {
        "max_evaluation_cases": 16,
        "max_parallel_evaluations": 4,
        "max_research_tool_calls_per_agent": 6,
    }
    return hornsim_request(THRESHOLDS, budget=budget, **overrides)


def plan_of(draft: dict[str, Any], capabilities: EvaluatorCapabilities, request: dict[str, Any]):
    package = validate_request(parse_request(request), capabilities)
    findings = frozenset({"hearing-F1", "context-F1", "design-F1"})
    return build_plan(PlanDraft.model_validate(draft), package, findings, plan_version=1)


def test_a_plan_with_candidates_from_both_families_is_valid(tmp_path):
    evaluator, _ = make_evaluator(tmp_path)
    capabilities = as_contract(evaluator).get_evaluator_capabilities()

    plan, errors = plan_of(both_families_draft(), capabilities, both_families_request())
    assert errors == []
    assert plan is not None
    assert {c.candidate_id: c.family_id for c in plan.candidates} == {
        "unaided": None,
        "wide_funnel": FAMILY_ID,
        "earpiece_flush": EARPIECE_FAMILY_ID,
        "earpiece_collector": EARPIECE_FAMILY_ID,
    }
    assert len(plan.experiments) == 16
    by_family = {e.family_id for e in plan.experiments}
    assert by_family == {None, FAMILY_ID, EARPIECE_FAMILY_ID}
    collector_spec = next(e for e in plan.experiments if e.candidate_id == "earpiece_collector")
    assert collector_spec.parameters == EARPIECE_COLLECTOR
    assert [c.metric for c in plan.selection_rule.constraints] == ["protrusion_mm"]

    # A faceplate mouth beyond what this ear holds is caught before anything is frozen.
    too_wide = both_families_draft()
    too_wide["candidates"][2]["parameters"][1]["value"] = 450.0
    _, errors = plan_of(too_wide, capabilities, both_families_request())
    assert any("mouth_mm2=450 is above the maximum 304.7 mm^2" in error for error in errors)

    # A dial of one family is not a dial of the other.
    mixed = both_families_draft()
    mixed["candidates"][1]["parameters"].append({"name": COLLECTOR_REACH, "value": 10.0, "choice": ""})
    _, errors = plan_of(mixed, capabilities, both_families_request())
    assert any(f"'{COLLECTOR_REACH}' is not a parameter of family '{FAMILY_ID}'" in error for error in errors)


def test_a_size_preference_can_be_planned_as_a_limit_on_protrusion(tmp_path):
    evaluator, _ = make_evaluator(tmp_path)
    capabilities = as_contract(evaluator).get_evaluator_capabilities()
    request = both_families_request(
        needs_profile={
            "activities": [],
            "goals": [],
            "priorities": ["compact_size"],
            "requirements": [],
            "free_text": "",
        }
    )
    draft = both_families_draft()
    draft["hypotheses"][0]["user_goals"] = []
    draft["needs_coverage"] = [need("compact_size", metric_names=["protrusion_mm"])]
    plan, errors = plan_of(draft, capabilities, request)
    assert errors == []
    assert plan is not None

    # Without the limit an informational metric cannot stand for the need.
    draft["selection"]["constraints"] = []
    _, errors = plan_of(draft, capabilities, request)
    assert any("'protrusion_mm' is informational" in error for error in errors)


async def test_a_study_with_both_families_completes_and_can_select_an_earpiece(tmp_path):
    evaluator, bridge = make_evaluator(tmp_path, FakeBridge(build_delay=0.02))
    harness = Harness(
        tmp_path / "studies",
        evaluator=as_contract(evaluator),
        coordinator=coordinator_responder(both_families_draft()),
    )
    outcome = await run_study(both_families_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    assert bridge.count("context") == 1
    assert bridge.count("build") == 1
    assert bridge.count("build-earpiece") == 2
    assert bridge.count("score") == 16  # 4 candidates x 4 scenarios
    report = outcome.report
    assert report is not None
    assert report.experiments_completed == 16
    # The stub scores the collector best, and at 15.9 mm it is inside the 20 mm limit.
    assert report.selection.reason_code == "selected"
    assert report.selected_candidate_id == "earpiece_collector"
    ranked = {c.candidate_id: (c.eligible, c.rank) for c in report.candidates if c.kind == "design"}
    assert ranked == {"earpiece_collector": (True, 1), "wide_funnel": (True, 2), "earpiece_flush": (True, 3)}

    saved = json.loads((outcome.directory / "results.json").read_text())
    selected = saved["selected_candidate"]
    assert selected["family_id"] == EARPIECE_FAMILY_ID
    assert selected["parameters"] == EARPIECE_COLLECTOR
    # The names the final step (`horn-study earpiece`) locks: the throat and the faceplate mouth.
    assert final_step.locked_params(selected["parameters"]) == {"throat_mm2": 60.0, "mouth_mm2": 300.0}
    records = json.loads((outcome.directory / "experiment_results.json").read_text())["records"]
    assert all(record["outcome"] == "completed" for record in records)
    built = [r["result"]["design"]["family"] for r in records if "earpiece" in r["result"]["candidate_id"]]
    assert built == ["concha_horn_earpiece"] * 8


async def test_an_earpiece_that_protrudes_past_the_plans_limit_is_not_selected(tmp_path):
    evaluator, _ = make_evaluator(tmp_path)
    draft = both_families_draft()
    draft["selection"]["constraints"] = [{"metric": "protrusion_mm", "bound": "max", "value": 8}]
    harness = Harness(
        tmp_path / "studies", evaluator=as_contract(evaluator), coordinator=coordinator_responder(draft)
    )
    outcome = await run_study(both_families_request(), harness.deps)

    assert outcome.state is StudyState.COMPLETED
    report = outcome.report
    assert report is not None
    collector = next(c for c in report.candidates if c.candidate_id == "earpiece_collector")
    assert not collector.eligible
    assert any(
        "protrusion_mm mean 15.9 exceeds the limit 8" in reason for reason in collector.ineligibility_reasons
    )
    assert report.selected_candidate_id == "wide_funnel"


# --------------------------------------------------------------------------
# The bridge process
# --------------------------------------------------------------------------


def script_config(tmp_path: Path, script: str) -> HornsimConfig:
    bridge = tmp_path / "bridge.py"
    bridge.write_text(script)
    return HornsimConfig(
        backend_dir=tmp_path,
        python=Path(sys.executable),
        ear_mesh=tmp_path / "ear.ply",
        work_dir=tmp_path / "work",
        bridge=bridge,
        timeout_seconds=30,
    )


def test_the_process_runner_passes_json_both_ways_and_withholds_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-for-the-backend")
    script = (
        "import json, os, sys\n"
        "print('progress chatter', file=sys.stderr)\n"
        "json.dump({'ok': True, 'command': sys.argv[1], 'payload': json.load(sys.stdin),\n"
        "           'has_key': 'ANTHROPIC_API_KEY' in os.environ,\n"
        "           'pythonpath': os.environ['PYTHONPATH'], 'cwd': os.getcwd()}, sys.stdout)\n"
    )
    answer = process_runner(script_config(tmp_path, script))("score", {"level_db_spl": 65})
    assert answer["command"] == "score"
    assert answer["payload"] == {"level_db_spl": 65}
    assert answer["has_key"] is False
    assert answer["pythonpath"] == str(tmp_path)
    assert Path(answer["cwd"]).resolve() == tmp_path.resolve()


def test_a_bridge_that_dies_without_an_answer_is_a_transient_failure(tmp_path):
    run = process_runner(
        script_config(tmp_path, "import sys\nprint('Killed', file=sys.stderr)\nsys.exit(137)\n")
    )
    with pytest.raises(BridgeProcessError, match="exited with code 137") as raised:
        run("build", {})
    assert isinstance(raised.value, TransientEvaluatorError)
    assert "Killed" in str(raised.value)


def test_the_bridge_script_starts_without_the_backend_environment():
    done = subprocess.run(
        [sys.executable, str(BRIDGE), "no-such-command"],
        input="{}",
        capture_output=True,
        text=True,
        check=False,
    )
    answer = json.loads(done.stdout)
    assert answer["ok"] is False
    assert answer["error"]["code"] == "usage"


# --------------------------------------------------------------------------
# Opt-in: the real backend
# --------------------------------------------------------------------------

_BACKEND_CONFIGURED = all(os.environ.get(name) for name in (BACKEND_DIR_ENV, EAR_MESH_ENV, WORK_DIR_ENV))


@pytest.mark.skipif(
    not _BACKEND_CONFIGURED,
    reason=f"set {BACKEND_DIR_ENV}, {EAR_MESH_ENV}, and {WORK_DIR_ENV} to run the real hornsim pipeline",
)
def test_the_real_backend_scores_the_control_the_default_and_a_wide_design():
    """Minutes on first run (one context and two aid builds), seconds once they exist in the work dir."""
    evaluator = evaluator_for("real", env={REAL_EVALUATOR_ENV: "horn_study.hornsim_evaluator"})
    capabilities = evaluator.get_evaluator_capabilities()
    assert capabilities.kind == "real"
    assert capabilities.evaluator_version.startswith("hornsim-")
    assert capabilities.hearing_input.required_frequencies_hz == (250, 500, 1000, 2000, 4000, 6000)
    declared = {m.name for m in capabilities.metrics}

    scenario = "speech_in_babble_65_db_spl"
    control_spec = make_spec("unaided", scenario, baseline=True)
    design_spec = make_spec("default_horn", scenario)
    wide_spec = make_spec("wide_funnel", scenario, parameters=WIDE_DESIGN)
    control = evaluator.evaluate_experiment(control_spec)
    design = evaluator.evaluate_experiment(design_spec)
    wide = evaluator.evaluate_experiment(wide_spec)

    for spec, result in ((control_spec, control), (design_spec, design), (wide_spec, wide)):
        assert check_result(spec, result, capabilities) == []
        assert result.status == "completed", result.error
        assert {m.name for m in result.metrics} == declared
    control_values = {m.name: m.value for m in control.metrics}
    design_values = {m.name: m.value for m in design.metrics}
    wide_values = {m.name: m.value for m in wide.metrics}
    # The wide throat with no vent builds, and attenuates far less than the default across speech.
    for band in ("insertion_gain_1000_2000_hz_db", "insertion_gain_2000_4000_hz_db"):
        assert wide_values[band] > design_values[band] + 10
    assert wide_values["bore_length_mm"] < design_values["bore_length_mm"]
    assert len(control.model_dump(mode="json")["haspi_per_clip"]) >= 4
    assert 0 <= control_values["haspi_v2_mean"] <= 1
    assert 0 <= design_values["haspi_v2_worst_canal"] <= design_values["haspi_v2_mean"] <= 1
    assert design_values["haspi_v2_improvement_over_unaided"] == pytest.approx(
        design_values["haspi_v2_mean"] - control_values["haspi_v2_mean"]
    )
    assert design_values["bore_length_mm"] > 0
    for asset in design.assets:
        assert Path(asset.ref).is_file(), asset.ref
    assert control.evaluation_config["audiogram_db_hl"] == {str(f): float(t) for f, t in THRESHOLDS.items()}


@pytest.mark.skipif(
    not _BACKEND_CONFIGURED,
    reason=f"set {BACKEND_DIR_ENV}, {EAR_MESH_ENV}, and {WORK_DIR_ENV} to run the real hornsim pipeline",
)
def test_the_real_backend_builds_and_scores_earpieces_and_reports_what_the_ear_cannot_hold():
    """A few minutes on first run: each earpiece builds in seconds, each scored scenario takes about half a minute."""
    evaluator = evaluator_for("real", env={REAL_EVALUATOR_ENV: "horn_study.hornsim_evaluator"})
    capabilities = evaluator.get_evaluator_capabilities()
    family = capabilities.family(EARPIECE_FAMILY_ID)
    assert family is not None, capabilities.model_dump(mode="json")["earpiece"]
    bounds = {p.name: (p.minimum, p.maximum) for p in family.parameters}
    limits = capabilities.model_dump(mode="json")["earpiece"]["ear_limits"]
    # The faceplate mouth is bounded by this ear, well inside the builder's own 1500 mm^2.
    assert bounds["mouth_mm2"][1] == limits["mouth_mm2"] < 1500
    assert bounds["throat_mm2"][0] > 0
    declared = {m.name for m in capabilities.metrics}

    scenario = "speech_in_babble_65_db_spl"
    control_spec = make_spec("unaided", scenario, baseline=True)
    default_spec = earpiece_spec("earpiece_default", scenario)
    wide_open = {
        "throat_mm2": bounds["throat_mm2"][1],
        "mouth_mm2": min(300.0, bounds["mouth_mm2"][1]),
        "canal_stem_mm": 0.0,
        COLLECTOR_REACH: 10.0,
        COLLECTOR_MOUTH: 450.0,
    }
    collector_spec = earpiece_spec("earpiece_collector", scenario, parameters=wide_open)
    control = evaluator.evaluate_experiment(control_spec)
    default = evaluator.evaluate_experiment(default_spec)
    collector = evaluator.evaluate_experiment(collector_spec)

    for spec, result in ((control_spec, control), (default_spec, default), (collector_spec, collector)):
        assert check_result(spec, result, capabilities) == []
        assert result.status == "completed", result.error
        assert {m.name for m in result.metrics} == declared
    control_values = {m.name: m.value for m in control.metrics}
    default_values = {m.name: m.value for m in default.metrics}
    collector_values = {m.name: m.value for m in collector.metrics}
    for values in (default_values, collector_values):
        assert 0 <= values["haspi_v2_worst_canal"] <= values["haspi_v2_mean"] <= 1
        assert values["haspi_v2_improvement_over_unaided"] == pytest.approx(
            values["haspi_v2_mean"] - control_values["haspi_v2_mean"]
        )
        assert values["bore_length_mm"] > 0
    # The collector stands further out of the ear, and its wider throat and opening pass more of 2 to 8 kHz.
    assert collector_values["protrusion_mm"] > default_values["protrusion_mm"] > 0
    for band in ("insertion_gain_2000_4000_hz_db", "insertion_gain_4000_8000_hz_db"):
        assert collector_values[band] > default_values[band]

    # What was scored is what was built: the builder's own report and area profile.
    for result in (default, collector):
        saved = result.model_dump(mode="json")
        assert saved["design"]["checks"]["watertight"] is True
        assert result.evaluation_config["acoustic_door"] == "profile"
        files = {asset.kind: Path(asset.ref) for asset in result.assets}
        for kind in (
            "design_json",
            "earpiece_print_stl",
            "earpiece_glb",
            "earpiece_in_ear_glb",
            "acoustics_json",
        ):
            assert files[kind].is_file(), files[kind]
        report = json.loads(files["design_json"].read_text())
        model_input = json.loads(files["acoustics_json"].read_text())["model_input"]
        geometry = report["geometry"]
        assert saved["design"]["geometry"] == geometry
        # Mouth (or collector rim) first, throat last, and the stem added as a tube at the throat area.
        assert model_input["s_mm"][0] == 0
        assert model_input["area_mm2"][0] == pytest.approx(geometry["collector_mouth_mm2"], abs=0.05)
        assert model_input["area_mm2"][-1] == geometry["throat_mm2"]
        built_length = report["area_profile_mm2"][-1][0]
        assert model_input["s_mm"][-1] == pytest.approx(built_length + geometry["canal_stem_mm"])
        assert model_input["tip_length_mm"] == geometry["canal_stem_mm"]
        assert model_input["ear_params"]["opening_area_mm2"] > 0
    collector_geometry = collector.model_dump(mode="json")["design"]["geometry"]
    assert collector_geometry["collector"] is True
    assert collector_geometry["collector_mouth_mm2"] == pytest.approx(450.0, abs=1.0)
    assert collector_values["protrusion_mm"] == collector_geometry["proud_of_concha_mm"]

    # In the builder's range, but more than this ear holds: a failed case with the builder's reason.
    too_wide = {**EARPIECE_DEFAULT, "throat_mm2": 30.0, "mouth_mm2": bounds["mouth_mm2"][1] + 150.0}
    rejected_spec = earpiece_spec("too_wide", scenario, parameters=too_wide)
    rejected = evaluator.evaluate_experiment(rejected_spec)
    assert check_result(rejected_spec, rejected, capabilities) == []
    assert rejected.status == "failed"
    assert rejected.metrics == ()
    assert rejected.error is not None
    assert rejected.error.code == "geometry_does_not_fit"
    assert "mouth_fit: the mouth is larger than this concha's opening allows" in rejected.error.message
    if limits["throat_with_stem_mm2"] is not None and limits["throat_with_stem_mm2"] < 30.0:
        assert "stem_throat: the throat does not fit inside the canal stem" in rejected.error.message
    checks = {reason["check"] for reason in rejected.model_dump(mode="json")["build_reasons"]}
    assert "mouth_fit" in checks
