"""Builder checks on AudioEar's average ear. Run from backend/: .venv/bin/python -m pytest tests -q

Each build takes a few seconds. Skipped when the AudioEar submodule is not checked out.
"""
import json
import os
import pickle

import numpy as np
import pytest
import trimesh

from hornsim import acoustics as ac
from hornsim import aid, context

AUDIOEAR = os.path.join(context.HERE, "..", "third_party", "AudioEar", "data")
F = np.geomspace(100, 8000, 200)


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    """A context folder with only what aid.build reads: the config, pointing at the average ear."""
    model = os.path.join(AUDIOEAR, "UHM_models", "ear_model.pkl")
    if not os.path.isfile(model):
        pytest.skip("AudioEar submodule not checked out")
    d = tmp_path_factory.mktemp("patient")
    m = pickle.load(open(model, "rb"))
    v, f = np.asarray(m["Mean"], float)[:, 0].reshape(-1, 3), np.asarray(m["Trilist"], np.int64)
    v = v - (v.min(0) + v.max(0)) / 2                    # posed and scaled the way earrecon writes ear.ply
    v[:, 0] *= -1; v[:, 2] *= -1
    trimesh.Trimesh(v * (62.0 / np.ptp(v[:, 1])), f - f.min(), process=False).export(str(d / "ear.ply"))
    cfg = context.load_defaults()
    cfg["patient"]["ear_mesh"] = str(d / "ear.ply")
    cfg["ear_world"]["landmarks_xlsx"] = os.path.join(AUDIOEAR, "55_landmarks.xlsx")
    os.makedirs(d / "context")
    json.dump({"config": cfg}, open(d / "context" / "context.json", "w"))
    return d


def build(ctx, tmp_path, **over):
    return aid.build(str(ctx / "context"), str(tmp_path / "aid"), over, log=lambda m: None)


def band(design, lo, hi):
    ig = ac.insertion_gain_db(ac.Design.from_design_json(design), [ac.Canal(0.7)], F)[0]
    return ig[(F >= lo) & (F <= hi)].mean()


def test_default_design_is_a_coiled_spiral_with_a_vent(ctx, tmp_path):
    d = build(ctx, tmp_path)
    assert d["route"] == "spiral" and d["spiral"]["turns"] >= 2 and d["bore_length_mm"] > 60
    assert d["printable_solid_watertight"]
    assert d["vent_wall_to_bore_mm"] >= aid.DEFAULT["min_wall_mm"] - 0.1
    assert d["acoustic"]["vent_length_mm"] > 0
    json.load(open(tmp_path / "aid" / "design.json"), parse_constant=pytest.fail)     # no NaN / Infinity


def test_no_vent_builds_and_tells_the_acoustic_model(ctx, tmp_path):
    d = build(ctx, tmp_path, vent_diameter_mm=0)
    assert d["printable_solid_watertight"] and d["vent_wall_to_bore_mm"] is None
    assert d["acoustic"]["vent_diameter_mm"] == 0 and d["acoustic"]["vent_length_mm"] == 0
    assert "vent" not in trimesh.load(str(tmp_path / "aid" / "aid.glb")).geometry


def test_a_vent_that_cannot_clear_the_bore_is_refused(ctx, tmp_path):
    with pytest.raises(ValueError, match="no vent route clears the bore"):
        build(ctx, tmp_path, vent_diameter_mm=2.0)
    with pytest.raises(ValueError, match="no vent route clears the bore"):     # no room beside a wide throat
        build(ctx, tmp_path, throat_mm2=10, mouth_mm2=40)


@pytest.mark.parametrize("throat, mouth, wall", [(10, 40, 0.6), (15, 100, 0.6), (20, 150, 0.6), (23.7, 150, 0.4)])
def test_wide_throats_build(ctx, tmp_path, throat, mouth, wall):
    d = build(ctx, tmp_path, throat_mm2=throat, mouth_mm2=mouth, min_wall_mm=wall, vent_diameter_mm=0)
    assert d["printable_solid_watertight"]
    assert d["min_wall_to_skin_side_mm"] >= wall - 0.1
    a = d["acoustic"]
    assert a["area_mm2"][0] == pytest.approx(mouth, rel=1e-3) and a["area_mm2"][-1] == pytest.approx(throat, rel=1e-3)
    assert np.all(np.diff(a["area_mm2"]) <= 1e-6)                       # flares one way only
    assert 0 < d["bore_volume_cc"] < d["shell_volume_cc"]
    json.load(open(tmp_path / "aid" / "design.json"), parse_constant=pytest.fail)


def test_wide_throat_is_closer_to_the_open_ear_than_the_default(ctx, tmp_path):
    narrow = build(ctx, tmp_path / "a")
    wide = build(ctx, tmp_path / "b", throat_mm2=20, mouth_mm2=150, vent_diameter_mm=0)
    assert wide["route"] == "funnel" and wide["bore_length_mm"] < 40
    assert band(wide, 1000, 2000) > band(narrow, 1000, 2000) + 15
    assert band(wide, 2000, 4000) > band(narrow, 2000, 4000) + 10
    assert band(wide, 2000, 4000) < 0                                   # still short of the open ear there


def test_max_path_shortens_the_bore(ctx, tmp_path):
    d = build(ctx, tmp_path, max_path_mm=20)
    assert d["bore_length_mm"] < 20 + 16                                # path + mouth riser + run through the tip
    assert d["printable_solid_watertight"]


def test_a_snugger_tip_makes_room_for_a_wider_throat(ctx, tmp_path):
    over = dict(throat_mm2=30, mouth_mm2=150, min_wall_mm=0.4, vent_diameter_mm=0)
    with pytest.raises(ValueError, match="at most 23.8 mm2"):
        build(ctx, tmp_path, **over)
    d = build(ctx, tmp_path, **over, tip_clearance_mm=0.2)
    assert d["route"] == "funnel" and d["printable_solid_watertight"] and d["min_wall_to_skin_side_mm"] >= 0.3


def test_designs_that_cannot_fit_say_why(ctx, tmp_path):
    with pytest.raises(ValueError, match="throat too wide for the canal tip"):
        build(ctx, tmp_path, throat_mm2=23.7, mouth_mm2=40, vent_diameter_mm=0)       # needs the 0.4 mm wall
    with pytest.raises(ValueError, match="no bore route fits"):
        build(ctx, tmp_path, throat_mm2=10, mouth_mm2=200, vent_diameter_mm=0)
