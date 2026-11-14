"""Design an earpiece from the browser's scene grid (frontend /sim).

    python -m hornsim.scene_design <patient_dir> <scenes.json>

The grid sends, per scene, the deficit per SII band that its live wave sim measured (the same
quantity hornsim.runner writes to baseline.json) and a weight. From there this is the existing
pipeline, unchanged:

  1. target   hornsim.target.triage: T(f), key bands, guarded bands, verdict
  2. reach    hornsim.target.reach over the in-concha earpiece family's design box (seeded sweep,
              acoustics.insertion_gain over this ear's canal samples)
  3. pick     the swept design that best delivers T(f) where it matters (objective below)
  4. build    hornsim.earpiece.build: geometry checks + printable mesh; on a failed check, the next
              best design is tried

Objective, lower is better: how closely the design's gain curve maps onto T(f), band by band,
each band weighted by its share of the importance-weighted deficit (target.triage's `share`):
    J = Σ share·(T − G_mean)₊² + ¼·Σ share·(G_mean − T)₊² + ½·Σ share·(T − G_worst)₊²
squared so the SHAPE is fitted (a band far off costs more than several slightly off), shortfall
weighted over overshoot, and the worst canal counted so the fit holds across canal sizes.

Writes <patient_dir>/scene_design/: request.json, result.json, ear_params.json (cache),
boxes.json (cache), and the chosen build's files under aid/<design_id>/.
"""
import json
import math
import os
import sys
import time

import numpy as np

from . import ear_world as ew
from . import earpiece as epc
from . import scoring
from . import target as tg

N_TRY = 6            # builds attempted, best objective first, before giving up


def _cached(path, make):
    if os.path.exists(path):
        return json.load(open(path))
    v = make()
    json.dump(v, open(path, "w"), indent=1, default=float)
    return v


def earpiece_ear_params(patient_dir):
    """The ear_params fields the earpiece family reads (acoustics._open/_aid, target.family_boxes).
    ear_world.ear_params would also search for a coiled horn and RAISES when none fits, which says
    nothing about the in-concha earpiece; this skips that search."""
    cfg = json.load(open(os.path.join(patient_dir, "context", "context.json")))["config"]
    P, E = cfg["patient"], cfg["ear_world"]
    _, world = ew.build(P["ear_mesh"], E["landmarks_xlsx"], tuple(E["concha_rim_landmarks"]), E["voxel_mm"],
                        E["fit_tolerance_mm"], E["faceplate_protrusion_mm"], E["canal_opening_diameter_mm"],
                        P["ear_height_mm"])
    return {"concha_depth_mm": float(world.max_depth_mm), "opening_area_mm2": float(world.opening_area_mm2),
            "bowl_volume_cc": float(world.bowl_volume_cc), "shell_volume_cc": float(world.shell_volume_cc),
            "canal_diameter_mm": float(world.canal_diameter_mm), "canal_point_mm": world.canal_point.tolist(),
            "canal_axis": world.canal_axis.tolist(), "x_head_mm": float(world.canal_point[0])}


def canal_lengths(patient_dir):
    cj = json.load(open(os.path.join(patient_dir, "context", "canals.json")))
    return [c["length_mm"] for c in cj["canals"]]


def objective(mean_db, worst_db, target, share):
    under = np.clip(target - mean_db, 0, None) ** 2 @ share
    over = np.clip(mean_db - target, 0, None) ** 2 @ share
    under_w = np.clip(target - worst_db, 0, None) ** 2 @ share
    return under + 0.25 * over + 0.5 * under_w


def to_build_params(d):
    """A swept design (acoustics keys) -> earpiece.build params. Length is not a dial (the bowl sets it)."""
    p = {k: d[k] for k in ("throat_mm2", "mouth_mm2", "flare_mid1", "flare_mid2", "canal_stem_mm")}
    p["flare_mid2"] = max(p["flare_mid2"], p["flare_mid1"])
    return {k: round(float(v), 3) for k, v in p.items()}


def run(patient_dir, request, log=print):
    t0 = time.time()
    out = os.path.join(patient_dir, "scene_design")
    os.makedirs(out, exist_ok=True)
    json.dump(request, open(os.path.join(out, "request.json"), "w"), indent=1)
    scenes = [s for s in request["scenes"] if s.get("weight", 0) > 0 and s.get("deficit_db")]
    if not scenes:
        raise ValueError("no scene with a deficit and a positive weight")
    ag = {float(k): float(v) for k, v in request["audiogram_db_hl"].items()}

    log("ear parameters (cached after the first run)")
    ear = _cached(os.path.join(out, "ear_params.json"), lambda: earpiece_ear_params(patient_dir))
    log(f"  canal {ear['canal_diameter_mm']:.1f} mm  ({time.time() - t0:.0f}s)")
    log("earpiece design box (two probe builds, cached)")
    boxes = _cached(os.path.join(out, "boxes.json"), lambda: tg.earpiece_boxes(ear, patient_dir))
    boxes = [{k: tuple(v) for k, v in b.items()} for b in boxes]
    if not boxes:
        raise ValueError("this ear cannot hold any in-concha earpiece variant")
    log(f"sweep: {tg.SWEEP_N} designs per variant x {len(canal_lengths(patient_dir))} canals")
    r = tg.reach(ear, canal_lengths(patient_dir), {"earpiece": boxes})["earpiece"]
    log(f"  done ({time.time() - t0:.0f}s)")

    w = np.array([s["weight"] for s in scenes], float)
    deficit = [s["deficit_db"] for s in scenes]
    weighted = [s.get("deficit_weighted") or (np.array(s["deficit_db"]) * scoring.SII_IMPORTANCE).tolist() for s in scenes]
    t = tg.triage(deficit, weighted, w, ag, {"earpiece": r})
    T = np.array(t["gain_db"], float)
    share = np.clip((w / w.sum()) @ np.array(weighted, float), 0, None)
    share = share / share.sum() if share.sum() > 0 else np.full(len(T), 1 / len(T))
    guard = np.nonzero(share >= tg.HARM_SHARE)[0]

    J = objective(r["mean_db"], r["worst_db"], T, share)
    order = np.argsort(J)
    chosen, attempts = None, []
    for rank, j in enumerate(order[:N_TRY]):
        params = to_build_params(r["designs"][j])
        did = f"grid{rank + 1}"
        log(f"build {did}: throat {params['throat_mm2']:.0f} mm2, mouth {params['mouth_mm2']:.0f} mm2, J {J[j]:.2f}")
        rep = epc.build(os.path.join(patient_dir, "context"), os.path.join(patient_dir, "aid"), params, did,
                        log=lambda m: None)
        attempts.append({"design_id": did, "objective": round(float(J[j]), 3), "ok": rep["ok"],
                         "reasons": [x.get("message", x) for x in rep.get("reasons", [])]})
        if rep["ok"]:
            chosen = (j, did, params, rep)
            break
        log(f"  rejected: {attempts[-1]['reasons'][:1]}")
    if chosen is None:
        raise ValueError(f"none of the {N_TRY} best designs passed the geometry checks: {attempts}")

    j, did, params, rep = chosen
    G, Gw = r["mean_db"][j], r["worst_db"][j]
    met = (T < tg.NEGLIGIBLE_DB) | (G >= T - 1.0)        # within 1 dB counts as met
    key = np.array(t["key_bands_hz"], float)
    key_idx = [int(np.argmin(np.abs(tg.FREQS - f))) for f in key]
    result = {
        "version": 1, "elapsed_s": round(time.time() - t0, 1),
        "freqs_hz": tg.FREQS.tolist(), "target_db": T.round(2).tolist(),
        "share": share.round(4).tolist(), "key_bands_hz": t["key_bands_hz"], "guard_bands_hz": tg.FREQS[guard].tolist(),
        "triage": t["triage"], "why": t["why"],
        "reach_db": np.round(t["reach_db"], 2).tolist(),     # per band, the best ANY swept design reaches (upper bound)
        "design": {"id": did, "params": params, "objective": round(float(J[j]), 3),
                   "gain_mean_db": G.round(2).tolist(), "gain_worst_db": Gw.round(2).tolist(),
                   "key_met": f"{int(met[key_idx].sum())} of {len(key_idx)}", "met": met.tolist(),
                   "geometry": {k: v for k, v in rep.get("geometry", {}).items() if isinstance(v, (int, float, str))},
                   "files": {k: f"aid/{did}/{k}" for k in ("earpiece_in_ear.glb", "earpiece.glb", "earpiece_print.stl", "preview.png")
                             if os.path.exists(os.path.join(patient_dir, "aid", did, k))}},
        "attempts": attempts, "swept": int(len(J)),
        "notes": ["Deficits come from the browser's coarse dummy-head wave sim (hornsim.head_grid, both ears, far "
                  "talkers as plane waves) and the ANSI standard speech spectrum; hornsim.runner on the full wavesim "
                  "is the reference.",
                  "Gain is insertion gain over the open ear from hornsim.acoustics, averaged (mean) or worst over the "
                  "sampled canals."],
    }
    json.dump(result, open(os.path.join(out, "result.json"), "w"), indent=1)
    log(f"chose {did}: key bands met {result['design']['key_met']}, triage {t['triage']} ({result['elapsed_s']}s)")
    return result


if __name__ == "__main__":
    print(json.dumps({k: v for k, v in run(sys.argv[1], json.load(open(sys.argv[2]))).items() if k != "attempts"}, indent=1)[:3000])
