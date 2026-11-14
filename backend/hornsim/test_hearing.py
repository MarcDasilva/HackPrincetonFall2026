"""Hearing-model and baseline checks (specs 04, 05). Plain asserts:

    python -m hornsim.test_hearing            (from backend/; needs the validation patient's waves/)
"""
import os

import numpy as np
from clarity.evaluator.haspi import eb

from . import runner, scenes, scoring

PATIENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "patients", "d60d88e7550d")
FS = runner.FS
PLACEHOLDER = {250: 15, 500: 20, 1000: 30, 2000: 45, 4000: 55, 6000: 55}   # defaults.yaml
NORMAL = {f: 0 for f in PLACEHOLDER}
ISO389_7_1K = 2.4   # dB SPL, free-field binaural threshold at 1 kHz (ISO 389-7:2005)


def tone_sl(level_db, hl, f=1000):
    """dB SL of a steady tone in Kates' ear model (HASPI/HASQI); 0 = below threshold."""
    x = np.sqrt(2) * np.sin(2 * np.pi * f * np.arange(int(0.5 * FS)) / FS)   # RMS 1 = level_db
    np.random.seed(0)
    sl = eb.ear_model(x, FS, x, FS, np.array([hl[k] for k in sorted(hl)], float), 0, level_db)[5]
    return float(sl[np.argmin(np.abs(eb.center_frequency(32) - f))])


def main():
    ag, normal = scoring.audiogram(PLACEHOLDER), scoring.audiogram(NORMAL)
    x = scenes.clip("clean_1")

    # A wrong level convention (eardrum vs free field) moves every absolute audibility by 10-20 dB.
    h, i = tone_sl(ISO389_7_1K, NORMAL), tone_sl(ISO389_7_1K + PLACEHOLDER[1000], PLACEHOLDER)
    print(f"calibration, 1 kHz tone at threshold: healthy {h:+.1f} dB SL, impaired {i:+.1f} dB SL")
    assert 0 < h <= 6 and 0 < i <= 6 and abs(h - i) < 1

    s = {(a, L): scoring.sii(x, None, FS, g, L) for a, g in (("normal", normal), ("placeholder", ag)) for L in (50, 65)}
    print("SII clean speech:", {f"{a} {L} dB": round(v, 3) for (a, L), v in s.items()})
    assert s["normal", 65] > 0.95 and s["placeholder", 65] < s["normal", 65] - 0.2
    assert s["placeholder", 50] < s["placeholder", 65]

    # Without seeding HASPI/HASQI drift between calls and design rankings flip on noise.
    y = x + 0.1 * np.random.default_rng(1).standard_normal(len(x))
    for f in (scoring.haspi, scoring.hasqi):
        a, b = f(x, y, FS, ag, 65, 0), f(x, y, FS, ag, 65, 0)
        print(f"{f.__name__} repeat: {a:.6f} {b:.6f}")
        assert a == b

    ss = {s["condition"]: s for s in scenes.build(PATIENT) if s["clip"] == "clean_1"}
    waves = os.path.join(PATIENT, "waves")
    r = {c: runner.run_scene(ss[c], PLACEHOLDER, waves, 0) for c in ("C1", "C2", "C3", "C4")}
    hf = scoring.SII_FREQS >= 2000
    d2 = np.array(r["C2"]["deficit_db"])
    print("C2 deficit_db by band:", dict(zip(scoring.SII_FREQS.astype(int).tolist(), d2.round(1).tolist())))
    assert d2[hf].mean() > d2[~hf].mean() and scoring.SII_FREQS[np.argmax(d2)] >= 2000
    tot = {c: sum(v["deficit_weighted"]) for c, v in r.items()}
    print("weighted deficit:", {c: round(v, 2) for c, v in tot.items()})
    assert tot["C1"] > tot["C2"]
    assert runner.run_scene(ss["C4"], PLACEHOLDER, waves, 0) == r["C4"]

    for p in (None, ["C6", "C2", "C1"], ["C1", "C2", "C3", "C4", "C5"]):
        w = sum(scenes.condition_weights(p).values())
        assert abs(w - 1) < 1e-12, (p, w)
    sc = scenes.build(PATIENT)
    assert len(sc) == 96 and abs(sum(s["weight"] for s in sc) - 1) < 1e-12
    print("weights sum to 1; 96 scenes")

    # Head shadow: the far side must lose more than the aided side. KNOWN FAILURE with the flat-head
    # wave simulation, which puts 90 deg 2-4 dB BELOW the front at 0.8-3 kHz (a real head is above it).
    assert tot["C4"] > tot["C3"], "head shadow: far-side talker must lose more than aided-side talker"
    print("all checks passed")


if __name__ == "__main__":
    main()
