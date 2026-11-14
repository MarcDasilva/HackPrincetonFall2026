"""Baseline runs (spec 05): every scene through a healthy ear and this patient's ear, no device.

    python -m hornsim.runner <patient_dir> [--workers N] [--no-neurograms]

Needs <patient_dir>/context/canals.json (hornsim.context) and <patient_dir>/waves/az*_transfer.npz
(hornsim.wavesim, azimuths 0 and 90). Writes <patient_dir>/scenes/:
    scenes.json       the 96 scenes (hornsim.scenes)
    progress.jsonl    one line per finished scene, appended live, for the frontend to follow
    baseline.json     per scene: deficit_db[18], deficit_weighted[18], SII and HASPI for both ears
    neurograms/       <scene>_{healthy,impaired}.png for one showcase scene per condition

Without a device the canal sample cannot change anything, so the 4 canal scenes of each
(condition, clip) share ONE run.
"""
import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
from scipy.signal import fftconvolve

from . import scenes as sc
from . import scoring
from .audio import apply_gain
from .context import load_defaults

FS = 24000
C = 343.0
HEAD_RADIUS_M = 0.0875     # Brown & Duda (1998)'s sphere
EARLY_S = 0.050            # SII cannot see reverb: reflections after 50 ms count as noise (C50 split)
NEUROGRAM_CFS = np.geomspace(160, 8000, 100)


def sphere_gain_db(deg, f):
    """Head shadow of a rigid sphere re: frontal incidence, one-pole/one-zero model of Brown & Duda
    (1998, IEEE Trans. Speech Audio Process. 6:476), alpha_min 0.1, theta_min 150 deg."""
    def H(az):
        theta = abs((az - 90 + 180) % 360 - 180)            # degrees from the aided ear's axis
        alpha = 1.05 + 0.95 * np.cos(np.radians(theta / 150 * 180))
        w = 2 * np.pi * f * HEAD_RADIUS_M / (2 * C)
        return (1 + 1j * alpha * w) / (1 + 1j * w)
    return 20 * np.log10(np.abs(H(deg) / H(0)))


def direction_gain(waves_dir, deg):
    """(freqs, dB) reaching the eardrum from `deg` relative to the front. Normalised to 0 deg because
    dB HL and SII already assume a frontal talker into a normal open ear — the raw eardrum gain would
    count that ear twice (spec 04). 270 deg is not simulable (flat head plane): spherical head."""
    if deg == 270:
        f = np.geomspace(100, 12000, 200)
        return f, sphere_gain_db(270, f)
    H = lambda a: np.load(os.path.join(waves_dir, f"az{a:03.0f}_el+00_transfer.npz"))
    h, h0 = H(deg), H(0)
    return h["freqs_hz"], 20 * np.log10(np.abs(h["eardrum"]) / np.abs(h0["eardrum"]))


def scene_signals(scene, waves_dir):
    """(reference, speech, noise) on ONE level scale: reference = the dry clip, front, RMS 1."""
    x = sc.clip(scene["clip"])
    to_ear = lambda s, deg: s if deg == 0 else apply_gain(s, FS, *direction_gain(waves_dir, deg))
    speech, noise, n = to_ear(x, scene["talker_deg"]), None, scene["noise"]
    if n and n["type"] == "babble":
        b = np.resize(sc.clip(sc.BABBLE), len(x)) * 10 ** (-n["snr_db"] / 20)
        noise = to_ear(b, n["deg"])
    elif n and n["type"] == "reverb":
        h = sc.reverb_ir(FS, n["rt60_s"], n["seed"])
        k = int(EARLY_S * FS)
        speech, noise = fftconvolve(speech, h[:k])[: len(x)], fftconvolve(speech, np.r_[np.zeros(k), h[k:]])[: len(x)]
    return x, speech, noise


def run_scene(scene, ag_db_hl, waves_dir, seed):
    ag = scoring.audiogram(ag_db_hl)
    normal = scoring.audiogram({f: 0.0 for f in ag_db_hl})
    ref, speech, noise = scene_signals(scene, waves_dir)
    mix = speech if noise is None else speech + noise
    L = scene["level_db"]
    gap = (scoring.band_audibility(speech, noise, FS, normal, L) - scoring.band_audibility(speech, noise, FS, ag, L))
    return {"deficit_db": np.round(gap, 3).tolist(),
            "deficit_weighted": np.round(gap * scoring.SII_IMPORTANCE, 4).tolist(),
            "sii_healthy": round(scoring.sii(speech, noise, FS, normal, L), 4),
            "sii_unaided": round(scoring.sii(speech, noise, FS, ag, L), 4),
            "haspi_healthy": round(scoring.haspi(ref, mix, FS, normal, L, seed), 4),
            "haspi_unaided": round(scoring.haspi(ref, mix, FS, ag, L, seed), 4)}


def neurogram_pair(scene, ag_db_hl, waves_dir, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _, speech, noise = scene_signals(scene, waves_dir)
    mix = speech if noise is None else speech + noise
    ears = {"healthy": (np.ones(len(NEUROGRAM_CFS)), np.ones(len(NEUROGRAM_CFS))),
            "impaired": scoring.hair_cells(scoring.audiogram(ag_db_hl), NEUROGRAM_CFS)}
    ngs = {k: scoring.neurogram(mix, FS, co, ci, scene["level_db"], NEUROGRAM_CFS) for k, (co, ci) in ears.items()}
    vmax = max(n.max() for n in ngs.values())          # SAME colour scale for both ears
    files = []
    for k, n in ngs.items():
        fig, ax = plt.subplots(figsize=(6, 3))
        im = ax.pcolormesh(np.arange(n.shape[1]) * 0.0064, NEUROGRAM_CFS, n, vmin=0, vmax=vmax, cmap="magma")
        ax.set_yscale("log"); ax.set_xlabel("s"); ax.set_ylabel("CF (Hz)")
        ax.set_title(f"{scene['name']}, {k} ear (Zilany 2014 model, simulated)", fontsize=9)
        fig.colorbar(im, ax=ax, label="spikes/s per fibre")
        fig.tight_layout()
        files.append(f"{scene['id']}_{k}.png")
        fig.savefig(os.path.join(out_dir, files[-1]), dpi=100)
        plt.close(fig)
    return files


def run(patient_dir, workers=None, neurograms=True, log=print):
    t0 = time.time()
    out = os.path.join(patient_dir, "scenes")
    os.makedirs(os.path.join(out, "neurograms"), exist_ok=True)
    scenes = sc.build(patient_dir)
    json.dump(scenes, open(os.path.join(out, "scenes.json"), "w"), indent=1)
    ag = {float(k): float(v) for k, v in sc.load_request(patient_dir)["audiogram_db_hl"].items()}
    waves, seed = os.path.join(patient_dir, "waves"), load_defaults()["evaluation"]["haspi_seed"]
    groups = {}
    for s in scenes:
        groups.setdefault((s["condition"], s["clip"]), []).append(s)
    if neurograms:
        try:
            import cochlea  # noqa: F401
        except ImportError as e:
            log(f"neurograms skipped: {e}")
            neurograms = False
    showcase = [g[0] for (cond, clip), g in groups.items() if clip == sc.CLIPS[0]]

    results, figs, t_base = {}, {}, None
    progress = open(os.path.join(out, "progress.jsonl"), "w")
    with ProcessPoolExecutor(workers) as ex:
        jobs = {ex.submit(run_scene, g[0], ag, waves, seed): key for key, g in groups.items()}
        if neurograms:
            jobs |= {ex.submit(neurogram_pair, s, ag, waves, os.path.join(out, "neurograms")): s["id"] for s in showcase}
        for fut in as_completed(jobs):
            key = jobs[fut]
            if isinstance(key, str):
                figs[key] = [f"neurograms/{f}" for f in fut.result()]
                log(f"neurograms {key} ({time.time() - t0:.1f}s)")
                continue
            r = fut.result()
            for s in groups[key]:
                results[s["id"]] = {"id": s["id"]} | r
                line = {"scene": s["id"], "t_ms": round((time.time() - t0) * 1000), "sii_unaided": r["sii_unaided"],
                        "haspi_unaided": r["haspi_unaided"]}
                progress.write(json.dumps(line) + "\n"); progress.flush()
                log(json.dumps(line))
            if len(results) == len(scenes):
                t_base = time.time() - t0
    progress.close()

    json.dump({"note": ["Predictions from simulation, no device. Healthy ear = 0 dB HL.",
                        "deficit_db = SII band audibility (dB, range -15..+15) healthy minus impaired; "
                        "deficit_weighted = deficit_db x ANSI S3.5-1997 band importance.",
                        "Direction filters are relative to a frontal talker: 45-180 deg from the wave simulation "
                        "of this ear (flat head plane); 270 deg from a spherical head (Brown & Duda 1998).",
                        "C5 reverb is synthetic (decaying noise, RT60 0.6 s); SII counts reflections after 50 ms "
                        "as noise.",
                        "The canal sample has no effect without a device: scenes differing only in canal share "
                        "one run."],
               "bands_hz": scoring.SII_FREQS.tolist(), "importance": scoring.SII_IMPORTANCE.tolist(),
               "audiogram_db_hl": ag, "haspi_seed": seed,
               "runtime_s": {"baseline": round(t_base, 1), "total": round(time.time() - t0, 1)},
               "neurograms": figs, "results": [results[s["id"]] for s in scenes]},
              open(os.path.join(out, "baseline.json"), "w"), indent=1)
    log(f"{len(scenes)} scenes in {t_base:.1f}s ({len(groups)} runs), total {time.time() - t0:.1f}s -> {out}")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("patient_dir")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--no-neurograms", action="store_true")
    a = ap.parse_args()
    run(a.patient_dir, a.workers, not a.no_neurograms)
