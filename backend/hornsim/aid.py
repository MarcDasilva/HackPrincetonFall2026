"""Build a 3D in-ear passive horn aid that fits the patient's concha.

    python -m hornsim.aid <patient_dir> [design.yaml]

Needs <patient_dir>/context/ from hornsim.context. Writes <patient_dir>/aid/:
    aid.glb           the aid alone: translucent shell + coloured air channels (bore, vent)
    aid_in_ear.glb    the same, seated in the translucent ear
    aid_print.stl     printable solid: shell with the bore and vent cut out
    design.json       parameters and what was achieved (length, cutoff, gain, wall)

Geometry:
  shell  = shell space from the ear world (smoothed) + a short canal tip
  bore   = conical spiral from a mouth on the faceplate down to the canal opening,
           then straight through the tip; area flares exponentially throat -> mouth
  vent   = straight channel from faceplate to tip, beside the bore
"""
import json
import os
import sys

import numpy as np
import trimesh
import yaml
from scipy import ndimage
from scipy.spatial import cKDTree

from . import ear_world as ew

DEFAULT = {
    "throat_mm2": 1.0, "mouth_mm2": 22.2,        # handoff doc's example areas (area ratio 22.2)
    "max_path_mm": 130, "min_wall_mm": 0.6,
    "tip_length_mm": 6.0, "tip_clearance_mm": 0.6,
    "vent_diameter_mm": 0.8, "vent_offset_mm": 2.2,
}


def frames(path):
    """Parallel-transport frames along a polyline."""
    t = np.gradient(path, axis=0); t /= np.linalg.norm(t, axis=1, keepdims=True)
    a = np.cross(t[0], [0, 0, 1.0]);  a = a if np.linalg.norm(a) > 1e-3 else np.cross(t[0], [0, 1.0, 0])
    n = [a / np.linalg.norm(a)]
    for i in range(1, len(t)):
        v = n[-1] - np.dot(n[-1], t[i]) * t[i]
        n.append(v / np.linalg.norm(v))
    n = np.array(n)
    return t, n, np.cross(t, n)


def tube(path, radii, seg=28, fr=None):
    """Closed (capped) tube mesh. `radii` is per station, or [station, angle] for a shaped section
    whose angle j points along cos(a_j)·n + sin(a_j)·b of `frames(path)`. Pass `fr` (sliced from a
    longer path's frames) when this tube must line up angle-for-angle with a tube on that path."""
    _, n, b = fr if fr is not None else frames(path)
    if radii.ndim == 2:
        seg = radii.shape[1]
    ang = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    ring = np.cos(ang)[None, :, None] * n[:, None, :] + np.sin(ang)[None, :, None] * b[:, None, :]
    r = radii[:, :, None] if radii.ndim == 2 else radii[:, None, None]
    verts = (path[:, None, :] + r * ring).reshape(-1, 3)
    faces = []
    for i in range(len(path) - 1):
        for j in range(seg):
            a, b2 = i * seg + j, i * seg + (j + 1) % seg
            c, d = a + seg, b2 + seg
            faces += [[a, c, b2], [b2, c, d]]
    s0, s1 = len(verts), len(verts) + 1
    verts = np.vstack([verts, path[0], path[-1]])
    last = (len(path) - 1) * seg
    for j in range(seg):
        faces.append([s0, j, (j + 1) % seg])
        faces.append([s1, last + (j + 1) % seg, last + j])
    m = trimesh.Trimesh(verts, np.array(faces), process=True)
    if m.volume < 0:
        m.invert()
    return m


def spiral(world, R0, turns, n_top, steps=600):
    """Conical spiral in the ear-world frame: wide at the faceplate, closing onto the canal opening."""
    u, w, nrm = world.axes
    c = world.rim_center
    cp = world.canal_point - c
    cp_l = np.array([cp @ u, cp @ w, cp @ nrm])
    vox = world.voxel_centers() - c
    mid = vox[np.abs(vox @ nrm - cp_l[2] / 2) < 1.0]
    start_c = np.array([(mid @ u).mean(), (mid @ w).mean()])        # bowl centre at mid depth
    t = np.linspace(0, 1, steps)
    cen = (1 - t)[:, None] * start_c + t[:, None] * cp_l[:2]
    R = R0 * (1 - t) ** 0.85
    th = 2 * np.pi * turns * t
    du, dw = cen[:, 0] + R * np.cos(th), cen[:, 1] + R * np.sin(th)
    dn = n_top + (cp_l[2] - n_top) * t ** 0.9
    return c + du[:, None] * u + dw[:, None] * w + dn[:, None] * nrm


def clearance(path, world, edt, tip_r, tip_len, top_n):
    """Distance (mm) from each point to the outside of the solid: shell space or canal tip.
    Points above `top_n` (the mouth breaking through the faceplate) count as clear."""
    idx = np.round((path - world.origin) @ world.axes.T / world.voxel_mm).astype(int)
    ok = np.all((idx >= 0) & (idx < world.voxels.shape), axis=1)
    d = np.zeros(len(path))
    d[ok] = edt[tuple(idx[ok].T)]
    rel = path - world.canal_point
    ax_d = rel @ world.canal_axis
    rad_d = np.linalg.norm(rel - ax_d[:, None] * world.canal_axis, axis=1)
    in_tip = (ax_d > -1.5) & (ax_d < tip_len)
    d = np.where(in_tip, np.maximum(d, tip_r - rad_d), d)
    above = (path - world.rim_center) @ world.axes[2] > top_n
    return np.where(above, 99.0, d)


def check(path, radii, world, edt, wall, tip_r, tip_len, top_n):
    """Smallest clearance (mm) to the outside and between neighbouring turns. >= 0 means it fits."""
    d = clearance(path, world, edt, tip_r, tip_len, top_n)
    surf = np.min(d - radii - wall)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    tree = cKDTree(path)
    worst = np.inf
    for i, j in tree.query_pairs(r=2 * radii.max() + wall + 1):
        if abs(s[i] - s[j]) > 2.5 * (radii[i] + radii[j]) + 2:
            worst = min(worst, np.linalg.norm(path[i] - path[j]) - radii[i] - radii[j] - wall)
    return surf, worst, s[-1]


def build(context_dir, out_dir, overrides=None, log=print):
    """Build the aid for the patient whose context is in `context_dir`. Returns design dict."""
    D = dict(DEFAULT)
    D.update(overrides or {})
    out = out_dir
    os.makedirs(out, exist_ok=True)
    cfg = json.load(open(os.path.join(context_dir, "context.json")))["config"]

    mesh, world = ew.build(cfg["patient"]["ear_mesh"], cfg["ear_world"]["landmarks_xlsx"],
                           tuple(cfg["ear_world"]["concha_rim_landmarks"]), cfg["ear_world"]["voxel_mm"],
                           cfg["ear_world"]["fit_tolerance_mm"], cfg["ear_world"]["faceplate_protrusion_mm"],
                           cfg["ear_world"]["canal_opening_diameter_mm"], cfg["patient"]["ear_height_mm"])
    edt = ndimage.distance_transform_edt(world.voxels) * world.voxel_mm

    r_mouth, r_throat = np.sqrt(D["mouth_mm2"] / np.pi), np.sqrt(D["throat_mm2"] / np.pi)
    prot = cfg["ear_world"]["faceplate_protrusion_mm"]
    tip_r = cfg["ear_world"]["canal_opening_diameter_mm"] / 2 - D["tip_clearance_mm"]
    tip_len = D["tip_length_mm"]

    # search spiral size/turns for the longest bore that fits
    best = None
    for R0 in np.arange(2.0, 9.01, 0.5):
        for turns in np.arange(1.0, 4.01, 0.25):
            for n_top in (prot - r_mouth - D["min_wall_mm"], 0.0, -2.0):
                p = spiral(world, R0, turns, n_top)
                s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
                if s[-1] > D["max_path_mm"]:
                    continue
                rad = r_mouth * (r_throat / r_mouth) ** (s / s[-1])     # exponential flare
                surf, inter, L = check(p, rad, world, edt, D["min_wall_mm"], tip_r, tip_len, n_top + 0.5)
                if surf >= -0.1 and inter >= 0 and (best is None or L > best[0]):
                    best = (L, R0, turns, n_top, p, rad, surf, inter)
    if best is None:
        raise ValueError("no spiral fits this concha with these areas; reduce mouth area or wall")
    L, R0, turns, n_top, path, rad, surf, inter = best

    # mouth riser up through the faceplate; tip run down the canal
    nrm, ax = world.axes[2], world.canal_axis
    riser = path[0] + np.linspace(prot + 1.5 - (path[0] - world.rim_center) @ nrm, 0, 12)[:-1, None] * nrm
    tipn = np.linspace(0, D["tip_length_mm"] + 1.0, 14)[1:]
    tip = path[-1] + tipn[:, None] * ax
    full = np.vstack([riser, path, tip])
    full_r = np.r_[np.full(len(riser), r_mouth), rad, np.full(len(tip), r_throat)]
    bore = tube(full, full_r)

    # shell = smoothed shell space + canal tip
    shell = ew.shell_space_mesh(world)
    trimesh.smoothing.filter_taubin(shell, iterations=25)
    tip_cyl = trimesh.creation.cylinder(radius=tip_r, segment=[world.canal_point - 1.5 * ax, world.canal_point + D["tip_length_mm"] * ax], sections=48)
    shell = trimesh.boolean.union([shell, tip_cyl], engine="manifold")

    # vent: straight channel faceplate -> tip, offset from the canal axis
    # try directions and offsets around the canal axis; keep the route with most wall to the bore
    e1 = np.cross(ax, world.axes[0]); e1 /= np.linalg.norm(e1); e2 = np.cross(ax, e1)
    vr, btree = D["vent_diameter_mm"] / 2, cKDTree(full)
    best_v = None
    # faceplate targets: centres of top-layer voxels with room around them
    top_k = world.voxels.shape[2] - 1
    tops = np.argwhere(world.voxels[:, :, top_k] & (edt[:, :, top_k - 4] > vr + 1.0))
    tops = world.origin + np.c_[tops, np.full(len(tops), top_k)] @ (world.axes * world.voxel_mm)
    tops = tops[:: max(1, len(tops) // 60)]
    for ang in np.linspace(0, 2 * np.pi, 12, endpoint=False):
        for off in np.arange(1.2, tip_r - vr - D["min_wall_mm"] + 1e-6, 0.4):
          for tgt in tops:
            side = np.cos(ang) * e1 + np.sin(ang) * e2
            v0 = world.canal_point + off * side + (tip_len + 0.5) * ax
            v1 = tgt + 1.5 * nrm
            vp = np.linspace(v0, v1, 60)
            inside = clearance(vp, world, edt, tip_r, tip_len, prot - 0.2)
            body = ((vp - world.rim_center) @ nrm < prot - 0.2) & ((vp - world.canal_point) @ ax < tip_len - 0.2)
            if np.min(inside[body]) < vr + 0.3:
                continue  # vent would break out of the shell's skin side
            dd, ii = btree.query(vp)
            c = np.min(dd - full_r[ii] - vr)
            if best_v is None or c > best_v[0]:
                best_v = (c, vp)
    if best_v is None:
        raise ValueError("no vent route fits; try a smaller vent")
    vent_clear, vent_path = best_v
    vent = tube(vent_path, np.full(len(vent_path), vr), seg=16)

    solid = trimesh.boolean.difference([shell, bore, vent], engine="manifold")
    solid.export(os.path.join(out, "aid_print.stl"))

    # viewing meshes: translucent shell, bright channels clipped to the shell
    bore_in = trimesh.boolean.intersection([bore, shell], engine="manifold")
    vent_in = trimesh.boolean.intersection([vent, shell], engine="manifold")
    shell_v = shell.copy(); shell_v.visual.face_colors = [235, 225, 210, 70]
    bore_v = bore_in.copy(); bore_v.visual.face_colors = [243, 140, 40, 255]
    vent_v = vent_in.copy(); vent_v.visual.face_colors = [60, 140, 255, 255]
    aid = trimesh.Scene()
    aid.add_geometry(shell_v, node_name="shell", geom_name="shell")
    aid.add_geometry(bore_v, node_name="bore", geom_name="bore")
    aid.add_geometry(vent_v, node_name="vent", geom_name="vent")
    aid.export(os.path.join(out, "aid.glb"))
    ear = mesh.copy(); ear.visual = trimesh.visual.ColorVisuals(ear, vertex_colors=np.tile([214, 160, 140, 110], (len(ear.vertices), 1)))
    aid.add_geometry(ear, node_name="ear", geom_name="ear")
    aid.export(os.path.join(out, "aid_in_ear.glb"))

    total_L = L + np.linalg.norm(riser[0] - path[0]) + tipn[-1]
    design = {
        "throat_mm2": D["throat_mm2"], "mouth_mm2": D["mouth_mm2"], "area_ratio": D["mouth_mm2"] / D["throat_mm2"],
        "flare": "exponential",
        "spiral": {"R0_mm": float(R0), "turns": float(turns), "top_mm": float(n_top)},
        "bore_length_mm": round(float(total_L), 1),
        "est_cutoff_hz": round(343000 / (4 * total_L)),
        "est_max_gain_db": round(10 * np.log10(D["mouth_mm2"] / D["throat_mm2"]), 1),
        "min_wall_to_skin_side_mm": round(float(surf + D["min_wall_mm"]), 2),
        "min_wall_between_turns_mm": round(float(inter + D["min_wall_mm"]), 2),
        "vent_diameter_mm": D["vent_diameter_mm"], "vent_wall_to_bore_mm": round(float(vent_clear), 2),
        "shell_volume_cc": round(shell.volume / 1000, 2), "bore_volume_cc": round(bore_in.volume / 1000, 2),
        "printable_solid_watertight": bool(solid.is_watertight), "print_volume_cc": round(solid.volume / 1000, 2),
        "notes": ["est_* use the simple horn formulas; the design loop replaces them with the 1D model + losses.",
                  "Canal opening position/size are assumed (not visible in a photo)."],
    }
    json.dump(design, open(os.path.join(out, "design.json"), "w"), indent=1)
    log(f"aid: bore {design['bore_length_mm']} mm, {turns} turns, watertight {design['printable_solid_watertight']}")
    return design


if __name__ == "__main__":
    # python -m hornsim.aid <patient_dir> [design.yaml]
    pdir = sys.argv[1]
    over = yaml.safe_load(open(sys.argv[2])) if len(sys.argv) > 2 else None
    print(json.dumps(build(os.path.join(pdir, "context"), os.path.join(pdir, "aid"), over), indent=1))
