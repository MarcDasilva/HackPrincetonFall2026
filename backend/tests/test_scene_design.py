"""scene_design's four options, with the sweep and the printable build stubbed.

Run from backend/: .venv/bin/python -m pytest tests/test_scene_design.py -q
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from hornsim import scene_design as sd
from hornsim import target as tg

NB = len(tg.FREQS)


def _design(throat, mouth, stem=0.0):
    return {"throat_mm2": throat, "mouth_mm2": mouth, "flare_mid1": 0.1, "flare_mid2": 0.4, "canal_stem_mm": stem}


def test_four_options_differ_in_shape_aim_and_the_best_is_recommended(tmp_path, monkeypatch):
    """Catches the dashboard offering four look-alikes (all four once came out the same flush piece, same
    throat, stem and aim), a failed build left on the list, aims that ignore the user's talkers, or the top
    performer not marked."""
    d = str(tmp_path)
    os.makedirs(os.path.join(d, "context"))
    json.dump({"canals": [{"length_mm": 20.0}]}, open(os.path.join(d, "context", "canals.json"), "w"))
    # Best first. 1-3 are near copies of 0; 4 is a stemmed design that fails every build, 5 one that builds.
    flat = [_design(60, 220), _design(59, 215), _design(58, 210), _design(60, 200), _design(25, 200, 6.0),
            _design(26, 210, 5.0), _design(10, 40), _design(60, 60), _design(15, 230), _design(40, 120)]
    cones = [_design(50, 500) | {"length_mm": 8.0 + 14}, _design(55, 600) | {"length_mm": 8.0 + 18}]
    J = np.array([100, 101, 102, 103, 104, 110, 120, 121, 125, 126, 112, 140], float)
    mean = np.array([np.full(NB, 10.0 - (j - 100) / 10) for j in J])
    sweeps = iter([{"designs": flat, "mean_db": mean[:10], "worst_db": mean[:10] - 2},
                   {"designs": cones, "mean_db": mean[10:], "worst_db": mean[10:] - 2}])
    box = {"throat_mm2": [7, 60], "mouth_mm2": [20, 240], "length_mm": [8.0, 8.0], "canal_stem_mm": [0.0, 0.0]}
    monkeypatch.setattr(sd, "earpiece_ear_params", lambda _: {"canal_diameter_mm": 7.0})
    monkeypatch.setattr(tg, "earpiece_boxes", lambda *_: [box])
    monkeypatch.setattr(tg, "reach", lambda *_a, **_k: {"earpiece": next(sweeps)})
    monkeypatch.setattr(tg, "triage", lambda *_a, **_k: {"gain_db": np.full(NB, 10.0), "key_bands_hz": [2000.0, 4000.0],
                                                          "triage": "passive-suitable", "why": "", "reach_db": np.full(NB, 10.0)})
    monkeypatch.setattr(sd, "objective", lambda *_a: J)
    monkeypatch.setattr(sd, "_pool", ThreadPoolExecutor)

    def build(_ctx, _aid, params, did, log):
        # The cone's first, fully tilted try is refused, as a tilt toward the face was on a real ear.
        ok = params["canal_stem_mm"] != 6.0 and not (params.get("collector") and params["aim_yaw_deg"] < 45)
        return {"ok": ok, "reasons": [{"message": "touches the ear"}], "geometry": {"bore_length_mm": 8.0}}

    monkeypatch.setattr(sd.epc, "build", build)
    deficit = [5.0] * NB
    scenes = [{"id": "a", "name": "a", "weight": 3, "deficit_db": deficit, "talker_az_deg": 0},
              {"id": "b", "name": "b", "weight": 5, "deficit_db": deficit, "talker_az_deg": 30},
              {"id": "c", "name": "c", "weight": 2, "deficit_db": deficit, "talker_az_deg": 90}]
    r = sd.run(d, {"audiogram_db_hl": {"1000": 30}, "scenes": scenes}, log=lambda m: None)

    opts = r["options"]
    picked = [(o["params"]["throat_mm2"], o["params"].get("collector") is not None) for o in opts]
    assert len(opts) == 4
    assert picked[0] == (60, False)
    assert any(cone for _, cone in picked)                      # one option is a cone
    assert any(o["params"]["canal_stem_mm"] == 5.0 for o in opts)   # the failed stem build was replaced
    assert not {59, 58} & {t for t, _ in picked}                # near copies of option 1 are never offered
    yaws = sorted(o["params"]["aim_yaw_deg"] for o in opts)
    assert len(set(yaws)) == 4                                   # every option faces its own way
    assert 20 < opts[0]["params"]["aim_yaw_deg"] < 40           # recommended: the weighted mean talker
    cone = next(o for o in opts if o["params"].get("collector"))
    assert cone["params"]["aim_yaw_deg"] >= 45                  # a refused tilt falls back to a gentler one
    assert [o["recommended"] for o in opts] == [True, False, False, False]
    assert r["design"] == opts[0]
    assert opts[0]["reason"].startswith("Recommended.")
    assert "cone collector" in cone["reason"]
