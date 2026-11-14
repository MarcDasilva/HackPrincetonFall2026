"""Target and triage (spec 06): what gain this ear needs per SII band, what each passive device family can
reach, and whether a passive device is worth building at all.

    python -m hornsim.target <patient_dir>          writes <patient_dir>/target/target.json

A "powered aid recommended" verdict is a RESULT, not an error: the file is written and the design search
(spec 08) reads `triage` to decide whether to run.

Target: T(f) = scene-weighted mean audibility gap (baseline `deficit_db`), capped at NAL-R, floored at 0.
The importance-weighted deficit (`deficit_weighted`) decides WHICH bands matter (their share), not how
many dB they need — it is the gap times an importance <= 0.09, so as a gain it would be ~10x too small.

Reach: best canal-mean insertion gain over the open ear (spec 07) per band, over a seeded random sweep of
each family's box, with that SAME design's worst canal alongside. Each band takes its own best design, so
reach is an upper bound no single device meets everywhere; `harm` flags bands whose best design costs
more than HARM_DB in any band holding >= HARM_SHARE of the weighted deficit.
"""
import json
import os
import sys
import tempfile

import numpy as np

from . import acoustics, scoring
from . import ear_world as ew
from . import earpiece as epc

# Reviewer decisions, not evidence (spec 06 "open decisions"); change them here and nowhere else.
KEY_COVER = 0.5            # key bands: the fewest bands (largest share first) holding >= half the weighted deficit
HARM_SHARE = 0.10          # a band holding >= 10% of the weighted deficit must not lose more than HARM_DB
HARM_DB = 3.0
NEGLIGIBLE_DB = HARM_DB    # a band needing less than the loss already tolerated as harmless needs no device
SWEEP_N = 3000             # random designs per family box
SWEEP_SEED = 0
PER_BAND = 5               # frequencies averaged (as power) across each one-third-octave band

FREQS = scoring.SII_FREQS
VERDICTS = ("passive-suitable", "partial", "powered aid recommended")
NAMES = {"coil": "coiled horn", "earpiece": "in-concha earpiece"}


def load_ear_params(patient_dir):
    """ear_params (spec 02) from the patient's context config; ~40 s, NOT saved in context.json."""
    cfg = json.load(open(os.path.join(patient_dir, "context", "context.json")))["config"]
    P, E = cfg["patient"], cfg["ear_world"]
    mesh, world = ew.build(P["ear_mesh"], E["landmarks_xlsx"], tuple(E["concha_rim_landmarks"]), E["voxel_mm"],
                           E["fit_tolerance_mm"], E["faceplate_protrusion_mm"], E["canal_opening_diameter_mm"],
                           P["ear_height_mm"])
    return ew.ear_params(world, mesh)


def family_boxes(ear_params, patient_dir):
    """{family: [box, ...]}, box = {design key: (lo, hi)} in acoustics.insertion_gain's keys."""
    return {"coil": [dict(ew.design_bounds(ear_params))], "earpiece": earpiece_boxes(ear_params, patient_dir)}


def earpiece_boxes(ear_params, patient_dir):
    """The in-concha earpiece family's boxes (needs only ear_params["canal_diameter_mm"]).

    Earpiece: bore length and the largest mouth exist only as earpiece.build geometry, so two probe builds
    (stem, and no stem with the widest throat) are run into a throwaway folder. Same rules the acoustics
    go/no-go used: mouth <= 0.95 x the opening's max (earpiece's mouth_fit), throat <= what the stem wall
    leaves, flare capped at earpiece's defaults (wider broke the bore wall at throat 60), sealed."""
    D = {k: v[2] for k, v in epc.PARAMS.items()}
    lo = lambda k: epc.PARAMS[k][0]
    stem_throat = np.pi * (ear_params["canal_diameter_mm"] / 2 - epc.STEM_WALL_MM) ** 2
    probes = [({"canal_stem_mm": D["canal_stem_mm"]}, (lo("canal_stem_mm"), epc.PARAMS["canal_stem_mm"][1]),
               stem_throat),
              ({"throat_mm2": epc.PARAMS["throat_mm2"][1], "canal_stem_mm": 0.0}, (0.0, 0.0), epc.PARAMS["throat_mm2"][1])]
    boxes = []
    with tempfile.TemporaryDirectory() as d:
        for params, stem, throat_hi in probes:
            r = epc.build(os.path.join(patient_dir, "context"), d, params | {"throat_mm2": throat_hi}, "probe",
                          log=lambda m: None)
            if not r["ok"]:
                continue                    # this ear cannot hold that variant; the family keeps the others
            g = r["geometry"]
            boxes.append({"throat_mm2": (lo("throat_mm2"), throat_hi), "mouth_mm2": (lo("mouth_mm2"), 0.95 * g["mouth_mm2_max"]),
                          "length_mm": (g["bore_length_mm"],) * 2, "canal_stem_mm": stem,
                          "flare_mid1": (0.0, D["flare_mid1"]), "flare_mid2": (D["flare_mid1"], D["flare_mid2"]),
                          "vent_count": (0, 0), "vent_diameter_mm": (0.8, 0.8), "vent_length_mm": (0.0, 0.0)})
    # vent_length 0 is inert: vent_count 0 removes the vent branch (acoustics._aid)
    return boxes


def _sample(box, n, rng):
    x = {k: lo + (hi - lo) * rng.uniform(size=n) for k, (lo, hi) in box.items()}
    x["vent_count"] = np.round(x["vent_count"])
    keep = x["mouth_mm2"] > x["throat_mm2"]          # earpiece.validate; the bore NEVER narrows
    return {k: v[keep] for k, v in x.items()}


def reach(ear_params, canal_lengths_mm, boxes, n=SWEEP_N, seed=SWEEP_SEED):
    """{family: {"mean_db": [designs, 18], "worst_db": [designs, 18], "designs": [x]}} band insertion gains."""
    edges = FREQS[:, None] * 2.0 ** np.linspace(-1 / 6, 1 / 6, PER_BAND)
    canal = {"length_mm": np.asarray(canal_lengths_mm, float)}
    out = {}
    for fam, fboxes in boxes.items():
        rng = np.random.default_rng(seed)
        xs = [_sample(b, n, rng) for b in fboxes]
        if not xs:
            continue
        x = {k: np.concatenate([d[k] for d in xs]) for k in xs[0]}
        G = []
        for i in range(0, len(x["mouth_mm2"]), 500):
            xi = {k: v[i:i + 500, None] for k, v in x.items()}
            g = acoustics.insertion_gain(xi, ear_params, canal, edges.ravel())          # [d, canal, f]
            p = (10 ** (g / 10)).reshape(*g.shape[:2], len(FREQS), PER_BAND).mean(-1)
            G.append(10 * np.log10(p))
        G = np.concatenate(G)
        out[fam] = {"mean_db": G.mean(1), "worst_db": G.min(1),
                    "designs": [{k: float(v[j]) for k, v in x.items()} for j in range(len(G))]}
    return out


def _bands(idx):
    return ", ".join(f"{FREQS[i]:g} Hz" for i in idx)


def _judge(fam, r, target, key, guard):
    """Verdict for one family: per band its best design, that design's worst canal, and harm to the guarded bands."""
    best = r["mean_db"].argmax(0)
    reach_db = r["mean_db"][best, np.arange(len(FREQS))]
    worst_db = r["worst_db"][best, np.arange(len(FREQS))]
    cost = r["mean_db"][best][:, guard].min(1, initial=np.inf)   # worst guarded-band gain of each band's best design
    harm = cost < -HARM_DB
    met = (target < NEGLIGIBLE_DB) | ((reach_db >= target) & ~harm)
    k_met = met[key]
    triage = VERDICTS[0] if k_met.all() else VERDICTS[1] if k_met.any() else VERDICTS[2]
    lead = f"{NAMES[fam]}: "
    if k_met.all():
        why = lead + f"meets the target in every key band ({_bands(key)})"
    else:
        short = key[~k_met]
        bits = [f"{FREQS[i]:g} Hz needs {target[i]:.1f} dB, best reach {reach_db[i]:+.1f} dB "
                f"(worst canal {worst_db[i]:+.1f})" for i in short]
        why = lead + ("meets " + _bands(key[k_met]) + "; " if k_met.any() else "") + "falls short at " + "; ".join(bits)
    if harm[key].any():
        i = key[harm[key]][0]
        j = guard[np.argmin(r["mean_db"][best[i], guard])]
        why += (f"; the best design for {FREQS[i]:g} Hz costs {r['mean_db'][best[i], j]:+.1f} dB at {FREQS[j]:g} Hz")
    return {"triage": triage, "reach_db": reach_db, "reach_worst_db": worst_db, "harm": harm,
            "key_met": int(k_met.sum()), "key_reach_mean": float(reach_db[key].mean()) if len(key) else 0.0, "why": why,
            "best_designs": [r["designs"][j] for j in best]}


def triage(deficit_db, deficit_weighted, weights, ag_db_hl, reach_by_family, side=None):
    """Target and verdict from the baseline arrays ([scenes, 18] each, weights [scenes]). Pure."""
    w = np.asarray(weights, float) / np.sum(weights)
    need = np.clip(w @ np.asarray(deficit_db, float), 0, None)
    share = np.clip(w @ np.asarray(deficit_weighted, float), 0, None)
    share = share / share.sum() if share.sum() > 0 else share
    ag = scoring.audiogram({float(k): float(v) for k, v in ag_db_hl.items()})
    fr, g = scoring.prescription_gain("nal_r", ag)
    nal = np.interp(np.log(FREQS), np.log(fr), g)
    target = np.minimum(need, nal)
    order = np.argsort(-share, kind="stable")
    key = np.sort(order[:np.searchsorted(np.cumsum(share[order]), KEY_COVER) + 1]) if share.sum() > 0 else order[:0]
    guard = np.nonzero(share >= HARM_SHARE)[0]

    fams = {f: _judge(f, r, target, key, guard) for f, r in reach_by_family.items()}
    fam = min(fams, key=lambda f: (VERDICTS.index(fams[f]["triage"]), -fams[f]["key_met"], -fams[f]["key_reach_mean"]))
    pick = fams[fam]
    ratio = [None if t <= 0 or r <= 0 else round(float(t / r), 3) for t, r in zip(target, pick["reach_db"])]
    needed = not (target[key] < NEGLIGIBLE_DB).all()
    if not needed:
        need_line = f"No key band needs {NEGLIGIBLE_DB:g} dB or more (largest target {target.max():.1f} dB): no device is needed."
    else:
        need_line = (f"Needs up to {target.max():.1f} dB at {FREQS[target.argmax()]:g} Hz; {len(key)} bands "
                     f"({_bands(key)}) hold {share[key].sum() * 100:.0f}% of the weighted deficit.")
    if pick["triage"] == VERDICTS[2]:
        top = max(fams, key=lambda f: fams[f]["reach_db"][key].max())
        verdict_line = (f"No passive design of any family meets any key band: the best reaches "
                        f"{fams[top]['reach_db'][key].max():+.1f} dB ({NAMES[top]}) against targets of "
                        f"{target[key].min():.1f}-{target[key].max():.1f} dB, so a powered aid is recommended.")
    else:
        verdict_line = f"The {NAMES[fam]} meets {pick['key_met']} of {len(key)} key bands ({pick['triage']})."
    rnd = lambda a: np.round(a, 2).tolist()
    return {
        "freqs_hz": FREQS.tolist(), "gain_db": rnd(target), "reach_db": rnd(pick["reach_db"]), "ratio": ratio,
        "triage": pick["triage"], "side": side,
        "family": fam, "needed": needed,
        "why": " ".join([need_line, verdict_line] + [fams[f]["why"] + "." for f in fams]) if needed else need_line,
        "reach_worst_db": rnd(pick["reach_worst_db"]), "harm": pick["harm"].tolist(),
        "need_db": rnd(need), "nal_r_db": rnd(nal), "deficit_share": np.round(share, 4).tolist(),
        "key_bands_hz": FREQS[key].tolist(),
        "families": {f: {"triage": v["triage"], "why": v["why"], "reach_db": rnd(v["reach_db"]),
                         "reach_worst_db": rnd(v["reach_worst_db"]), "harm": v["harm"].tolist(),
                         "best_design_hz": {f"{FREQS[i]:g}": {k: round(x, 3) for k, x in v["best_designs"][i].items()}
                                            for i in key}}
                     for f, v in fams.items()},
        "thresholds": {"key_cover": KEY_COVER, "harm_share": HARM_SHARE, "harm_db": HARM_DB, "negligible_db": NEGLIGIBLE_DB,
                       "sweep_n": SWEEP_N, "sweep_seed": SWEEP_SEED},
        "notes": ["Predictions from simulation (spec 07 L1 model), not measurements.",
                  "reach_db: per band, the best canal-mean insertion gain over the open ear among the swept designs; "
                  "each band may use a different design. reach_worst_db is that design's worst canal.",
                  "Thresholds are reviewer decisions (target.py constants)."],
    }


def build(patient_dir, ear_params=None, reach_by_family=None):
    """Read scenes/ and the audiogram, compute target and triage, write target/target.json. Returns the dict."""
    scenes = json.load(open(os.path.join(patient_dir, "scenes", "scenes.json")))
    base = json.load(open(os.path.join(patient_dir, "scenes", "baseline.json")))
    rows = {r["id"]: r for r in base["results"]}
    req = json.load(open(os.path.join(patient_dir, "job.json")))["request"] \
        if not os.path.exists(os.path.join(patient_dir, "request.json")) \
        else json.load(open(os.path.join(patient_dir, "request.json")))
    if reach_by_family is None:
        ear_params = ear_params or load_ear_params(patient_dir)
        canals = json.load(open(os.path.join(patient_dir, "context", "canals.json")))["canals"]
        reach_by_family = reach(ear_params, [c["length_mm"] for c in canals], family_boxes(ear_params, patient_dir))
    t = triage([rows[s["id"]]["deficit_db"] for s in scenes], [rows[s["id"]]["deficit_weighted"] for s in scenes],
               [s["weight"] for s in scenes], base["audiogram_db_hl"], reach_by_family, req.get("side"))
    out = os.path.join(patient_dir, "target")
    os.makedirs(out, exist_ok=True)
    json.dump(t, open(os.path.join(out, "target.json"), "w"), indent=1)
    return t


if __name__ == "__main__":
    r = build(sys.argv[1])
    print(json.dumps({k: r[k] for k in ("triage", "family", "why", "gain_db", "reach_db", "key_bands_hz")}, indent=1))
