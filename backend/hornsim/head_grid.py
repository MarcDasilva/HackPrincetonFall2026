"""Export a dummy-head wave grid with BOTH of the patient's ears for the browser's scene grid (/sim).

    python -m hornsim.head_grid [out.json] [--left-ear left.ply] [--right-ear right.ply] [--dx 3.0]

The flat head plane of hornsim.wavesim is replaced by a head-and-torso simulator shape (head,
neck, shoulders) with the two reconstructed pinnae mounted at its ear positions. So:
  - one FDTD run per speaker gives the pressure at BOTH eardrums (two receivers, one grid);
  - speakers go all the way round (0-360°): the head shadows the far ear, which the flat plane
    could not model;
  - shoulder and head reflections reach the canal the way they do on a person.

Head frame (mm): origin midway between the points where the canals meet the head's curve, +x toward the RIGHT ear, +y up,
-z forward (the same handedness as AudioEar's right-ear frame, so the right ear maps by translation
only). earrecon mirrors z for a left ear, so the left ear maps by a 180° turn about y, a proper
rotation that keeps its (already mirrored) shape.

Each ear is first put with its canal opening on the head's curve, then slid straight toward the
head centre (x only, fit_inset) until half of its edge touches the head. Per ear, inside the pinna's
outline and within PINNA_SLAB_MM medial of the canal opening, the pinna height field decides solid
vs air exactly as in wavesim; everywhere else the head shape does. So where the slid-in ear's bowl
(concha) dips below the head's curve, the head is carved away under it.
The canal is the same rigid tube closed by the lossy eardrum (wavesim.CANAL_LEN_MM, EARDRUM_Z).

Head shape: the patient's, fitted from a front photo (hornsim.head_shape: measured face outline and
breadth, assumed depth and crown), or without one the average head (ITU-T P.58 breadth 152 mm,
length ~194 mm). The neck and shoulders are a generic shape, an ASSUMPTION.

Talkers are far away: the browser injects each one as a plane wave (total-field/scattered-field
source), so only its direction matters and the box holds just the head and shoulder tops.

Writes JSON: shape, dx_mm, origin_mm, solid (base64 bit-packed, C order), radius_mm (where the UI
draws speakers), the head parts (for display), and per ear: eardrum cells, receiver, canal
point/axis/diameter, decimated mesh.
"""
import argparse
import base64
import json
import math
import os

import numpy as np

from . import wavesim as ws
from . import head_shape
from .context import load_defaults

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = 9
# Talkers are FAR (plane waves injected on a box around the head, frontend lib/fdtd.ts
# runPlaneWave), so the grid only has to hold the head, pinnae and shoulder tops plus air.
EAR_PAD_MM = 50.0        # beside the head: the pinnae stand ~30 mm off it, plus air and the TF/SF margin
BOX_PAD_MM = 23.0        # in front, behind and above the head
Y_MIN_MM = -210.0        # floor: takes in the tops of the shoulders, not the whole torso
RADIUS_MM = 170.0        # where the UI draws the speakers (outside the box); only their direction is simulated
PINNA_SLAB_MM = 12.0     # depth medial of the canal opening over which the pinna height field rules
EL_RANGE = (-30.0, 60.0) # below -30° the wave would arrive through the truncated torso

class Mount:
    """Ear frame <-> head frame for one ear. s = +1 right (translation only), -1 left (turn about y)."""

    def __init__(self, world, side, head, mesh=None):
        self.s = 1.0 if side == "right" else -1.0
        self.c = np.asarray(world.canal_point, float)                 # canal opening, ear frame
        self.R = np.diag([self.s, 1.0, self.s])
        self.inset = 0.0
        self.anchor = np.array([self.s * head.canal_anchor_x(), 0.0, 0.0])  # canal opening, head frame
        if mesh is not None:
            self.inset = fit_inset(self.to_head(mesh.vertices), mesh.faces, self.s, head)
            self.anchor[0] -= self.s * self.inset

    def to_head(self, p):
        return (np.asarray(p, float) - self.c) @ self.R.T + self.anchor

    def to_ear(self, p):
        return (np.asarray(p, float) - self.anchor) @ self.R + self.c   # R is its own inverse

    def dir_to_head(self, v):
        return np.asarray(v, float) @ self.R.T


def pinna_surface(mesh, mount, ys, zs, deepest=False):
    """Lateral surface of the pinna over the head grid's (y, z) lattice, in head-frame x.
    NaN outside the ear's outline (rays along the ear's -x that miss the mesh). deepest=True takes the
    most medial hit instead of the first (under an overhang, the bowl floor rather than the overhang)."""
    yy, zz = np.meshgrid(ys, zs, indexing="ij")
    pe = mount.to_ear(np.stack([np.zeros(yy.size), yy.ravel(), zz.ravel()], 1))
    lo, hi = mesh.bounds
    near = (pe[:, 1] >= lo[1] - 1) & (pe[:, 1] <= hi[1] + 1) & (pe[:, 2] >= lo[2] - 1) & (pe[:, 2] <= hi[2] + 1)
    surf = np.full(yy.size, np.nan)
    idx = np.flatnonzero(near)
    if len(idx):
        start = np.stack([np.full(len(idx), hi[0] + 1.0), pe[idx, 1], pe[idx, 2]], 1)
        loc, ray, _ = mesh.ray.intersects_location(start, np.tile([-1.0, 0, 0], (len(idx), 1)), multiple_hits=deepest)
        if deepest:          # keep the most medial hit per ray
            ex = np.full(len(idx), np.inf)
            np.minimum.at(ex, ray, loc[:, 0])
            hit = np.isfinite(ex)
            surf[idx[hit]] = mount.anchor[0] + mount.s * (ex[hit] - mount.c[0])
        else:
            surf[idx[ray]] = mount.anchor[0] + mount.s * (loc[:, 0] - mount.c[0])   # ear x -> head x
    return surf.reshape(yy.shape)


SURF_DX = 1.0            # mm, lattice of the exported pinna surface (display carving)
SURF_PAD_MM = 3.0        # display carve reaches this far past the ear's outline
EAR_FIT_QUANTILE = 0.5  # slide each ear in until this share of its edge touches the head


def fit_inset(v, faces, s, head):
    """mm to slide an ear toward the head centre (along x only) so it sits on the head. The ear mesh is
    an open shell (the pinna as photographed) whose edge floats a few mm off the head's curve when the
    canal opening alone is put on the surface. Slide until EAR_FIT_QUANTILE of that edge is at or inside
    the head; the rest (the helix rim) stands off it, as on a person. v in head frame, canal on surface."""
    faces = np.asarray(faces)
    e = np.sort(np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), 1)
    uniq, cnt = np.unique(e, axis=0, return_counts=True)
    edge = np.unique(uniq[cnt == 1])
    if not len(edge):
        return 0.0
    gap = s * v[edge, 0] - head.surface_x(v[edge, 1], v[edge, 2])
    return float(max(0.0, np.quantile(gap, EAR_FIT_QUANTILE)))


def to_index(p, origin, dx, shape):
    i = np.round((np.asarray(p) - origin) / dx).astype(int)
    if np.any(i < 0) or np.any(i >= shape):
        raise ValueError(f"point {p} is outside the grid")
    return tuple(int(v) for v in i)


def export(out, ears, dx=3.0, faces=7000, head=None):
    """ears: {"left": ear.ply, "right": ear.ply} (earrecon output: the left one already mirrored).
    head: a hornsim.head_shape.HeadShape (the patient's, from a front photo); default the average head."""
    head = head or head_shape.average()
    cfg = load_defaults()
    cfg["ear_world"]["landmarks_xlsx"] = os.environ.get(
        "LANDMARKS_XLSX", os.path.join(HERE, "..", "third_party", "AudioEar", "data", "55_landmarks.xlsx"))
    wmax, zmin, zmax, ytop = head.extent()
    half = max(wmax + EAR_PAD_MM, -zmin + BOX_PAD_MM, zmax + BOX_PAD_MM)
    half = dx * math.ceil(half / dx)          # whole cells: x = 0 falls between mirrored cells, so both ears grid alike
    lo = np.array([-half, Y_MIN_MM, -half])
    hi = np.array([half, ytop + BOX_PAD_MM, half])
    shape = tuple(int(math.ceil(s / dx)) + 1 for s in hi - lo)
    xs, ys, zs = (lo[i] + dx * np.arange(shape[i]) for i in range(3))
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    P = np.stack([X, Y, Z], -1)
    solid = head.head_solid(P)

    loaded = {}
    for side in ("left", "right"):
        mesh, world, _ = ws.load_ear(ears[side], side == "left", cfg)
        m = Mount(world, side, head, mesh)
        surf = pinna_surface(mesh, m, ys, zs)                       # (ny, nz) head-frame x
        inside = ~np.isnan(surf)
        lat = m.s * (X - m.anchor[0])                               # mm lateral of the canal opening
        zone = inside[None] & (lat > -PINNA_SLAB_MM) & (lat < 60)
        pinna = m.s * (X - surf[None]) < 0                          # medial of the pinna surface
        solid = np.where(zone, pinna, solid)
        loaded[side] = (mesh, world, m)

    ear_out = {}
    for side, (mesh, world, m) in loaded.items():
        axis = m.dir_to_head(world.canal_axis)
        rel = P - m.anchor
        t = rel @ axis
        r = np.linalg.norm(rel - t[..., None] * axis, axis=-1)
        rc = world.canal_diameter_mm / 2
        solid &= ~((t > -3) & (t < ws.CANAL_LEN_MM) & (r < rc))
        drum = (t >= ws.CANAL_LEN_MM - dx) & (t < ws.CANAL_LEN_MM) & (r < rc)
        ear_out[side] = {"drum": drum, "axis": axis, "mesh": mesh, "world": world, "mount": m}

    for side, e in ear_out.items():
        m, world, axis = e["mount"], e["world"], e["axis"]
        drum = e["drum"] & ~solid
        rec = None
        for k in np.arange(ws.CANAL_LEN_MM - 1.5, 0, -dx / 2):   # coarse grid: back up the canal until in air
            rec = to_index(m.anchor + axis * k, lo, dx, shape)
            if not solid[rec]:
                break
        assert rec is not None and not solid[rec], f"{side} receiver is inside the wall"
        assert drum.any(), f"{side} eardrum has no air cells at {dx} mm"
        full = e["mesh"]
        mesh = full
        if len(mesh.faces) > faces:
            try:
                mesh = mesh.simplify_quadric_decimation(face_count=faces)
            except ImportError:
                pass
        v, f = m.to_head(mesh.vertices), np.asarray(mesh.faces)
        # the pinna's lateral surface on a 1 mm (y, z) lattice: the display carves the head below it,
        # which is what the grid's solid does (inside the outline the pinna height field rules)
        lo_e, hi_e = v[:, 1:].min(0) - 1, v[:, 1:].max(0) + 1
        sy_, sz_ = np.arange(lo_e[0], hi_e[0] + SURF_DX, SURF_DX), np.arange(lo_e[1], hi_e[1] + SURF_DX, SURF_DX)
        surf = pinna_surface(full, m, sy_, sz_, deepest=True)
        # widen the outline by SURF_PAD_MM with the nearest edge value, so the display's carve does not
        # stop on a hard edge that the head's triangles would cross (display only; the grid is unchanged)
        from scipy import ndimage
        dist, (iy, iz) = ndimage.distance_transform_edt(np.isnan(surf), return_indices=True)
        surf = np.where(np.isnan(surf) & (dist * SURF_DX <= SURF_PAD_MM), surf[iy, iz], surf)
        e.update(out={
            "eardrum": np.flatnonzero(drum.ravel()).tolist(), "receiver": list(rec),
            "canal_point_mm": m.anchor.round(3).tolist(), "canal_axis": axis.round(5).tolist(),
            "canal_diameter_mm": float(world.canal_diameter_mm), "inset_mm": round(m.inset, 2),
            "mesh": {"verts": v.round(2).ravel().tolist(), "faces": f.ravel().tolist()},
            "surface": {"y0": round(float(sy_[0]), 3), "z0": round(float(sz_[0]), 3), "d": SURF_DX,
                        "ny": len(sy_), "nz": len(sz_),
                        "x": [None if np.isnan(x) else round(float(x), 2) for x in surf.ravel()]},
        })

    data = {
        "source": "hornsim.head_grid", "version": VERSION, "shape": list(shape), "dx_mm": dx,
        "origin_mm": lo.round(3).tolist(), "radius_mm": RADIUS_MM, "el_range": list(EL_RANGE),
        "canal_len_mm": ws.CANAL_LEN_MM, "eardrum_z": ws.EARDRUM_Z,
        "front": [0.0, 0.0, -1.0], "right": [1.0, 0.0, 0.0], "head": head.to_json(),
        "solid_b64": base64.b64encode(np.packbits(solid.ravel())).decode(),
        "ears": {s: e["out"] for s, e in ear_out.items()},
    }
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    json.dump(data, open(tmp, "w"))
    os.replace(tmp, out)
    print(f"head grid {shape} at {dx} mm, {solid.mean() * 100:.0f}% solid, eardrum cells "
          f"L {len(data['ears']['left']['eardrum'])} R {len(data['ears']['right']['eardrum'])} -> {out} "
          f"({os.path.getsize(out) / 1e3:.0f} kB)")
    return data


def mirrored_mean_ear(out_dir):
    """The average ear as a LEFT ear, mirrored the way earrecon mirrors a left reconstruction."""
    import trimesh
    from earrecon.reconstruct import mean_ear
    path = os.path.join(out_dir, "ear.ply")
    if os.path.exists(path):
        return path
    src = mean_ear(os.path.join(out_dir, "_right"))
    m = trimesh.load(src, process=False)
    v = m.vertices.copy()
    v[:, 2] *= -1
    trimesh.Trimesh(v, m.faces[:, ::-1], process=False).export(path)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=os.path.join(HERE, "..", "..", "frontend", "public", "sim", "head_grid.json"))
    ap.add_argument("--left-ear", help="left ear.ply from earrecon (already mirrored); default: the mirrored average ear")
    ap.add_argument("--right-ear", help="right ear.ply from earrecon; default: the model's average ear")
    ap.add_argument("--dx", type=float, default=3.0)
    ap.add_argument("--head", help="head shape JSON (hornsim.head_shape HeadShape.to_json); default: the average head")
    a = ap.parse_args()
    import tempfile
    tmp = tempfile.mkdtemp()
    if not a.right_ear:
        from earrecon.reconstruct import mean_ear
        a.right_ear = mean_ear(os.path.join(tmp, "right"))
    if not a.left_ear:
        a.left_ear = mirrored_mean_ear(os.path.join(tmp, "left"))
    hs = head_shape.HeadShape.from_json(json.load(open(a.head))) if a.head else None
    export(a.out, {"left": a.left_ear, "right": a.right_ear}, a.dx, head=hs)
