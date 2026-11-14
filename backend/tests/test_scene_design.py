"""scene_design's four options, with the sweep and the printable build stubbed.

Run from backend/: .venv/bin/python -m pytest tests/test_scene_design.py -q
"""
import json
import os

import numpy as np

from hornsim import scene_design as sd
from hornsim import target as tg

NB = len(tg.FREQS)


def test_four_distinct_buildable_options(tmp_path, monkeypatch):
    """Catches the dashboard offering four near copies, or a design whose build failed."""
    d = str(tmp_path)
    os.makedirs(os.path.join(d, "context"))
    json.dump({"canals": [{"length_mm": 20.0}]}, open(os.path.join(d, "context", "canals.json"), "w"))
    # Ten swept designs, best objective first: 0 and 1 are near copies, 2 fails its build.
    throats = [10, 10.5, 20, 30, 40, 50, 60, 70, 80, 90]
    designs = [{"throat_mm2": t, "mouth_mm2": 4 * t, "flare_mid1": 0.3, "flare_mid2": 0.6, "canal_stem_mm": 5} for t in throats]
    mean = np.array([np.full(NB, 10.0 - i) for i in range(10)])
    monkeypatch.setattr(sd, "earpiece_ear_params", lambda _: {"canal_diameter_mm": 7.0})
    monkeypatch.setattr(tg, "earpiece_boxes", lambda *_: [{"throat_mm2": [5, 100]}])
    monkeypatch.setattr(tg, "reach", lambda *_a, **_k: {"earpiece": {"designs": designs, "mean_db": mean, "worst_db": mean - 2}})
    monkeypatch.setattr(tg, "triage", lambda *_a, **_k: {"gain_db": np.full(NB, 10.0), "key_bands_hz": [2000.0, 4000.0],
                                                          "triage": "passive-suitable", "why": "", "reach_db": np.full(NB, 10.0)})
    built = []

    def build(_ctx, _aid, params, did, log):
        built.append(params["throat_mm2"])
        return {"ok": params["throat_mm2"] != 20, "reasons": [{"message": "too big"}], "geometry": {"bore_length_mm": 18.0}}

    monkeypatch.setattr(sd.epc, "build", build)
    scene = {"id": "s", "name": "s", "weight": 1, "deficit_db": [5.0] * NB}
    r = sd.run(d, {"audiogram_db_hl": {"1000": 30}, "scenes": [scene]}, log=lambda m: None)

    assert [o["params"]["throat_mm2"] for o in r["options"]] == [10, 30, 40, 50]
    assert 10.5 not in built                 # the near copy is skipped before building
    assert r["design"] == r["options"][0]
    assert r["options"][0]["reason"].startswith("Closest fit")
    assert "than option 1" in r["options"][1]["reason"]
