"""Target and triage checks (spec 06). Plain asserts:

    python -m hornsim.test_target            (from backend/; needs the validation patient's scenes/ and waves/,
                                              and AUDIOEAR_DIR / LANDMARKS_XLSX for ear_params, ~1 min)
"""
import json
import os

import numpy as np

from . import manifest, runner, scoring
from . import target as T

PATIENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "patients", "d60d88e7550d")
PLACEHOLDER = {250: 15, 500: 20, 1000: 30, 2000: 45, 4000: 55, 6000: 55}   # defaults.yaml


def deficits(ag_db_hl):
    """Baseline deficits for any audiogram on the validation patient's scenes: runner.run_scene without
    HASPI, which the target never reads."""
    scenes = json.load(open(os.path.join(PATIENT, "scenes", "scenes.json")))
    ag, normal = scoring.audiogram(ag_db_hl), scoring.audiogram({f: 0.0 for f in ag_db_hl})
    waves, cache, gaps = os.path.join(PATIENT, "waves"), {}, []
    for s in scenes:
        key = (s["condition"], s["clip"])
        if key not in cache:
            _, speech, noise = runner.scene_signals(s, waves)
            L = s["level_db"]
            cache[key] = (scoring.band_audibility(speech, noise, runner.FS, normal, L)
                          - scoring.band_audibility(speech, noise, runner.FS, ag, L))
        gaps.append(cache[key])
    gaps = np.array(gaps)
    return gaps, gaps * scoring.SII_IMPORTANCE, [s["weight"] for s in scenes]


def main():
    ep = T.load_ear_params(PATIENT)
    canals = [c["length_mm"] for c in json.load(open(os.path.join(PATIENT, "context", "canals.json")))["canals"]]
    boxes = T.family_boxes(ep, PATIENT)
    reach = T.reach(ep, canals, boxes)
    f = np.array(T.FREQS)

    # The device must aim at the high-frequency loss; a target spread low would size the horn for the wrong band.
    t = T.triage(*deficits(PLACEHOLDER), PLACEHOLDER, reach, "left")
    g = np.array(t["gain_db"])
    print(f"placeholder: target above 1.5 kHz {g[f >= 1500].sum():.1f} of {g.sum():.1f} dB-bands, "
          f"peak {g.max():.1f} dB at {f[g.argmax()]:g} Hz; {t['triage']}")
    assert t["triage"] in T.VERDICTS and f[g.argmax()] >= 1500 and g[f >= 1500].sum() > 2 * g[f < 1500].sum()
    assert all(x >= 0 for x in g)                                  # never a negative target

    # A near-normal ear must not be prescribed gain: that is all cost and no benefit for a passive device.
    flat10 = {k: 10 for k in PLACEHOLDER}
    t10 = T.triage(*deficits(flat10), flat10, reach, "left")
    print(f"flat 10 dB HL: max target {max(t10['gain_db']):.2f} dB; {t10['triage']} | {t10['why']}")
    assert max(t10["gain_db"]) < T.NEGLIGIBLE_DB and t10["needed"] is False

    # A moderate flat loss is beyond any passive device; the verdict is a result, not an exception.
    flat60 = {k: 60 for k in PLACEHOLDER}
    t60 = T.triage(*deficits(flat60), flat60, reach, "left")
    print(f"flat 60 dB HL: {t60['triage']} | {t60['why']}")
    assert t60["triage"] == "powered aid recommended" and t60["needed"]

    # The SAME inputs must give the SAME file, or the demo replays and the agent loop disagree with it.
    again = T.triage(*deficits(PLACEHOLDER), PLACEHOLDER, T.reach(ep, canals, boxes), "left")
    assert json.dumps(again) == json.dumps(t)

    # The demo screen reads target/target.json through the manifest; a missing key blanks the triage card.
    out = T.build(PATIENT, reach_by_family=reach)
    need = [k.rstrip("?") for k in manifest.SCHEMA["target"] if not k.endswith("?")]
    assert all(k in out for k in need) and all(len(out[k]) == 18 for k in ("freqs_hz", "gain_db", "reach_db", "ratio"))
    assert json.load(open(os.path.join(PATIENT, "target", "target.json"))) == json.loads(json.dumps(out))
    print("validation patient:", out["triage"], "|", out["why"])
    print("ok")


if __name__ == "__main__":
    main()
