"""Score a built aid for its patient: insertion gain -> speech -> HASPI v2.

For each clip and level that has headroom (see references.json), the aid's insertion gain
(per sampled canal) is applied to the listener's input and HASPI is computed with the
patient's audiogram. The reward term is the share of the gap it closes:

    closure = (haspi_aided - unaided) / (ceiling - unaided)      0 = no better than no aid,
                                                                 1 = as good as the best linear aid,
                                                                 < 0 = worse than no aid

    python -m hornsim.score <patient_dir>     # needs context/ and aid/acoustics.json
"""
import json
import os
import sys

import numpy as np
import soundfile as sf

from . import acoustics as ac
from . import scoring
from .audio import apply_gain, rms


def _haspi(args):
    """One (condition, canal) HASPI score, in a worker process. Seeded, so it is the SAME wherever it runs."""
    x_ref, x_in, fs, freqs, g, ag, level, seed = args
    return scoring.haspi(x_ref, apply_gain(x_in, fs, freqs, g), fs, ag, level, seed)


def score(patient_dir, n_canals=5, log=print):
    ctx, aid_dir = os.path.join(patient_dir, "context"), os.path.join(patient_dir, "aid")
    cfg = json.load(open(os.path.join(ctx, "context.json")))["config"]
    refs = json.load(open(os.path.join(ctx, "references.json")))
    cj = json.load(open(os.path.join(ctx, "canals.json")))
    design = ac.Design.from_design_json(json.load(open(os.path.join(aid_dir, "design.json"))))
    ag = scoring.audiogram(cfg["patient"]["audiogram_db_hl"])
    seed = refs["seed"]

    # a spread of canals (smallest .. largest), not all 32: HASPI is the slow part
    idx = np.unique(np.round(np.linspace(0, len(cj["canals"]) - 1, n_canals)).astype(int))
    canals = [ac.Canal(cj["canals"][i]["volume_cc"], cj["assumed_diameter_mm"]) for i in idx]
    freqs = ac.DEFAULT_FREQS
    ig = ac.insertion_gain_db(design, canals, freqs)

    clips = {}
    used = [r for r in refs["results"] if r["use_in_reward"]]
    for name in {r["clip"] for r in used}:
        x_ref, fs = sf.read(os.path.join(ctx, "speech", f"{name}_reference.wav"))
        x_in, _ = sf.read(os.path.join(ctx, "speech", f"{name}_input.wav"))
        k = 1 / rms(x_ref)                          # files are stored scaled; restore RMS 1 for the reference
        clips[name] = (x_ref * k, x_in * k, fs)
    # 45-odd HASPI calls took ~50 s an ear one after another. Processes, NOT threads (HASPI holds the GIL), and "spawn"
    # for the same reason as hornsim/context.py: a fork of the server would copy its threads and locks.
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    tasks = [(*clips[r["clip"]], freqs, g, ag, r["level_db_spl"], seed) for r in used for g in ig]
    with ProcessPoolExecutor(max_workers=max(1, min(len(tasks), (os.cpu_count() or 2) - 1)), mp_context=mp.get_context("spawn")) as ex:
        scores = list(ex.map(_haspi, tasks))
    rows = []
    for i, r in enumerate(used):
        name = r["clip"]
        per_canal = scores[i * len(ig):(i + 1) * len(ig)]
        head = r["ceiling"] - r["unaided"]
        clos = [(h - r["unaided"]) / head for h in per_canal]
        rows.append({"clip": name, "level_db_spl": r["level_db_spl"], "unaided": r["unaided"], "ceiling": r["ceiling"],
                     "aided_mean": float(np.mean(per_canal)), "aided_worst": float(np.min(per_canal)),
                     "closure_mean": float(np.mean(clos)), "closure_worst": float(np.min(clos))})
        log(f"  {name:9s} {r['level_db_spl']} dB  unaided {r['unaided']:.3f}  aided {np.mean(per_canal):.3f}  "
            f"ceiling {r['ceiling']:.3f}  closure {np.mean(clos):+.2f}")
    # pooled over conditions, so one condition with little headroom cannot dominate
    head = sum(x["ceiling"] - x["unaided"] for x in rows)
    mean_c = float(sum(x["aided_mean"] - x["unaided"] for x in rows) / head)
    worst_c = float(sum(x["aided_worst"] - x["unaided"] for x in rows) / head)
    out = {"metric": "HASPI v2", "canals_used_cc": [c.volume_cc for c in canals],
           "closure_mean": round(mean_c, 3), "closure_worst_canal": round(worst_c, 3),
           "reward": round(mean_c - 0.5 * max(0.0, mean_c - worst_c), 3),
           "better_than_unaided_in": f"{sum(x['aided_mean'] > x['unaided'] for x in rows)} of {len(rows)} conditions",
           "conditions": rows,
           "notes": ["closure: 0 = same as no aid, 1 = best linear prescription, negative = worse than no aid.",
                     "Overall closure pools HASPI gains over all conditions with headroom.",
                     "reward = mean closure - 0.5 x (mean - worst-canal closure). Loudness and occlusion terms not yet included."]}
    json.dump(out, open(os.path.join(aid_dir, "score.json"), "w"), indent=1)
    log(f"score: closure {out['closure_mean']:+.2f} (worst canal {out['closure_worst_canal']:+.2f}), reward {out['reward']:+.2f}")
    return out


if __name__ == "__main__":
    s = score(sys.argv[1])
    print(json.dumps({k: s[k] for k in ("closure_mean", "closure_worst_canal", "reward")}, indent=1))
