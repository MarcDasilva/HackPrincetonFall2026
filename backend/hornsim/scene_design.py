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
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from . import ear_world as ew
from . import earpiece as epc
from . import scoring
from . import target as tg

N_TRY = 10           # builds attempted, best objective first, before giving up
N_OPTIONS = 4        # distinct buildable designs offered to the patient
# Options past the first come from designs within this factor of the best objective, picked to be as far
# apart in SHAPE as possible — ranked picks were near copies of option 1 (same throat, stem and flare).
SLACK = 1.3
STEM_MM = 4.0        # a canal stem this long is visible; one option carries one when the ear holds it
# Shape axes and how much each shows on the printed piece; flare is subtler than mouth, throat or stem.
SHAPE = {"throat_mm2": 1.0, "mouth_mm2": 1.0, "canal_stem_mm": 1.0, "collector_reach_mm": 1.5,
         "flare_mid1": 0.5, "flare_mid2": 0.5}
# Cone collector: it leaves the faceplate straight out for COLLECTOR_BASE_MM, then bends toward the talker.
# A cone tilted straight off the faceplate hit the tragus on a real ear; the straight base clears it.
COLLECTOR_BASE_MM = 6.0
COLLECTOR_REACH_MM = (10.0, 20.0)
COLLECTOR_OPENING_MM2 = 700.0
HOOD_MM = 3.0        # a flush piece shows its aim through a hood on the side away from the talker
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


def _shape(designs):
    """Designs -> [n, axes] scaled to the sweep's range, weighted by how visible each axis is."""
    X = np.array([[d.get(k, 0.0) for k in SHAPE] for d in designs], float)
    return (X - X.min(0)) / np.where(np.ptp(X, 0) > 0, np.ptp(X, 0), 1) * np.array(list(SHAPE.values()))


def pick(designs, J, chosen, skip, slack=SLACK):
    """The next design to build: the best first, then the best with a visible stem, then the design
    farthest in shape from everything already chosen. Families come first: the best with a cone collector,
    then the best with a visible stem. ``skip`` holds indices already tried. None when spent."""
    J = np.asarray(J, float)
    free = np.ones(len(J), bool)
    free[list(skip)] = False
    if not chosen:
        return int(np.argmin(np.where(free, J, np.inf))) if free.any() else None
    # One option per visibly different family the ear holds: a cone collector, a canal stem.
    for key, least in (("collector_reach_mm", 1.0), ("canal_stem_mm", STEM_MM)):
        has = np.array([d.get(key, 0.0) for d in designs]) >= least
        if not any(designs[i].get(key, 0.0) >= least for i in chosen) and (has & free).any():
            return int(np.argmin(np.where(has & free, J, np.inf)))
    pool = np.nonzero(free & (J <= slack * J.min()))[0]
    if not len(pool):
        return None
    X = _shape(designs)
    far = np.min(np.linalg.norm(X[pool, None] - X[chosen][None], axis=2), 1)
    return int(pool[np.argmax(far)])


# Tests swap in a ThreadPoolExecutor: a stubbed epc.build does NOT reach a worker process.
_pool = ProcessPoolExecutor


def _build(context_dir, aid_dir, tries, did):
    """The first of ``tries`` (same design, gentler aim each time) that passes the geometry checks, in a
    worker process (module level, so it pickles). The last rejection when none does."""
    for params in tries:
        rep = epc.build(context_dir, aid_dir, params, did, log=lambda m: None)
        if rep["ok"]:
            break
    return rep | {"params_built": params}


def talker_aims(scenes):
    """(yaw, pitch, weight) per scene talker, yaw folded onto 0 front .. 90 straight out .. 180 behind.
    A talker on the far side (az > 180) is heard round the head, so it folds onto its mirror."""
    out = []
    for s in scenes:
        if s.get("talker_az_deg") is None:
            continue
        az = float(s["talker_az_deg"]) % 360
        out.append((az if az <= 180 else 360 - az, float(np.clip(s.get("talker_el_deg") or 0, -45, 45)), float(s["weight"])))
    return out


def option_aims(scenes, n):
    """n aims: the weighted mean talker first (the recommended option), then each distinct talker by
    weight, then a spread. No talkers (the /sim grid sends none) -> straight out, then the spread."""
    talkers = talker_aims(scenes)
    aims = []
    if talkers:
        w = np.array([t[2] for t in talkers])
        yaw = np.degrees(np.arctan2(w @ np.sin(np.radians([t[0] for t in talkers])), w @ np.cos(np.radians([t[0] for t in talkers]))))
        aims.append((float(np.clip(yaw, 0, 180)), float(w @ [t[1] for t in talkers] / w.sum())))
        aims += [(t[0], t[1]) for t in sorted(talkers, key=lambda t: -t[2])]
    aims += [(90.0, 0.0), (30.0, 0.0), (150.0, 0.0), (60.0, 15.0), (120.0, -15.0)]
    picked = []
    for a in aims:
        if all(abs(a[0] - b[0]) + abs(a[1] - b[1]) >= 15 for b in picked):
            picked.append(a)
    return picked[:n]


def collector(reach, opening_mm2, mouth_mm2, yaw, pitch):
    """A round cone: straight out COLLECTOR_BASE_MM, then (reach - base) toward (yaw, pitch). Spine is
    [out, up, front] (earpiece.py); yaw 90 is straight out, so the bend never points back at the head."""
    y, p, rest = math.radians(yaw), math.radians(pitch), reach - COLLECTOR_BASE_MM
    tip = [COLLECTOR_BASE_MM + rest * math.sin(y) * math.cos(p), rest * math.sin(p), rest * math.cos(y) * math.cos(p)]
    r_mid, r_tip = math.sqrt(math.sqrt(mouth_mm2 * opening_mm2) / math.pi), math.sqrt(opening_mm2 / math.pi)
    return {"spine": [[COLLECTOR_BASE_MM, 0.0, 0.0], [round(v, 2) for v in tip]],
            "sections": [[round(r_mid, 2)] * 12, [round(r_tip, 2)] * 12]}


def build_tries(params, design, mouth_concha_mm2, aim):
    """The builds to attempt for one option, preferred first: aimed at its talker, then halfway to
    straight out, then straight out (and for a flush piece, finally without the hood)."""
    yaw, pitch = aim
    ladder = [(yaw, pitch), ((yaw + 90) / 2, pitch / 2), (90.0, 0.0)]
    tries = []
    for y, pt in ladder:
        q = params | {"aim_yaw_deg": round(y, 1), "aim_pitch_deg": round(pt, 1)}
        if design.get("collector_reach_mm", 0) > 0:
            q = q | {"mouth_mm2": mouth_concha_mm2,
                     "collector": collector(design["collector_reach_mm"], design["mouth_mm2"], mouth_concha_mm2, y, pt)}
        else:
            q = q | {"hood_mm": HOOD_MM}
        if q not in tries:
            tries.append(q)
    if not design.get("collector_reach_mm"):
        tries.append(params | {"aim_yaw_deg": round(yaw, 1), "hood_mm": 0.0})
    return tries


def reason(o, best, T, key_idx):
    """One plain line on why this option is on the list, from its numbers only."""
    G, B = np.array(o["gain_mean_db"]), np.array(best["gain_mean_db"])
    on_key = float(np.mean(G[key_idx])) if key_idx else float(np.mean(G))
    # NEVER "key bands" in this line: it is patient-facing (the option cards, the report); key_met stays in the result.
    line = (f"Recommended. The closest fit to the gain your scenes need, {on_key:.1f} dB average gain where it matters most."
            if o is best else f"{on_key:.1f} dB average gain where it matters most.")
    if o is not best:
        d = G - B
        i = int(np.argmax(np.abs(d)))
        line += f" {abs(d[i]):.1f} dB {'more' if d[i] > 0 else 'less'} than option 1 at {tg.FREQS[i]:g} Hz."
    g = o["geometry"]
    shape = []
    col = o["params"].get("collector")
    if col:
        shape.append(f"{o['collector_reach_mm']:.0f} mm cone collector")
    elif o["params"].get("hood_mm"):
        shape.append("hood")
    shape += [f"{g['mouth_width_mm']:.0f} x {g['mouth_height_mm']:.0f} mm mouth"] if "mouth_width_mm" in g else []
    if g.get("canal_stem_mm"):
        shape.append(f"{g['canal_stem_mm']:.0f} mm canal stem")
    if isinstance(g.get("bore_length_mm"), (int, float)):
        shape.append(f"{g['bore_length_mm']:.0f} mm bore")
    shape.append(f"aimed {_where(o['params'].get('aim_yaw_deg', 90), o['params'].get('aim_pitch_deg', 0))}")
    return line + (f" {', '.join(shape).capitalize()}." if shape else "")


def _where(yaw, pitch):
    side = "toward the front" if yaw < 60 else "straight out" if yaw <= 120 else "toward the back"
    return side + (" and up" if pitch >= 10 else " and down" if pitch <= -10 else "") + f" ({yaw:.0f} deg)"


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
    r, mouth_concha = _sweep(patient_dir, out, ear, log, t0)
    log(f"  done ({time.time() - t0:.0f}s)")
    return _design(patient_dir, out, request, scenes, ag, r, mouth_concha, log, t0)


def _sweep(patient_dir, out, ear, log, t0):
    log("earpiece design box (two probe builds, cached)")
    boxes = _cached(os.path.join(out, "boxes.json"), lambda: tg.earpiece_boxes(ear, patient_dir))
    boxes = [{k: tuple(v) for k, v in b.items()} for b in boxes]
    if not boxes:
        raise ValueError("this ear cannot hold any in-concha earpiece variant")
    log(f"sweep: {tg.SWEEP_N} designs per variant x {len(canal_lengths(patient_dir))} canals")
    r = tg.reach(ear, canal_lengths(patient_dir), {"earpiece": boxes})["earpiece"]
    for d in r["designs"]:
        d["collector_reach_mm"] = 0.0
    # Cone collectors grow from the flush (no-stem) variant. ponytail: the 1D model sees a collector only
    # as more horn, so it is scored as the bore extended by the reach out to the cone's opening; the full
    # wavesim check is what to trust for its directivity.
    flush = [b for b in boxes if b["canal_stem_mm"][1] == 0]
    mouth_concha = flush[0]["mouth_mm2"][1] if flush else None
    if flush:
        L0 = flush[0]["length_mm"][0]
        cone = dict(flush[0]) | {"length_mm": (L0 + COLLECTOR_REACH_MM[0], L0 + COLLECTOR_REACH_MM[1]),
                                 "mouth_mm2": (mouth_concha, COLLECTOR_OPENING_MM2)}
        rc = tg.reach(ear, canal_lengths(patient_dir), {"earpiece": [cone]})["earpiece"]
        for d in rc["designs"]:
            d["collector_reach_mm"] = d["length_mm"] - L0
        r = {"mean_db": np.concatenate([r["mean_db"], rc["mean_db"]]),
             "worst_db": np.concatenate([r["worst_db"], rc["worst_db"]]), "designs": r["designs"] + rc["designs"]}
    return r, mouth_concha


def _design(patient_dir, out, request, scenes, ag, r, mouth_concha, log, t0):
    """Target from the scenes, then pick and build the options from the sweep ``r``."""
    w = np.array([s["weight"] for s in scenes], float)
    deficit = [s["deficit_db"] for s in scenes]
    weighted = [s.get("deficit_weighted") or (np.array(s["deficit_db"]) * scoring.SII_IMPORTANCE).tolist() for s in scenes]
    t = tg.triage(deficit, weighted, w, ag, {"earpiece": r})
    T = np.array(t["gain_db"], float)
    share = np.clip((w / w.sum()) @ np.array(weighted, float), 0, None)
    share = share / share.sum() if share.sum() > 0 else np.full(len(T), 1 / len(T))
    guard = np.nonzero(share >= tg.HARM_SHARE)[0]

    J = objective(r["mean_db"], r["worst_db"], T, share)
    key = np.array(t["key_bands_hz"], float)
    key_idx = [int(np.argmin(np.abs(tg.FREQS - f))) for f in key]
    aims = option_aims(scenes, N_OPTIONS)
    log("aims from your scenes: " + ", ".join(f"{y:.0f} deg" + (f" / {p:+.0f}" if p else "") for y, p in aims))
    options, attempts, chosen, tried = [], [], [], set()
    ctx, aid = os.path.join(patient_dir, "context"), os.path.join(patient_dir, "aid")
    # Builds are independent (each writes ONLY aid/<id>/), so a round of up to N_OPTIONS runs in parallel; a
    # rejected build is replaced next round by the next pick.
    with _pool(max_workers=N_OPTIONS) as ex:
        while len(options) < N_OPTIONS and len(attempts) < N_TRY:
            batch = []
            for _ in range(min(N_OPTIONS - len(options), N_TRY - len(attempts))):
                j = pick(r["designs"], J, chosen + [b[0] for b in batch], tried)
                if j is None:
                    break
                tried.add(j)
                # A rejected build hands its aim on: each aim goes to ONE option.
                taken = {o["aim_slot"] for o in options} | {b[3] for b in batch}
                slot = next((k for k in range(len(aims)) if k not in taken), len(aims) - 1)
                tries = build_tries(to_build_params(r["designs"][j]), r["designs"][j], r["designs"][j].get("mouth_concha_mm2", mouth_concha), aims[slot])
                batch.append((j, tries, f"grid{len(attempts) + len(batch) + 1}", slot))
            if not batch:
                break
            for j, tries, did, _ in batch:
                d, q = r["designs"][j], tries[0]
                log(f"build {did}: throat {d['throat_mm2']:.0f} mm2, mouth {d['mouth_mm2']:.0f} mm2, "
                    f"stem {d['canal_stem_mm']:.1f} mm, cone {d['collector_reach_mm']:.0f} mm, "
                    f"aim {q['aim_yaw_deg']:.0f} deg, J {J[j]:.2f}")
            futures = [ex.submit(_build, ctx, aid, tries, did) for _, tries, did, _ in batch]
            for (j, tries, did, slot), fut in zip(batch, futures):
                rep = fut.result()
                params = rep["params_built"]
                attempts.append({"design_id": did, "objective": round(float(J[j]), 3), "ok": rep["ok"],
                                 "reasons": [x.get("message", x) for x in rep.get("reasons", [])]})
                if not rep["ok"]:
                    log(f"  {did} rejected: {attempts[-1]['reasons'][:1]}")
                    continue
                chosen.append(j)
                G, Gw = r["mean_db"][j], r["worst_db"][j]
                met = (T < tg.NEGLIGIBLE_DB) | (G >= T - 1.0)        # within 1 dB counts as met
                options.append({"id": did, "params": params, "objective": round(float(J[j]), 3), "aim_slot": slot,
                                "collector_reach_mm": round(float(r["designs"][j]["collector_reach_mm"]), 1),
                                "gain_mean_db": G.round(2).tolist(), "gain_worst_db": Gw.round(2).tolist(),
                                "key_met": f"{int(met[key_idx].sum())} of {len(key_idx)}", "met": met.tolist(),
                                "geometry": {k: v for k, v in rep.get("geometry", {}).items() if isinstance(v, (int, float, str))},
                                "files": {k: f"aid/{did}/{k}" for k in ("earpiece_in_ear.glb", "earpiece.glb", "earpiece_print.stl", "preview.png")
                                          if os.path.exists(os.path.join(aid, did, k))}})
    # Best objective first: option 1 is the recommendation, and "design" below reads it.
    options.sort(key=lambda o: o["objective"])
    if not options:
        raise ValueError(f"none of the {len(attempts)} best designs passed the geometry checks: {attempts}")
    for o in options:
        o["recommended"] = o is options[0]
        o["reason"] = reason(o, options[0], T, key_idx)
    did = options[0]["id"]
    result = {
        "version": 1, "elapsed_s": round(time.time() - t0, 1),
        "freqs_hz": tg.FREQS.tolist(), "target_db": T.round(2).tolist(),
        "share": share.round(4).tolist(), "key_bands_hz": t["key_bands_hz"], "guard_bands_hz": tg.FREQS[guard].tolist(),
        "triage": t["triage"], "why": t["why"],
        "reach_db": np.round(t["reach_db"], 2).tolist(),     # per band, the best ANY swept design reaches (upper bound)
        # "design" stays the best option: /sim's Aggregate and the wave check read it.
        "design": options[0], "options": options,
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
