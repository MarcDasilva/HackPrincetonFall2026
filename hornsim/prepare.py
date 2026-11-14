"""Build everything the design loop needs for one patient (no design search here).

    .venv/bin/python prepare.py [config.yaml]

Writes out/<patient id>/context/:
    ear_world.npz        shell-space voxels, canal opening, rim, frame
    ear_world.glb        ear + shell space + canal marker, for viewing
    canals.json          32 sampled residual canals
    speech/*.wav         reference and input clips (RMS 1)
    references.json      HASPI: healthy check, unaided, ceiling (best linear prescription)
    context.json         everything above summarised, plus the config used
    summary.png          one-page picture of the context
"""
import json
import os
import sys
import time

import numpy as np
import soundfile as sf
import trimesh
import yaml
from scipy.stats import qmc

from hornsim import audio, ear_world, scoring

HERE = os.path.dirname(os.path.abspath(__file__))


def main(cfg_path):
    cfg = yaml.safe_load(open(cfg_path))
    P, E, C, S, V = cfg["patient"], cfg["ear_world"], cfg["canal"], cfg["speech"], cfg["evaluation"]
    out = os.path.join(HERE, "out", P["id"], "context")
    os.makedirs(os.path.join(out, "speech"), exist_ok=True)
    rel = lambda p: os.path.join(HERE, p)
    t0 = time.time()

    # 1. ear world
    mesh, world = ear_world.build(rel(P["ear_mesh"]), rel(E["landmarks_xlsx"]), tuple(E["concha_rim_landmarks"]),
                                  E["voxel_mm"], E["fit_tolerance_mm"], E["faceplate_protrusion_mm"],
                                  E["canal_opening_diameter_mm"], P["ear_height_mm"])
    world.save(os.path.join(out, "ear_world.npz"))
    space = ear_world.shell_space_mesh(world)
    space.visual.face_colors = [243, 154, 61, 140]
    ear = mesh.copy()
    ear.visual = trimesh.visual.ColorVisuals(ear, vertex_colors=np.tile([220, 170, 150, 90], (len(ear.vertices), 1)))
    marker = trimesh.creation.cylinder(radius=E["canal_opening_diameter_mm"] / 2, height=6,
                                       segment=[world.canal_point, world.canal_point + 6 * world.canal_axis])
    marker.visual.face_colors = [80, 140, 255, 200]
    trimesh.Scene([ear, space, marker]).export(os.path.join(out, "ear_world.glb"))
    print(f"ear world: bowl {world.bowl_volume_cc:.2f} cc, shell space {world.shell_volume_cc:.2f} cc, "
          f"opening {world.opening_area_mm2:.0f} mm2, depth {world.max_depth_mm:.1f} mm  ({time.time()-t0:.1f}s)")

    # 2. canal samples (Latin hypercube over residual volume)
    lo, hi = C["residual_volume_cc"]
    u = qmc.LatinHypercube(d=1, seed=C["seed"]).random(C["samples"])[:, 0]
    area_cm2 = np.pi * (E["canal_opening_diameter_mm"] / 20) ** 2
    canals = [{"id": i, "volume_cc": round(float(lo + (hi - lo) * x), 4),
               "length_mm": round(float((lo + (hi - lo) * x) / area_cm2 * 10), 2)} for i, x in enumerate(sorted(u))]
    json.dump({"assumed_diameter_mm": E["canal_opening_diameter_mm"], "canals": canals},
              open(os.path.join(out, "canals.json"), "w"), indent=1)
    print(f"canals: {len(canals)} samples, {canals[0]['volume_cc']}-{canals[-1]['volume_cc']} cc")

    # 3. speech clips
    fs = S["sample_rate"]
    clips = []
    for i, c in enumerate(S["clean"]):
        x = audio.tts(c["text"], c["voice"], fs)
        clips.append({"name": f"clean_{i+1}", "voice": c["voice"], "text": c["text"], "reference": x, "input": x})
    for i, c in enumerate(S["noisy"]):
        x = audio.tts(c["text"], c["voice"], fs)
        b = audio.babble(S["babble_voices"], S["babble_text"], fs, len(x))
        mix = x + b * 10 ** (-c["snr_db"] / 20)
        clips.append({"name": f"babble_{i+1}", "voice": c["voice"], "text": c["text"], "snr_db": c["snr_db"],
                      "reference": x, "input": mix})
    for c in clips:
        sf.write(os.path.join(out, "speech", f"{c['name']}_reference.wav"), c["reference"] / 8, fs)
        sf.write(os.path.join(out, "speech", f"{c['name']}_input.wav"), c["input"] / 8, fs)
    print(f"speech: {len(clips)} clips, {sum(len(c['input']) for c in clips)/fs:.1f} s total ({time.time()-t0:.1f}s)")

    # 4. references: healthy check, unaided, ceiling
    ag = scoring.audiogram(P["audiogram_db_hl"])
    normal = scoring.audiogram({f: 0 for f in P["audiogram_db_hl"]})
    flat = (np.array([250.0, 6000.0]), np.zeros(2))
    rx = {name: scoring.prescription_gain(name, ag) for name in V["ceiling_prescriptions"]}
    seed = V["haspi_seed"]
    refs = []
    for c in clips:
        for L in V["levels_db_spl"]:
            r = {"clip": c["name"], "level_db_spl": L}
            r["healthy_check"] = scoring.score_gain({"reference": c["reference"], "input": c["reference"]}, fs, normal, L, *flat, seed)
            r["unaided"] = scoring.score_gain(c, fs, ag, L, *flat, seed)
            r["prescriptions"] = {k: scoring.score_gain(c, fs, ag, L, f, g, seed) for k, (f, g) in rx.items()}
            best = max(r["prescriptions"], key=r["prescriptions"].get)
            r["ceiling"], r["ceiling_from"] = r["prescriptions"][best], best
            if r["unaided"] >= r["ceiling"]:  # amplification hurt here (e.g. loud babble): no gain is best
                r["ceiling"], r["ceiling_from"] = r["unaided"], "no_gain"
            r["headroom"] = round(r["ceiling"] - r["unaided"], 4)
            r["use_in_reward"] = r["headroom"] >= 0.02  # too little room to tell designs apart otherwise
            refs.append(r)
            print(f"  {c['name']:9s} {L} dB  healthy {r['healthy_check']:.3f}  unaided {r['unaided']:.3f}  "
                  f"ceiling {r['ceiling']:.3f} ({best})")
    json.dump({"metric": "HASPI v2 (pyclarity)", "seed": seed, "prescription_gains_db":
               {k: {"freqs_hz": f.tolist(), "gain_db": np.round(g, 2).tolist()} for k, (f, g) in rx.items()},
               "results": refs}, open(os.path.join(out, "references.json"), "w"), indent=1)

    context = {
        "patient": P, "config": cfg,
        "ear_world": {k: (v.tolist() if isinstance(v, np.ndarray) and v.size < 20 else v)
                      for k, v in world.__dict__.items() if k != "voxels"} | {"voxel_shape": list(world.voxels.shape)},
        "canals": "canals.json", "speech": [{k: v for k, v in c.items() if k not in ("reference", "input")} for c in clips],
        "references": "references.json",
        "notes": [
            "Audiogram is the handoff doc's example (placeholder) until a real hearing test is supplied.",
            "Canal opening position and diameter are assumed: AudioEar meshes stop at the visible ear.",
            "Ceiling = best of linear prescriptions (NAL-R, half-gain, full-gain) at each clip and level.",
        ],
    }
    context["ear_world"].pop("rim_points", None)
    json.dump(context, open(os.path.join(out, "context.json"), "w"), indent=1, default=float)

    summary_figure(mesh, world, ag, rx, refs, V["levels_db_spl"], os.path.join(out, "summary.png"))
    print(f"done in {time.time()-t0:.0f}s -> {out}")


def summary_figure(mesh, world, ag, rx, refs, levels, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker

    fig = plt.figure(figsize=(15, 9))
    v, pts = mesh.vertices, world.voxel_centers()
    for i, (h, title) in enumerate([(2, "Side view (as photographed)"), (0, "Front view (depth left-right)")]):
        ax = fig.add_subplot(2, 3, i + 1)
        ax.scatter(v[:, h], v[:, 1], s=1, c="#c9a596", alpha=.5)
        ax.scatter(pts[::3, h], pts[::3, 1], s=1, c="#f39a3d", alpha=.35)
        ax.plot(*np.r_[world.rim_points, world.rim_points[:1]][:, [h, 1]].T, c="#7a3b00", lw=1.5)
        ax.plot(world.canal_point[h], world.canal_point[1], "o", c="#2459c9", ms=9)
        ax.set_aspect("equal"); ax.set_title(title); ax.set_xlabel("mm"); ax.set_ylabel("mm")
    ax = fig.add_subplot(2, 3, 3); ax.axis("off")
    ax.text(0, 1, "Shell space (orange)\n"
            f"  bowl air below rim: {world.bowl_volume_cc:.2f} cc\n"
            f"  usable after fit gap + faceplate: {world.shell_volume_cc:.2f} cc\n"
            f"  opening area: {world.opening_area_mm2:.0f} mm²\n"
            f"  deepest point: {world.max_depth_mm:.1f} mm\n\n"
            "Canal opening (blue): assumed at deepest point,\n"
            f"  diameter {world.canal_diameter_mm} mm (not visible in a photo)\n\n"
            "Rough bore budget: 120 mm × 8 mm² ≈ 1 cc",
            va="top", family="monospace", fontsize=10)

    ax = fig.add_subplot(2, 3, 4)
    f = ag.frequencies
    ax.plot(f, ag.levels, "o-", c="#2459c9", lw=2, label="hearing loss (dB HL)")
    for k, (ff, g) in rx.items():
        ax.plot(ff, g, "--", lw=1.5, label=f"{k} gain (dB)")
    ax.axhspan(0, 13.4, color="#f39a3d", alpha=.12, label="passive horn max ≈13.4 dB")
    ax.set_xscale("log"); ax.set_xticks(f); ax.set_xticklabels([f"{int(x)}" for x in f])
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_xlabel("Hz"); ax.set_title("Audiogram and linear prescriptions"); ax.legend(fontsize=8); ax.grid(alpha=.3)

    ax = fig.add_subplot(2, 3, (5, 6))
    names = sorted({r["clip"] for r in refs}, key=lambda s: (s.startswith("babble"), s))
    x = np.arange(len(names)); wdt = 0.12
    for j, L in enumerate(levels):
        un = [next(r["unaided"] for r in refs if r["clip"] == n and r["level_db_spl"] == L) for n in names]
        ce = [next(r["ceiling"] for r in refs if r["clip"] == n and r["level_db_spl"] == L) for n in names]
        ax.bar(x + (j - 1) * 2.2 * wdt - wdt / 2, un, wdt, color=plt.cm.Blues(0.4 + 0.2 * j), label=f"unaided {L} dB")
        ax.bar(x + (j - 1) * 2.2 * wdt + wdt / 2, ce, wdt, color=plt.cm.Oranges(0.4 + 0.2 * j), label=f"ceiling {L} dB")
    ax.set_xticks(x); ax.set_xticklabels(names); ax.set_ylim(0, 1.05); ax.set_ylabel("HASPI v2")
    ax.set_title("Score floor (unaided) and ceiling (best linear prescription): the reward scales between these")
    ax.legend(ncol=3, fontsize=8); ax.grid(axis="y", alpha=.3)
    plt.tight_layout(); plt.savefig(path, dpi=80)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "config.yaml"))
