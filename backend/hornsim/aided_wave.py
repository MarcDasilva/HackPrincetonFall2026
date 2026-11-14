"""Check the 1D acoustic model against the 3D wave sim for one built earpiece.

    python -m hornsim.aided_wave <patient_dir> <design_id> [--az 0 90] [--dist 60] [--dx 1.0]

Insertion gain measured directly: the SAME click from the SAME speaker, once with the open ear and
once with the earpiece's print solid voxelized into the grid, both through hornsim.wavesim's own
geometry (pinna height field, flat head plane, rigid canal closed by the lossy eardrum) and solver.

    G_wave(f) = P_eardrum(aided) / P_eardrum(open)

The 1D model (hornsim.acoustics.insertion_gain) is evaluated for the same design on the same canal
(wavesim's CANAL_LEN_MM whole canal), so the two numbers answer the same question. Differences come
from what the 1D model leaves out: diffraction around the piece, the mouth sitting proud of the
concha, non-plane waves in the wide concha and bore, and direction.

Writes <patient_dir>/aid/<design_id>/wave_check.json.
"""
import argparse
import json
import math
import os
import time

import numpy as np
import torch
import trimesh

from . import acoustics, scoring
from . import wavesim as ws
from .context import load_defaults

PER_BAND = 5


def _cfg(patient_dir):
    cfg = json.load(open(os.path.join(patient_dir, "context", "context.json")))["config"]
    base = load_defaults()
    base["ear_world"].update(cfg["ear_world"])
    return cfg, base


def band_db(f, H):
    """Power-mean |H|² inside each SII one-third-octave band."""
    out = []
    for fc in scoring.SII_FREQS:
        lo, hi = fc * 2 ** (-1 / 6), fc * 2 ** (1 / 6)
        k = (f >= lo) & (f < hi)
        if k.sum() < 2:                                     # low bands: interpolate on a few points
            ff = fc * 2.0 ** np.linspace(-1 / 6, 1 / 6, PER_BAND)
            p = np.interp(ff, f, np.abs(H) ** 2)
        else:
            p = np.abs(H[k]) ** 2
        out.append(10 * np.log10(p.mean()))
    return np.array(out)


def measure(patient_dir, design_id, azimuths=(0,), dist=60.0, dx=1.0, log=print):
    t0 = time.time()
    cfg, full = _cfg(patient_dir)
    P = cfg["patient"]
    left = P.get("side", "right") == "left"
    mesh, world, front = ws.load_ear(P["ear_mesh"], left, full)
    piece = trimesh.load(os.path.join(patient_dir, "aid", design_id, "earpiece_print.stl"), force="mesh")
    design = json.load(open(os.path.join(patient_dir, "aid", design_id, "design.json")))
    x_head = float(world.canal_point[0])
    dev = ws.device()
    dt = 0.99 / math.sqrt(3) * dx * 1e-3 / ws.C
    n = int(6e-3 / dt)
    sig = ws.click(n, dt)
    runs = []
    for az in azimuths:
        spk = ws.speaker_position(world, front, az, 0.0, dist)
        origin, shape = ws.grid_for(mesh, world, [spk, *piece.bounds], dx)
        solid_open = ws.solid_mask(mesh, world, x_head, origin, shape, dx)
        # voxelize the print solid: only cells inside its bounding box need the inside test
        lo = np.clip(np.floor((piece.bounds[0] - origin) / dx).astype(int), 0, None)
        hi = np.minimum(np.ceil((piece.bounds[1] - origin) / dx).astype(int) + 1, shape)
        idx = np.stack(np.meshgrid(*[np.arange(a, b) for a, b in zip(lo, hi)], indexing="ij"), -1).reshape(-1, 3)
        inside = piece.contains(origin + idx * dx)
        solid_aid = solid_open.copy()
        solid_aid[tuple(idx[inside].T)] = True
        added = int(inside.sum())
        rec = ws.to_index(world.canal_point + world.canal_axis * (ws.CANAL_LEN_MM - 1.5), origin, dx, shape)
        if solid_aid[rec]:
            raise ValueError("the eardrum receiver is inside the earpiece; check the canal stem")
        s = ws.to_index(spk, origin, dx, shape)
        while solid_aid[s]:
            s = (s[0] + 1, s[1], s[2])
        drum_open = ws.eardrum_cells(world, origin, shape, dx) & ~solid_open
        drum_aid = drum_open & ~solid_aid
        t1 = time.time()
        p_open = ws.fdtd(solid_open, s, sig, [rec], dev, drum_open)["traces"][:, 0]
        p_aid = ws.fdtd(solid_aid, s, sig, [rec], dev, drum_aid)["traces"][:, 0]
        f, H = ws.transfer(p_aid, p_open, dt, fmax=10000)
        g = band_db(f, H)
        log(f"az {az:g}: grid {shape} at {dx} mm, earpiece {added} cells, 2 runs x {n} steps in {time.time() - t1:.0f}s")
        runs.append({"az": az, "gain_db": g.round(2).tolist(), "cells": list(map(int, shape)), "earpiece_cells": added})

    # 1D model, same design, same whole canal as the wave grid
    p, geo = design["params"], design["geometry"]
    x = {"throat_mm2": p["throat_mm2"], "mouth_mm2": p["mouth_mm2"], "flare_mid1": p["flare_mid1"],
         "flare_mid2": p["flare_mid2"], "length_mm": geo["bore_length_mm"], "canal_stem_mm": p["canal_stem_mm"],
         "vent_count": 0, "vent_diameter_mm": 0.8, "vent_length_mm": 0.0}
    ear = {"canal_diameter_mm": float(world.canal_diameter_mm), "concha_depth_mm": float(world.max_depth_mm),
           "bowl_volume_cc": float(world.bowl_volume_cc), "opening_area_mm2": float(world.opening_area_mm2)}
    canal = {"length_mm": np.array([ws.CANAL_LEN_MM - acoustics.CANAL_SAMPLE_TIP_MM])}
    edges = scoring.SII_FREQS[:, None] * 2.0 ** np.linspace(-1 / 6, 1 / 6, PER_BAND)
    g1 = acoustics.insertion_gain({k: np.array([v]) for k, v in x.items()}, ear, canal, edges.ravel())
    g1 = 10 * np.log10((10 ** (g1.reshape(len(scoring.SII_FREQS), PER_BAND) / 10)).mean(-1))

    out = {"design_id": design_id, "freqs_hz": scoring.SII_FREQS.tolist(), "dx_mm": dx, "dist_mm": dist,
           "canal_len_mm": ws.CANAL_LEN_MM, "model_1d_db": g1.round(2).tolist(), "wave": runs,
           "elapsed_s": round(time.time() - t0, 1),
           "notes": ["wave: hornsim.wavesim geometry and solver, earpiece_print.stl voxelized in, click at "
                     f"{dist:g} mm; 1D: hornsim.acoustics on the same design and a {ws.CANAL_LEN_MM:g} mm canal."]}
    json.dump(out, open(os.path.join(patient_dir, "aid", design_id, "wave_check.json"), "w"), indent=1)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("patient_dir")
    ap.add_argument("design_id")
    ap.add_argument("--az", type=float, nargs="+", default=[0])
    ap.add_argument("--dist", type=float, default=60.0)
    ap.add_argument("--dx", type=float, default=1.0)
    a = ap.parse_args()
    r = measure(a.patient_dir, a.design_id, a.az, a.dist, a.dx)
    print("band     1D    " + "  ".join(f"az{w['az']:g}" for w in r["wave"]))
    for i, fc in enumerate(r["freqs_hz"]):
        print(f"{fc:6g} {r['model_1d_db'][i]:6.1f} " + " ".join(f"{w['gain_db'][i]:6.1f}" for w in r["wave"]))
