"""Spec 07 acceptance checks 1-5 and spec 02's design_bounds corners, on the validation ear.

    AUDIOEAR_DIR=... .venv/bin/python -m hornsim.test_acoustics        (or pytest)

Needs data/patients/d60d88e7550d (ear mesh, context.json, canals.json, waves/runs.json).
"""
import json
import os
import time
from functools import lru_cache
from itertools import product

import numpy as np

from . import acoustics as A
from . import ear_world as ew

PATIENT = os.path.join(os.path.dirname(__file__), "..", "data", "patients", "d60d88e7550d")
F = np.geomspace(160, 8000, 200)


@lru_cache(None)
def validation_ear():
    cfg = json.load(open(os.path.join(PATIENT, "context", "context.json")))["config"]
    P, E = cfg["patient"], cfg["ear_world"]
    mesh, world = ew.build(P["ear_mesh"], E["landmarks_xlsx"], tuple(E["concha_rim_landmarks"]), E["voxel_mm"],
                           E["fit_tolerance_mm"], E["faceplate_protrusion_mm"], E["canal_opening_diameter_mm"],
                           P["ear_height_mm"])
    return world, ew.ear_params(world, mesh)


def canals():
    c = json.load(open(os.path.join(PATIENT, "context", "canals.json")))["canals"]
    return {"length_mm": np.array([k["length_mm"] for k in c])}


def coil(**kw):
    """aid.py's default coil (1 -> 22.2 mm2, exponential-equivalent flare, 6 mm tip, 0.8 mm vent)."""
    return {"throat_mm2": 1.0, "mouth_mm2": 22.2, "flare_mid1": 0.182, "flare_mid2": 0.488, "length_mm": 64.0,
            "canal_stem_mm": 6.0, "vent_count": 1, "vent_diameter_mm": 0.8, "vent_length_mm": 20.0} | kw


def test_flare_beats_straight_tube_at_high_frequencies():
    """Handoff checkpoint 1: a model where flaring buys nothing above 2 kHz is not modelling a horn."""
    _, ep = validation_ear()
    hi = F >= 2000
    horn = A.insertion_gain(coil(), ep, canals(), F)[:, hi].mean()
    straight = A.insertion_gain(coil(mouth_mm2=1.0), ep, canals(), F)[:, hi].mean()
    print(f"  2-8 kHz mean over canals: flared {horn:.1f} dB, straight {straight:.1f} dB")
    assert horn > straight + 3


def test_open_ear_peak_matches_published_range_and_wave_sim():
    """The open ear is what the device must beat; a peak outside 10-20 dB near 2.5-3 kHz mis-states
    every insertion gain. Cross-checked against spec 03's wave run on the same ear, 90 deg, 25 mm canal."""
    _, ep = validation_ear()
    f = np.geomspace(1000, 6000, 600)
    whole_25mm = {"length_mm": 25.0 - A.CANAL_SAMPLE_TIP_MM}           # wavesim.CANAL_LEN_MM
    g = A.open_ear_gain(ep, whole_25mm, f, theta_deg=90)
    run = next(r for r in json.load(open(os.path.join(PATIENT, "waves", "runs.json"))) if r["az"] == 90)
    w_db = np.array(run["transfer"]["eardrum_db"])
    w_f = np.array(run["transfer"]["freqs_hz"])[w_db.argmax()]
    print(f"  open ear 90 deg, 25 mm canal: {g.max():.1f} dB at {f[g.argmax()]:.0f} Hz "
          f"(wave sim {w_db.max():.1f} dB at {w_f:.0f} Hz)")
    assert 10 <= g.max() <= 20 and 2500 <= f[g.argmax()] <= 3000
    assert abs(g.max() - w_db.max()) < 2 and abs(f[g.argmax()] / w_f - 1) < 0.2
    peaks = f[A.open_ear_gain(ep, canals(), f, theta_deg=90).argmax(-1)]
    print(f"  over the 32 canals: peak {peaks.min():.0f}-{peaks.max():.0f} Hz")


def test_large_vent_restores_the_open_ear_at_low_frequencies():
    """A big vent must hand the low end back to the open ear; if it does not, own-voice boom and the
    vent trade-off in spec 08 are meaningless."""
    _, ep = validation_ear()
    g = A.insertion_gain(coil(vent_diameter_mm=5.0, vent_length_mm=15.0), ep, canals(), [160, 250])
    print(f"  5 mm vent, 160-250 Hz: worst |G| {np.abs(g).max():.2f} dB")
    assert np.abs(g).max() < 0.5


def test_exponential_horn_cutoff():
    """f_c = c ln(Sm/St) / (4 pi L): 453 Hz for 1 -> 22.2 mm2 over 186.8 mm. The infinite exponential
    horn's throat resistance is rho*c/St * sqrt(1 - (fc/f)^2), so it crosses 0.5 at fc / sqrt(0.75).
    Areas are scaled x100 so wall losses (which this formula ignores) do not blur the crossing."""
    L, n = 0.1868, 400
    f = np.linspace(100, 1500, 2801)
    for scale in (100, 1):
        st, sm = 1e-6 * scale, 22.2e-6 * scale
        fc = A.C * np.log(sm / st) / (4 * np.pi * L)
        r = np.sqrt(st * (sm / st) ** ((np.arange(n) + 0.5) / n) / np.pi)
        a, b, c, d = A.horn(r, L, 2 * np.pi * f)
        q = fc / f
        z_mouth = A.RHO * A.C / sm * (np.sqrt(np.maximum(1 - q ** 2, 0)) + 1j * q)    # infinite-horn continuation
        res = ((d * z_mouth + b) / (c * z_mouth + a)).real * st / (A.RHO * A.C)
        f_model = f[np.argmax(res > 0.5)] * np.sqrt(0.75)
        print(f"  areas x{scale}: formula {fc:.0f} Hz, model {f_model:.0f} Hz")
        if scale == 100:
            assert abs(f_model / fc - 1) < 0.03


def test_bore_segments_converge():
    """BORE_SEGMENTS steps the flare; too few would put the horn's resonances in the wrong place."""
    _, ep = validation_ear()
    x = coil(mouth_mm2=150.0)
    coarse = A.insertion_gain(x, ep, canals(), F)
    fine = 20 * np.log10(np.abs(_with_segments(x, ep, 160) / _with_segments(x, ep, A.BORE_SEGMENTS)))
    print(f"  {A.BORE_SEGMENTS} vs 160 segments: max diff {np.abs(fine).max():.2f} dB")
    assert np.abs(fine).max() < 0.25 and np.isfinite(coarse).all()


def _with_segments(x, ep, n):
    keep = A.BORE_SEGMENTS
    A.BORE_SEGMENTS = n
    try:
        return A._aid(x, ep, canals(), 2 * np.pi * F)
    finally:
        A.BORE_SEGMENTS = keep


def test_thousand_designs_by_32_canals_by_200_freqs_is_fast():
    """Spec 08's search calls this thousands of times; minutes here makes the search unusable."""
    _, ep = validation_ear()
    b = ew.design_bounds(ep)
    rng = np.random.default_rng(0)
    x = {k: rng.uniform(lo, hi, (1000, 1)) for k, (lo, hi) in b.items()}
    t = time.time()
    g = A.insertion_gain(x, ep, canals(), F)
    dt = time.time() - t
    print(f"  {g.shape}: {dt:.2f} s")
    assert g.shape == (1000, 32, 200) and np.isfinite(g).all() and dt < 5


def test_design_bounds_corners_fit_the_ear():
    """Spec 02: every corner of design_bounds must build. The fit is checked with aid.py's own spiral
    clearance test at the longest and shortest coil the bounds allow, with the fattest bore profile;
    a corner that fails here would make spec 08 hand spec 09 a design that cannot be printed."""
    world, ep = validation_ear()
    b = ew.design_bounds(ep)
    for k, (lo, hi) in b.items():
        assert lo <= hi, k
    assert b["flare_mid1"][1] <= b["flare_mid2"][0]          # earpiece.py: the bore never narrows
    # residual canal never vanishes, whatever the canal sample
    assert canals()["length_mm"].min() + A.CANAL_SAMPLE_TIP_MM - b["canal_stem_mm"][1] >= 2.0
    # throat + vent side by side in the tip, each with its wall
    r_t = np.sqrt(b["throat_mm2"][1] / np.pi)
    assert r_t + b["vent_diameter_mm"][1] <= ep["vent_room_mm"] + 1e-9
    names = ("throat_mm2", "mouth_mm2", "flare_mid1", "flare_mid2", "canal_stem_mm")
    for which in ("longest", "shortest"):
        sp = ep["coil"][which]
        for corner in product(*(b[k] for k in names)):
            assert ew.coil_fits(world, sp, **dict(zip(names, corner))), (which, corner)
    # Keefe's large-radius loss expansion holds for rv >~ 2; the narrowest channel at 160 Hz
    r_min = min(np.sqrt(b["throat_mm2"][0] / np.pi), b["vent_diameter_mm"][0] / 2) * 1e-3
    assert r_min * np.sqrt(2 * np.pi * 160 * A.RHO / 1.81e-5) > 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            print(name)
            fn()
    print("ok")
