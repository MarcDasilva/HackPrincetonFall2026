"""Ear world: the space inside the concha where a shell and coiled bore can go.

Built from an AudioEar mesh (fixed 2,800-vertex topology), whose landmarks 35-49
outline the concha rim. The rim is fitted with a plane; rays cast inward from that
plane find the bowl floor; the air between rim plane and floor (minus a fit
tolerance, plus an allowed faceplate protrusion) is the shell space.

The canal opening is NOT in the mesh (AudioEar models only the visible pinna), so it
is placed at the deepest point of the bowl and points inward along the rim normal.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import trimesh
from matplotlib.path import Path


@dataclass
class EarWorld:
    voxels: np.ndarray          # bool [nu, nw, nn] shell space
    origin: np.ndarray          # world position of voxel (0,0,0) centre, mm
    axes: np.ndarray            # 3x3 rows: u, w, n (n = outward rim normal)
    voxel_mm: float
    rim_points: np.ndarray      # concha rim landmarks, mm
    rim_center: np.ndarray
    canal_point: np.ndarray     # assumed canal opening, mm
    canal_axis: np.ndarray      # unit vector pointing into the head
    canal_diameter_mm: float
    bowl_volume_cc: float       # air below the rim plane
    shell_volume_cc: float      # usable shell space after tolerance + protrusion
    opening_area_mm2: float
    max_depth_mm: float

    def voxel_centers(self):
        idx = np.argwhere(self.voxels)
        return self.origin + idx @ (self.axes * self.voxel_mm)

    def save(self, path):
        np.savez_compressed(path, **{k: v for k, v in self.__dict__.items()})


def build(mesh_path, landmarks_xlsx, rim_slice=(35, 50), voxel_mm=0.5, tol_mm=0.3,
          protrusion_mm=2.0, canal_diameter_mm=7.5, ear_height_mm=None):
    mesh = trimesh.load(mesh_path, process=False)
    if ear_height_mm:  # the mesh is already in mm; rescale if a different height is given
        h = np.ptp(mesh.vertices[:, 1])
        mesh.vertices *= ear_height_mm / h
    idx = pd.read_excel(landmarks_xlsx)["3dmm"].dropna().astype(int).values
    rim = mesh.vertices[idx[rim_slice[0]:rim_slice[1]]]

    c = rim.mean(0)
    _, _, vt = np.linalg.svd(rim - c)
    n = vt[2] if vt[2][0] > 0 else -vt[2]       # outward = lateral (+x in AudioEar canonical frame)
    u = vt[0]
    w = np.cross(n, u)
    rim2d = np.stack([(rim - c) @ u, (rim - c) @ w], 1)

    g = voxel_mm
    us = np.arange(rim2d[:, 0].min(), rim2d[:, 0].max() + g, g)
    ws = np.arange(rim2d[:, 1].min(), rim2d[:, 1].max() + g, g)
    uu, ww = np.meshgrid(us, ws, indexing="ij")
    inside = Path(rim2d).contains_points(np.stack([uu.ravel(), ww.ravel()], 1)).reshape(uu.shape)

    # floor depth below the rim plane, by ray casting inward
    cells = np.argwhere(inside)
    orig = c + us[cells[:, 0], None] * u + ws[cells[:, 1], None] * w + 0.01 * n
    loc, ray_i, _ = mesh.ray.intersects_location(orig, np.tile(-n, (len(orig), 1)), multiple_hits=False)
    depth = np.full(uu.shape, np.nan)
    depth[cells[ray_i, 0], cells[ray_i, 1]] = np.linalg.norm(loc - orig[ray_i], axis=1)

    ns = np.arange(-np.nanmax(depth), protrusion_mm + g, g)
    vox = np.zeros(uu.shape + (len(ns),), bool)
    d = np.nan_to_num(depth, nan=-1)[..., None]
    vox[:] = (d > 0) & (ns[None, None, :] > -d + tol_mm)

    k = np.nanargmax(depth)
    ki = np.unravel_index(k, depth.shape)
    canal_point = c + us[ki[0]] * u + ws[ki[1]] * w - depth[ki] * n

    return mesh, EarWorld(
        voxels=vox,
        origin=c + us[0] * u + ws[0] * w + ns[0] * n,
        axes=np.stack([u, w, n]),
        voxel_mm=g,
        rim_points=rim,
        rim_center=c,
        canal_point=canal_point,
        canal_axis=-n,
        canal_diameter_mm=canal_diameter_mm,
        bowl_volume_cc=float(np.nansum(depth) * g * g / 1000),
        shell_volume_cc=float(vox.sum() * g ** 3 / 1000),
        opening_area_mm2=float(inside.sum() * g * g),
        max_depth_mm=float(np.nanmax(depth)),
    )


def shell_space_mesh(world: EarWorld):
    """Surface of the shell space, for viewing (marching cubes)."""
    from skimage import measure
    padded = np.pad(world.voxels, 1).astype(float)
    verts, faces, _, _ = measure.marching_cubes(padded, 0.5)
    verts = (verts - 1) * world.voxel_mm
    world_verts = world.origin + verts @ world.axes
    return trimesh.Trimesh(world_verts, faces[:, ::-1], process=True)


SKIN_TAN = (217, 212, 204)   # for meshes with no photo colours (the average ear)


def skin(mesh, smooth_iterations=30):
    """The ear as SHOWN to people: one midpoint subdivision plus Taubin smoothing, photo colours
    carried across, triangle winding made consistent. Display only — the solver keeps the mesh.

    Returns (trimesh, parents): parents[i] are the two original vertices skin vertex i sits between
    (the same index twice for an original vertex), so per-vertex results map onto the skin.
    The reconstructed winding is NOT consistent; without fix_winding, averaged normals cancel and
    the surface shades blotchy (seen in the first renders)."""
    m = mesh.copy()
    trimesh.repair.fix_winding(m)
    e, fe, n = m.edges_unique, m.faces_unique_edges, len(m.vertices)
    mid = n + np.arange(len(e))
    a, b, c = m.faces.T
    ab, bc, ca = mid[fe].T                         # faces_unique_edges order: [0,1], [1,2], [2,0]
    faces = np.vstack([np.c_[a, ab, ca], np.c_[ab, b, bc], np.c_[ca, bc, c], np.c_[ab, bc, ca]])
    rgb = (m.visual.vertex_colors[:, :3].astype(float) if m.visual.kind == "vertex"
           else np.tile(SKIN_TAN, (n, 1)).astype(float))
    parents = np.vstack([np.repeat(np.arange(n)[:, None], 2, 1), e])
    s = trimesh.Trimesh(np.vstack([m.vertices, m.vertices[e].mean(1)]), faces,
                        vertex_colors=np.c_[rgb[parents].mean(1), np.full(len(parents), 255)].astype(np.uint8), process=False)
    trimesh.smoothing.filter_taubin(s, iterations=smooth_iterations)
    return s, parents


# ---------------------------------------------------------------- ear parameters (spec 02)

COIL_GROW = 1.25   # area growth per step when finding the widest throat and mouth the coil takes


def _profile(s, throat_mm2, mouth_mm2, flare_mid1, flare_mid2):
    """Bore radius (mm) at fraction s from throat (0) to mouth (1): earpiece.py's flare, which
    ear_acoustics.bore_radii also uses, so the fit is checked on the SAME bore the gain is computed for."""
    r_t, r_m = np.sqrt(throat_mm2 / np.pi), np.sqrt(mouth_mm2 / np.pi)
    return r_t + (r_m - r_t) * np.interp(s, [0, 1 / 3, 2 / 3, 1], [0, flare_mid1, flare_mid2, 1])


def _fit_setup(world, aid_defaults):
    from .aid import DEFAULT, solid_edt   # aid imports this module; importing at call time breaks the cycle
    D = DEFAULT | (aid_defaults or {})
    tip_r = world.canal_diameter_mm / 2 - D["tip_clearance_mm"]
    # SAME distance map aid.build checks against — aid.clearance indexes it with solid_edt's padding.
    edt = solid_edt(world, tip_r, D["tip_length_mm"])
    top = float((world.origin - world.rim_center) @ world.axes[2] + (world.voxels.shape[2] - 1) * world.voxel_mm)
    return D, edt, top, tip_r


def coil_fits(world, spiral_params, throat_mm2, mouth_mm2, flare_mid1, flare_mid2, canal_stem_mm,
              aid_defaults=None, _setup=None):
    """aid.py's clearance test for one spiral (from ear_params()["coil"]) carrying this bore."""
    from .aid import check, spiral
    D, edt, _, tip_r = _setup or _fit_setup(world, aid_defaults)
    sp = spiral_params
    p = spiral(world, sp["R0_mm"], sp["turns"], sp["top_mm"])
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    # the spiral starts at the mouth, so path fraction 0 is the mouth end of the profile
    r = _profile(1 - s / s[-1], throat_mm2, mouth_mm2, flare_mid1, flare_mid2)
    surf, inter, _ = check(p, r, world, edt, D["min_wall_mm"], tip_r, canal_stem_mm, sp["top_mm"] + 0.5)
    return bool(surf >= -0.1 and inter >= 0)


def ear_params(world, mesh, aid_defaults=None):
    """Numbers every later stage uses (spec 02). `mesh` is unused today; the spec keeps it in the
    interface for landmark-based canal placement (open question below).

    The canal is the ASSUMED one from build(): deepest bowl point, axis along the inward rim normal.
    Spec 02's open question (move it to the anterior concha near landmarks 36-39) is undecided; every
    consumer reads canal_* from HERE, so changing it is a one-place edit.

    Coil: aid.py's spiral grid with aid.py's clearance test, run once. The longest spiral that fits
    aid.py's default bore (1 -> 22.2 mm2, exponential-equivalent flare) is kept; on that SAME spiral the
    throat, then the mouth, grow while it still fits. Smaller bores fit the same spiral, so every
    corner of design_bounds() is buildable on it.
    """
    from .aid import spiral
    from .earpiece import concha_opening
    D, edt, top, tip_r = setup = _fit_setup(world, aid_defaults)
    wall = D["min_wall_mm"]

    # tip cross-section: bore on the axis, vent beside it, wall outside each (aid.py's layout), so
    # throat radius + vent diameter <= vent_room_mm
    vent_room = tip_r - 2 * wall
    k = np.sqrt(D["mouth_mm2"] / D["throat_mm2"])            # radius ratio of aid.py's default horn
    bore = {"throat_mm2": D["throat_mm2"], "mouth_mm2": D["mouth_mm2"], "canal_stem_mm": 0.0,
            "flare_mid1": (k ** (1 / 3) - 1) / (k - 1), "flare_mid2": (k ** (2 / 3) - 1) / (k - 1)}

    r_m = np.sqrt(D["mouth_mm2"] / np.pi)
    spirals = []
    for R0 in np.arange(2.0, 9.01, 0.5):                       # aid.build's grid
        for turns in np.arange(1.0, 4.01, 0.25):
            for n_top in (top - r_m - wall, 0.0, -2.0):
                p = spiral(world, R0, turns, n_top)
                L = float(np.sum(np.linalg.norm(np.diff(p, axis=0), axis=1)))
                if L <= D["max_path_mm"]:
                    spirals.append({"R0_mm": float(R0), "turns": float(turns), "top_mm": float(n_top), "length_mm": L})
    spirals.sort(key=lambda sp: sp["length_mm"])
    fits = lambda sp, **kw: coil_fits(world, sp, _setup=setup, **(bore | kw))
    longest = next((sp for sp in reversed(spirals) if fits(sp)), None)
    if longest is None:
        raise ValueError("no coil fits this concha at aid.py's default areas")

    _, _, room = concha_opening(world, wall)
    faceplate_mouth = float(np.pi * np.mean(room ** 2))
    limits = {"throat_mm2": np.pi * (vent_room - D["vent_diameter_mm"]) ** 2, "mouth_mm2": faceplate_mouth}
    for key in ("throat_mm2", "mouth_mm2"):
        while bore[key] * COIL_GROW <= limits[key] and fits(longest, **{key: bore[key] * COIL_GROW}):
            bore[key] *= COIL_GROW
    shortest = next(sp for sp in spirals if fits(sp))

    return {
        "concha_depth_mm": world.max_depth_mm, "opening_area_mm2": world.opening_area_mm2,
        "bowl_volume_cc": world.bowl_volume_cc, "shell_volume_cc": world.shell_volume_cc,
        "canal_point_mm": world.canal_point.tolist(), "canal_axis": world.canal_axis.tolist(),
        "canal_diameter_mm": world.canal_diameter_mm,
        "max_coil_mm": longest["length_mm"], "max_mouth_mm2": faceplate_mouth, "vent_room_mm": vent_room,
        "x_head_mm": float(world.canal_point[0]),          # head plane flush with the canal opening (spec 03)
        "coil": {"longest": longest, "shortest": shortest, **bore},
    }


def design_bounds(ear_params):
    """(lo, hi) for every design variable ear_acoustics.insertion_gain takes. Every corner fits the coil
    found by ear_params() (test_acoustics checks it). The vent is aid.py's default: the throat and the
    vent share the tip, so a wider vent narrows the throat bound (vent_room_mm)."""
    from .aid import DEFAULT
    from .earpiece import PARAMS
    c = ear_params["coil"]
    vent = DEFAULT["vent_diameter_mm"]
    vent_path = ear_params["concha_depth_mm"] + DEFAULT["tip_length_mm"]   # faceplate to tip, straight
    return {
        "throat_mm2": (DEFAULT["throat_mm2"], c["throat_mm2"]),
        "mouth_mm2": (DEFAULT["mouth_mm2"], c["mouth_mm2"]),
        "length_mm": (c["shortest"]["length_mm"], c["longest"]["length_mm"]),
        "flare_mid1": (0.0, c["flare_mid1"]),
        "flare_mid2": (c["flare_mid1"], c["flare_mid2"]),
        "canal_stem_mm": PARAMS["canal_stem_mm"][:2],
        "vent_count": (0, 1),
        "vent_diameter_mm": (vent, vent),
        "vent_length_mm": (vent_path, vent_path),
    }
