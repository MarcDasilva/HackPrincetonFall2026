"""Golden values for the unified acoustic model, taken from the two models it replaced.

    backend/.venv/bin/python backend/tests/golden_acoustics.py      # rewrites data/acoustics_golden.json

The two originals are read straight out of git, so this script needs no scratch files:

    main      backend/hornsim/acoustics.py at commit 80394e6   (profile + volume canals, 35 C)
    marc-sim  backend/hornsim/acoustics.py at commit 2862d60   (design dials + ear geometry, 20 C)

test_acoustics_unified.py imports the helpers below and compares the unified module against the JSON. The
JSON only changes if this script is rerun, and it should not be: both originals are frozen commits.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "data", "acoustics_golden.json")
MAIN_COMMIT, MARC_SIM_COMMIT = "80394e6", "2862d60"
SOURCE = "backend/hornsim/acoustics.py"

FREQS = np.geomspace(100.0, 8000.0, 97)
BANDS = [(500, 1000), (1000, 2000), (2000, 4000), (4000, 8000)]
# The template ear the study pipeline runs on (backend/data/horn_study/contexts/86e4b9e1ca8b0ad5).
EAR_PARAMS = {"concha_depth_mm": 11.995, "opening_area_mm2": 419.0, "bowl_volume_cc": 3.3678, "canal_diameter_mm": 7.5}
# Whole canal, opening to eardrum: shortest, median and longest of that context's 32 samples + main's 9 mm tip.
WHOLE_CANAL_MM = [20.52, 24.765, 29.22]
CANAL_DIAMETER_MM = 7.5


def exp_equiv_mids(throat_mm2, mouth_mm2):
    """flare_mid1/2 that put the piecewise-linear radius on an exponential flare at 1/3 and 2/3."""
    k = np.sqrt(mouth_mm2 / throat_mm2)
    return float((k ** (1 / 3) - 1) / (k - 1)), float((k ** (2 / 3) - 1) / (k - 1))


def _common_designs():
    """The four designs both models can express, written in marc-sim's dials."""
    m1, m2 = exp_equiv_mids(1.0, 22.2)
    c1, c2 = exp_equiv_mids(27.0, 450.0)
    return {
        "alan_default": {"concha_fill": 1.0, "x": {
            "throat_mm2": 1.0, "mouth_mm2": 22.2, "flare_mid1": m1, "flare_mid2": m2, "length_mm": 62.3,
            "canal_stem_mm": 10.0, "vent_count": 1, "vent_diameter_mm": 0.8, "vent_length_mm": 25.68}},
        "wide_in_concha": {"concha_fill": 1.0, "x": {
            "throat_mm2": 27.0, "mouth_mm2": 150.0, "flare_mid1": 0.15, "flare_mid2": 0.45, "length_mm": 22.0,
            "canal_stem_mm": 5.0, "vent_count": 0, "vent_diameter_mm": 0.8, "vent_length_mm": 0.0}},
        "open_concha_short": {"concha_fill": 0.0, "x": {
            "throat_mm2": 30.0, "mouth_mm2": 150.0, "flare_mid1": 0.15, "flare_mid2": 0.45, "length_mm": 10.0,
            "canal_stem_mm": 5.0, "vent_count": 0, "vent_diameter_mm": 0.8, "vent_length_mm": 0.0}},
        "protruding_collector": {"concha_fill": 1.0, "x": {
            "throat_mm2": 27.0, "mouth_mm2": 450.0, "flare_mid1": c1, "flare_mid2": c2, "length_mm": 35.0,
            "canal_stem_mm": 5.0, "vent_count": 0, "vent_diameter_mm": 0.8, "vent_length_mm": 0.0}},
    }


def profile_from_dials(x, n=2001):
    """The bore of a dial design as main's area profile: mouth (s = 0) -> flare -> canal stem at the throat area.

    Returns (s_mm, area_mm2). The radius is piecewise linear in the fraction along the flare, as in marc-sim.
    """
    length, stem = float(x["length_mm"]), float(x["canal_stem_mm"])
    s = np.linspace(0, length, n)
    r_t, r_m = np.sqrt(x["throat_mm2"] / np.pi), np.sqrt(x["mouth_mm2"] / np.pi)
    r = r_t + (r_m - r_t) * np.interp(1 - s / length, [0, 1 / 3, 2 / 3, 1], [0, x["flare_mid1"], x["flare_mid2"], 1])
    area = np.pi * r ** 2
    if stem > 0:
        s, area = np.r_[s, length + stem], np.r_[area, x["throat_mm2"]]
    return s, area


def residual_volume_cc(whole_mm, tip_mm, diameter_mm=CANAL_DIAMETER_MM):
    """main's canal sample (air beyond the tip, cm^3) for a whole canal and a tip depth."""
    return (np.asarray(whole_mm, float) - tip_mm) * np.pi * diameter_mm ** 2 / 4 / 1000.0


def exp_horn(length_mm, mouth_mm2=22.2, throat_mm2=1.0, n=400):
    s = np.linspace(0, length_mm, n)
    return s, mouth_mm2 * (throat_mm2 / mouth_mm2) ** (s / length_mm)


MAIN_NATIVE_VOLUMES_CC = [0.5, 0.7, 0.9]
MARC_SIM_NATIVE = {  # marc-sim's own coil() test design, with two vents and a damper halfway along the flare
    "throat_mm2": 1.0, "mouth_mm2": 22.2, "flare_mid1": 0.182, "flare_mid2": 0.488, "length_mm": 64.0,
    "canal_stem_mm": 6.0, "vent_count": 2, "vent_diameter_mm": 0.8, "vent_length_mm": 20.0,
    "damper_pos": 0.5, "damper_ohm": 1500.0}


def main_native_designs(design_cls):
    """Two designs in main's own parametrisation (profile, vent, concha_fill, 9 mm tip)."""
    s, area = exp_horn(51.0)
    t = np.linspace(0, 12, 60)
    return {"exp_horn_vented": design_cls(s, area, vent_diameter_mm=0.8, vent_length_mm=12.0),
            "canal_wide_tube_concha_open": design_cls(t, np.full(60, 44.2), concha_fill=0.0)}


def band_means(curve_db):
    return [float(np.mean(np.asarray(curve_db)[..., (FREQS >= lo) & (FREQS <= hi)], -1).mean()) for lo, hi in BANDS]


def _load_from_git(commit, tag):
    src = subprocess.run(["git", "show", f"{commit}:{SOURCE}"], capture_output=True, text=True, check=True,
                         cwd=HERE).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src)
    try:
        spec = importlib.util.spec_from_file_location(tag, f.name)
        module = importlib.util.module_from_spec(spec)
        sys.modules[tag] = module             # dataclasses look their module up while the class is built
        spec.loader.exec_module(module)
    finally:
        os.unlink(f.name)
    return module


def generate():
    old_main, old_marc = _load_from_git(MAIN_COMMIT, "acoustics_main"), _load_from_git(MARC_SIM_COMMIT, "acoustics_marc_sim")
    r = lambda a: np.round(np.asarray(a, float), 5).tolist()
    db = lambda p: 20 * np.log10(np.abs(p))
    whole = np.array(WHOLE_CANAL_MM)
    out = {
        "provenance": {
            "written_by": "backend/tests/golden_acoustics.py",
            "main": f"{SOURCE} at commit {MAIN_COMMIT}",
            "marc_sim": f"{SOURCE} at commit {MARC_SIM_COMMIT} (branch marc-sim)",
            "note": "Insertion gain and open-ear gain of the two original models. Do not edit by hand.",
        },
        "freqs_hz": "geomspace(100, 8000, 97)", "bands_hz": BANDS, "ear_params": EAR_PARAMS,
        "whole_canal_mm": WHOLE_CANAL_MM, "canal_diameter_mm": CANAL_DIAMETER_MM,
        "common": {}, "main_native": {}, "marc_sim_native": {},
    }
    canal_marc = {"length_mm": whole - old_marc.CANAL_SAMPLE_TIP_MM}
    for name, d in _common_designs().items():
        x, stem = d["x"], d["x"]["canal_stem_mm"]
        vent = x["vent_count"] > 0
        design = old_main.Design(*profile_from_dials(x), vent_diameter_mm=x["vent_diameter_mm"] if vent else 0.0,
                                 vent_length_mm=x["vent_length_mm"] if vent else 0.0, concha_fill=d["concha_fill"],
                                 tip_length_mm=stem)
        canals = [old_main.Canal(v, CANAL_DIAMETER_MM) for v in residual_volume_cc(whole, stem)]
        out["common"][name] = {
            "x": x, "concha_fill": d["concha_fill"],
            "main_insertion_gain_db": r(old_main.insertion_gain_db(design, canals, FREQS)),
            "marc_sim_insertion_gain_db": r(old_marc.insertion_gain(x, EAR_PARAMS, canal_marc, FREQS)),
        }
    canals = [old_main.Canal(v) for v in MAIN_NATIVE_VOLUMES_CC]
    for name, design in main_native_designs(old_main.Design).items():
        out["main_native"][name] = {
            "insertion_gain_db": r(old_main.insertion_gain_db(design, canals, FREQS)),
            "aided_db": r([db(old_main.aided(design, c, FREQS)) for c in canals]),
            "open_ear_db": r([db(old_main.open_ear(c, FREQS, design.tip_length_mm)) for c in canals]),
        }
    out["main_native"]["volumes_cc"] = MAIN_NATIVE_VOLUMES_CC
    out["marc_sim_native"] = {
        "x": MARC_SIM_NATIVE,
        "insertion_gain_db": r(old_marc.insertion_gain(MARC_SIM_NATIVE, EAR_PARAMS, canal_marc, FREQS)),
        "open_ear_gain_db_theta_0": r(old_marc.open_ear_gain(EAR_PARAMS, canal_marc, FREQS, theta_deg=0)),
        "open_ear_gain_db_theta_90": r(old_marc.open_ear_gain(EAR_PARAMS, canal_marc, FREQS, theta_deg=90)),
    }
    os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
    text = json.dumps(out, indent=1)
    text = re.sub(r"\[[^\[\]{}]*\]", lambda m: " ".join(m.group(0).split()), text)     # one array per line
    with open(GOLDEN, "w") as f:
        f.write(text + "\n")
    print("wrote", GOLDEN, f"({os.path.getsize(GOLDEN) / 1024:.0f} kB)")


if __name__ == "__main__":
    generate()
