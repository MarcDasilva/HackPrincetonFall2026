"""Optimise one ear's earpiece against the 3D simulation, for the user's own scenes.

    objective = scene-weighted mean of (index with the earpiece − index without), for this ear

where the index is the scene grid's (SII for speech targets, audibility for other targets; hornsim.
scene_score), each source heard through the simulated head: the open ears' responses come from one
reciprocity run (hornsim.hrtf_table) and each candidate earpiece is built (hornsim.earpiece),
voxelized into the head (hornsim.head_grid) and run again. 0 is "no earpiece", so a design that makes
things worse scores below zero and is never preferred to wearing nothing.

Search: Bayesian optimisation (Gaussian process + expected improvement) over the earpiece's main
dials, started from a space-filling sample. The 1D model is not used to rank: it misses what the 3D
check showed (the high-frequency loss of sealing the canal entrance). Builds that fail the geometry
checks count as poor and steer the search away. At SEARCH_DX a run takes seconds; the winner is then
used everywhere (its aided direction table is computed at hornsim.hrtf_table's finer HRTF_DX).
"""
import json
import os
import shutil
import time

import numpy as np
from scipy.stats import qmc
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

from . import earpiece as epc
from . import head_grid, hrtf_table
from . import scene_design as sd
from . import target as tg
from .scene_score import scene_index
from .scoring import SII_FREQS

SEARCH_DX = 2.0
SEED = 0

# the dials searched, in [0, 1] each; _params maps them to a build that respects the hard rules (a throat
# fits its canal stem, the mouth is wider than the throat). STEM_OFF of the stem dial means no stem: the
# wide-throat, open-canal region, where the canal keeps its own resonance.
DIALS = ["stem", "throat", "mouth", "flare_mid1", "flare_frac2", "hood_mm", "aim_yaw_deg"]
STEM_OFF = 0.35


def _limits(patient_dir):
    out = os.path.join(patient_dir, "scene_design")
    os.makedirs(out, exist_ok=True)
    ear = sd._cached(os.path.join(out, "ear_params.json"), lambda: sd.earpiece_ear_params(patient_dir))
    boxes = sd._cached(os.path.join(out, "boxes.json"), lambda: tg.earpiece_boxes(ear, patient_dir))
    stem = [b for b in boxes if b["canal_stem_mm"][1] > 0]
    free = [b for b in boxes if b["canal_stem_mm"][1] == 0] or boxes
    return {"throat_stem": max(b["throat_mm2"][1] for b in stem) if stem else 27.0,
            "throat_free": max(b["throat_mm2"][1] for b in free),
            "mouth": max(b["mouth_mm2"][1] for b in boxes)}


def _params(u, lim):
    s, th, mo, f1, f2, hood, yaw = (float(x) for x in u)
    stem_mm = 0.0 if s < STEM_OFF else 1.0 + 7.0 * (s - STEM_OFF) / (1 - STEM_OFF)
    th_hi = lim["throat_free"] if stem_mm == 0 else lim["throat_stem"]
    throat = 7.0 + th * (th_hi - 7.0)
    mouth = throat * 1.15 + mo * max(0.0, lim["mouth"] - throat * 1.15)
    p = {"canal_stem_mm": stem_mm, "throat_mm2": throat, "mouth_mm2": mouth, "flare_mid1": f1,
         "flare_mid2": f1 + f2 * (1 - f1), "hood_mm": 5.0 * hood, "aim_yaw_deg": 180.0 * yaw}
    return {k: round(v, 3) for k, v in p.items()}


class Evaluator:
    """Open ears once; then any candidate earpiece for `side` -> per-scene indices and the objective."""

    def __init__(self, patient_dir, side, ears, head, scenes, audiogram, dx=SEARCH_DX, log=print):
        self.pd, self.side, self.ears, self.head, self.ag, self.dx, self.log = patient_dir, side, ears, head, audiogram, dx, log
        self.scenes = [s for s in scenes if s.get("weight", 1) > 0]
        keys = {(0.0, 0.0)} | {(float(src["az"]) % 360, float(src["el"])) for s in self.scenes for src in s["sources"]}
        self.keys = sorted(keys)
        self.dirs = np.array([hrtf_table.unit(a, e) for a, e in self.keys])
        self.dev = hrtf_table.device()
        H = self._run(None)
        self.ref = hrtf_table.band_power(H[self.keys.index((0.0, 0.0))])
        self.open_gains = {k: 10 * np.log10(hrtf_table.band_power(H[i]) / self.ref) for i, k in enumerate(self.keys)}
        self.unaided = [self._index(s, self.open_gains) for s in self.scenes]
        self.w = np.array([s.get("weight", 1) for s, u in zip(self.scenes, self.unaided) if u is not None], float)

    def _run(self, piece_stl):
        g = head_grid.export(None, self.ears, dx=self.dx, head=self.head, pieces={self.side: piece_stl} if piece_stl else None)
        shape = tuple(g["shape"])
        n = int(np.prod(shape))
        import base64
        solid = np.unpackbits(np.frombuffer(base64.b64decode(g["solid_b64"]), np.uint8))[:n].reshape(shape).astype(bool)
        drum = np.zeros(n, bool)
        for s in ("left", "right"):
            drum[g["ears"][s]["eardrum"]] = True
        e = g["ears"][self.side]
        return hrtf_table.run_ear(solid, drum.reshape(shape), tuple(e["receiver"]), g["origin_mm"], g["dx_mm"], self.dev,
                                  log=lambda m: None, dirs=self.dirs)

    def _index(self, scene, gains):
        srcs = [{"role": x["role"], "level_db": x["level_db"], **({"target": x["target"]} if "target" in x else {})} for x in scene["sources"]]
        g = [gains[(float(x["az"]) % 360, float(x["el"]))] for x in scene["sources"]]
        return scene_index(srcs, g, self.ag)

    def evaluate(self, stl):
        H = self._run(stl)
        gains = {k: 10 * np.log10(hrtf_table.band_power(H[i]) / self.ref) for i, k in enumerate(self.keys)}
        aided = [self._index(s, gains) for s in self.scenes]
        pairs = [(a, u) for a, u in zip(aided, self.unaided) if u is not None and a is not None]
        benefit = float(np.sum(self.w * np.array([a - u for a, u in pairs])) / self.w.sum()) if pairs else 0.0
        ig = {k: (gains[k] - self.open_gains[k]) for k in self.keys}            # insertion gain per direction
        front = ig[(0.0, 0.0)]
        worst = np.min(np.stack(list(ig.values())), 0)
        return {"benefit": benefit, "aided": aided, "insertion_front_db": front.round(2).tolist(), "insertion_worst_db": worst.round(2).tolist()}


def optimize(patient_dir, side, ears, head, scenes, audiogram, budget=30, dx=SEARCH_DX, log=print, progress=None):
    t0 = time.time()
    lim = _limits(patient_dir)
    log(f"{side}: open ears at {dx} mm")
    ev = Evaluator(patient_dir, side, ears, head, scenes, audiogram, dx, log)
    ctx, aid_dir = os.path.join(patient_dir, "context"), os.path.join(patient_dir, "aid")
    d = len(DIALS)
    n_init = max(6, min(10, budget // 3))
    X0 = qmc.LatinHypercube(d=d, seed=SEED).random(n_init)
    rng = np.random.default_rng(SEED)
    history, X, y = [], [], []
    best = None

    def run(k, u):
        nonlocal best
        p = _params(u, lim)
        did = f"opt{k}"
        rep = epc.build(ctx, aid_dir, p, did, log=lambda m: None)
        rec = {"k": k, "design_id": did, "params": p, "ok": bool(rep["ok"])}
        if not rep["ok"]:
            rec["reasons"] = [r.get("message", r) if isinstance(r, dict) else r for r in rep.get("reasons", [])][:2]
            shutil.rmtree(os.path.join(aid_dir, did), ignore_errors=True)
        else:
            try:
                r = ev.evaluate(os.path.join(aid_dir, did, "earpiece_print.stl"))
                rec.update(r, geometry={k2: v for k2, v in rep.get("geometry", {}).items() if isinstance(v, (int, float, str))})
            except (AssertionError, ValueError) as e:            # e.g. the piece covers the eardrum receiver
                rec.update(ok=False, reasons=[str(e)])
        history.append(rec)
        X.append(u)
        y.append(rec["benefit"] if rec["ok"] else np.nan)
        if rec["ok"] and (best is None or rec["benefit"] > best["benefit"]):
            if best:
                shutil.rmtree(os.path.join(aid_dir, best["design_id"]), ignore_errors=True)
            best = rec
        elif rec["ok"]:
            shutil.rmtree(os.path.join(aid_dir, did), ignore_errors=True)
        log(f"{side} {k + 1}/{budget}: " + (f"benefit {rec['benefit']:+.3f}" if rec["ok"] else "rejected") +
            (f"  (best {best['benefit']:+.3f})" if best else ""))
        if progress:
            progress({"side": side, "done": k + 1, "budget": budget, "best": best["benefit"] if best else None})

    for k, u in enumerate(X0):
        run(k, u)
    for k in range(n_init, budget):
        Xa, ya = np.array(X), np.array(y, float)
        ok = np.isfinite(ya)
        if ok.sum() < 3:
            run(k, rng.random(d)); continue
        yfill = np.where(ok, ya, np.nanmin(ya) - 0.02)                  # failed builds: a bit worse than the worst
        gp = GaussianProcessRegressor(ConstantKernel(1.0) * Matern(length_scale=np.full(d, 0.3), nu=2.5) + WhiteKernel(1e-4),
                                      normalize_y=True, n_restarts_optimizer=2, random_state=SEED).fit(Xa, yfill)
        cand = np.vstack([rng.random((3000, d)), np.clip(Xa[np.nanargmax(yfill)] + rng.normal(0, 0.08, (1000, d)), 0, 1)])
        mu, sd_ = gp.predict(cand, return_std=True)
        from scipy.stats import norm
        imp = mu - np.nanmax(yfill) - 0.005
        z = imp / np.maximum(sd_, 1e-9)
        ei = imp * norm.cdf(z) + sd_ * norm.pdf(z)
        run(k, cand[int(np.argmax(ei))])

    return {"side": side, "best": best, "history": history, "unaided": ev.unaided, "weights": ev.w.tolist(),
            "scene_names": [s.get("name", "") for s in ev.scenes], "dx_mm": dx, "elapsed_s": round(time.time() - t0, 1),
            "freqs_hz": SII_FREQS.tolist()}
