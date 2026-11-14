"""Export a coarse wave-sim grid for the browser's live scene grid (frontend /sim route).

    python -m hornsim.sim_grid [out.json] [--ear ear.ply] [--left] [--dx 2.5] [--radius 55]

Uses the SAME geometry as hornsim.wavesim (pinna height field, flat head plane, rigid canal closed
by a lossy eardrum), on a fixed box centred on the canal opening that holds a sphere of `radius` mm,
so every speaker the browser can place on that sphere fits one shared grid. Coarser than wavesim
(2.5 mm vs 1 mm): good to ~7 points per wavelength at 20 kHz cut-off, enough for the 160 Hz–8 kHz SII
bands, and small enough (~50^3 cells) to step in a Web Worker in about a second.

Writes JSON: shape, dx_mm, origin_mm, solid (base64 bit-packed, C order), eardrum cell indices,
receiver index, canal point/axis, front, x_head, and a decimated ear mesh for display.
"""
import argparse
import base64
import json
import math
import os

import numpy as np

from . import wavesim as ws
from .context import load_defaults

HERE = os.path.dirname(os.path.abspath(__file__))
MARGIN_MM = 15.0         # same air gap as wavesim: a speaker near an absorbing face loses output


def export(out, ear_path, left=False, dx=2.5, radius=45.0, faces=3000):
    cfg = load_defaults()
    cfg["ear_world"]["landmarks_xlsx"] = os.environ.get(
        "LANDMARKS_XLSX", os.path.join(HERE, "..", "third_party", "AudioEar", "data", "55_landmarks.xlsx"))
    mesh, world, front = ws.load_ear(ear_path, left, cfg)
    x_head = float(world.canal_point[0])
    c = world.canal_point
    canal_end = c + world.canal_axis * ws.CANAL_LEN_MM
    pts = np.vstack([mesh.bounds, canal_end, c - radius, c + radius])
    lo, hi = pts.min(0) - MARGIN_MM, pts.max(0) + MARGIN_MM
    shape = tuple(int(math.ceil(s / dx)) + 1 for s in hi - lo)
    solid = ws.solid_mask(mesh, world, x_head, lo, shape, dx)
    drum = ws.eardrum_cells(world, lo, shape, dx) & ~solid
    rec = ws.to_index(c + world.canal_axis * (ws.CANAL_LEN_MM - 1.5), lo, dx, shape)
    if solid[rec]:                       # coarse grid: step back up the canal until the receiver is in air
        for k in np.arange(ws.CANAL_LEN_MM - 1.5, 0, -dx / 2):
            rec = ws.to_index(c + world.canal_axis * k, lo, dx, shape)
            if not solid[rec]:
                break
    assert not solid[rec], "receiver is inside the wall"

    m = mesh
    if len(mesh.faces) > faces:
        try:
            m = mesh.simplify_quadric_decimation(face_count=faces)
        except ImportError:      # fast_simplification not installed: ship the full mesh
            pass
    data = {
        "source": "hornsim.sim_grid", "ear": "average ear (AudioEar mean)" if "mean_ear" in ear_path else "patient ear",
        "left": left, "shape": list(shape), "dx_mm": dx, "origin_mm": lo.round(3).tolist(),
        "radius_mm": radius, "canal_len_mm": ws.CANAL_LEN_MM, "eardrum_z": ws.EARDRUM_Z,
        "solid_b64": base64.b64encode(np.packbits(solid.ravel())).decode(),
        "eardrum": np.flatnonzero(drum.ravel()).tolist(),
        "receiver": list(map(int, rec)),
        "canal_point_mm": c.round(3).tolist(), "canal_axis": world.canal_axis.round(5).tolist(),
        "canal_diameter_mm": float(world.canal_diameter_mm),
        "front": front.tolist(), "x_head_mm": x_head,
        "mesh": {"verts": m.vertices.round(2).ravel().tolist(), "faces": m.faces.ravel().tolist()},
    }
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    json.dump(data, open(out, "w"))
    print(f"grid {shape} at {dx} mm, {solid.mean() * 100:.0f}% solid, {drum.sum()} eardrum cells, "
          f"receiver {rec}, mesh {len(m.faces)} faces -> {out} ({os.path.getsize(out) / 1e3:.0f} kB)")
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=os.path.join(HERE, "..", "..", "frontend", "public", "sim", "ear_grid.json"))
    ap.add_argument("--ear", help="ear.ply from earrecon; default: the model's average ear")
    ap.add_argument("--left", action="store_true")
    ap.add_argument("--dx", type=float, default=2.5)
    ap.add_argument("--radius", type=float, default=45.0)
    a = ap.parse_args()
    ear = a.ear
    if not ear:
        from earrecon.reconstruct import mean_ear
        import tempfile
        ear = mean_ear(os.path.join(tempfile.mkdtemp(), "mean_ear"))
    export(a.out, ear, a.left, a.dx, a.radius)
