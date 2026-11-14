"""In-concha horn earpiece: a seat cast from the patient's concha with the horn carved INSIDE it.

The bore flares from the canal opening up to a mouth on the faceplate whose outline follows this
patient's concha opening, so the piece sits in the ear like an in-the-ear aid. Beyond the
faceplate the designer may sculpt a COLLECTOR: a swept shape growing out of the mouth (a cone, a
trumpet, a scoop toward the talker, an asymmetric bell), described by a spine and a cross-section
outline at each spine point. Without one the faceplate stays flush, with an optional low hood. A
small removal tab helps take it out. A soft stem down the canal holds it in; `fit_offset_mm` grows or shrinks the
whole cast so a patient can try S/M/L, since nobody yet knows how far a photo-built ear is off.

Print it in a flexible resin or cast it in silicone from a printed mould: a rigid cast has no
undercut to grip and falls out.

    python -m hornsim.earpiece <patient_dir> '<params json>' [design_id]
    python -m hornsim.earpiece --describe          the dials, their bounds and defaults

Prints ONE JSON report on stdout (logs go to stderr) and writes <patient_dir>/aid/<design_id>/:
    earpiece.glb  earpiece_in_ear.glb  earpiece_print.stl  design.json  preview.png

`collector` (optional) = {"spine": [[out, up, front], ...], "sections": [[12 radii], ...]}, mm,
relative to the mouth centre: `out` is away from the head along the faceplate normal, `front`
toward the face. Each section gives the INNER radius at 12 angles starting at front and turning
toward up (front, 30, 60, up, ..., back, ..., down, ...). The mouth itself is section 0.

A design that cannot be built returns {"ok": false, "reasons": [...]}. Each reason names the
failed check and which dial to move, so the design search or the agent can act on it (spec 09).

Frame: AudioEar canonical, mm. +x lateral, +y up, forward is -z for a right ear and +z for a
left ear (earrecon mirrors z). Talker azimuth 0 = front, 90 = straight out, 180 = behind.
"""
import json
import math
import os
import re
import sys
from dataclasses import replace

import numpy as np
import trimesh
from scipy import ndimage

from . import ear_world as ew
from .aid import frames, tube

PARAMS = {  # name: (min, max, default, meaning)
    "throat_mm2": (7.0, 60.0, 27.0, "bore area at the canal; with a stem it must fit inside the stem"),
    "mouth_mm2": (20.0, 1500.0, 150.0, "mouth area on the faceplate; capped by this concha's opening"),
    "aim_yaw_deg": (0.0, 180.0, 30.0, "where the talker is: 0 front, 90 straight out, 180 behind"),
    "aim_pitch_deg": (-45.0, 45.0, 0.0, "talker elevation, positive up"),
    "hood_mm": (0.0, 5.0, 0.0, "hood height on the side away from the talker; 0 = flush faceplate"),
    "rim_conformity": (0.0, 1.0, 1.0, "mouth outline: 0 plain ellipse, 1 follows this concha's opening"),
    "mouth_stretch": (0.5, 2.0, 1.0, "mouth height : width before it is fitted to the opening"),
    "flare_mid1": (0.0, 1.0, 0.15, "share of the widening done one third of the way up the bore"),
    "flare_mid2": (0.0, 1.0, 0.45, "share of the widening done two thirds of the way up the bore"),
    "wall_mm": (0.8, 3.0, 1.2, "minimum shell wall around the bore"),
    "canal_stem_mm": (0.0, 8.0, 5.0, "soft stem into the canal that holds the piece in; 0 = none. Its "
                      "outside is the assumed canal width, so it caps the throat"),
    "tab_mm": (0.0, 6.0, 4.0, "removal tab length; 0 = none"),
    "tab_side_deg": (-180.0, 180.0, -90.0, "where the tab sits on the faceplate edge: 0 front, 90 up, -90 down, 180 back"),
    "fit_offset_mm": (-1.0, 1.0, 0.0, "grow (+) or shrink (-) the whole cast, in voxel steps; sizes are -0.5 / 0 / +0.5"),
}
STEM_WALL_MM = 0.8   # thinnest soft wall that still holds its shape
NECK_MARGIN_MM = 1.0  # extra room where the bore starts: it bends toward the mouth from there, and a
                      # start that only just fits breaks out of the bowl wall on the way up
CLEAR_MM = 1.0       # gap kept between anything above the faceplate and skin
MAX_REACH_MM = 35.0  # furthest a collector may reach from the mouth centre
GRID = np.linspace(-np.pi, np.pi, 256, endpoint=False)
SEG = 64             # samples around each cross-section
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
Y = np.array([0.0, 1.0, 0.0])


def validate(params):
    """Full parameter set from defaults + `params`, and every problem at once."""
    issues, p = [], {k: v[2] for k, v in PARAMS.items()}
    params = dict(params)
    p["collector"], col_issues = validate_collector(params.pop("collector", None))
    issues += col_issues
    for k, v in params.items():
        if k not in PARAMS:
            issues.append(f"unknown parameter '{k}'")
            continue
        lo, hi = PARAMS[k][:2]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or not lo <= v <= hi:
            issues.append(f"{k}={v!r} is outside {lo}..{hi}")
            continue
        p[k] = float(v)
    if not issues and p["mouth_mm2"] <= p["throat_mm2"]:
        issues.append("mouth_mm2 must exceed throat_mm2")
    if not issues and p["flare_mid1"] > p["flare_mid2"]:
        issues.append("flare_mid1 must not exceed flare_mid2 (the bore never narrows)")
    if not issues and p["collector"] and p["hood_mm"] > 0:
        issues.append("use a collector or a hood, not both: a collector can shape its own hood")
    return p, issues


def _num(v, lo, hi):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


def validate_collector(col):
    """The collector as clean float lists, and every problem at once. None means no collector."""
    if col is None:
        return None, []
    if not isinstance(col, dict) or set(col) != {"spine", "sections"}:
        return None, ["collector must be {'spine': [...], 'sections': [...]}"]
    spine, sections = col["spine"], col["sections"]
    issues = []
    if not isinstance(spine, list) or not 1 <= len(spine) <= 8:
        issues.append("collector.spine needs 1 to 8 points")
    elif not all(isinstance(q, list) and len(q) == 3 and all(_num(x, -40, 40) for x in q) for q in spine):
        issues.append("each spine point is [out, up, front] in mm, each within -40..40")
    elif any(q[0] < 0 for q in spine):
        issues.append("spine points must not go back toward the head (out >= 0)")
    if not isinstance(sections, list) or not isinstance(spine, list) or len(sections) != len(spine):
        issues.append("collector.sections needs one section per spine point")
    elif not all(isinstance(r, list) and len(r) == 12 and all(_num(x, 1, 30) for x in r) for r in sections):
        issues.append("each section is 12 inner radii in mm, each within 1..30")
    if issues:
        return None, issues
    return {"spine": [[float(x) for x in q] for q in spine], "sections": [[float(x) for x in r] for r in sections]}, []


def section_on_grid(radii12, left):
    """12 radii (front, turning toward up) -> a smooth radius per GRID angle psi. psi runs from
    `side`, which is front on a right ear and back on a left one, hence the mirror."""
    theta = np.linspace(0, 2 * np.pi, 256, endpoint=False)
    r = np.clip(np.fft.irfft(np.fft.rfft(radii12), 256) * 256 / 12, 0.8, None)   # trig interpolation
    psi = np.pi - theta if left else theta
    return _periodic((psi + np.pi) % (2 * np.pi) - np.pi, r, GRID)


def ring_radii(t, nvec, bvec, S):
    """Radius at each sweep angle of one ring whose frame is (t, nvec, bvec), from a GRID profile S."""
    upv = Y - (Y @ t) * t
    if np.linalg.norm(upv) < 0.2:          # sweeping straight up or down: no "up" in this plane
        upv = np.array([0.0, 0, 1.0]) - t[2] * t
    upv /= np.linalg.norm(upv)
    sidev = np.cross(upv, t)
    ang = np.linspace(0, 2 * np.pi, SEG, endpoint=False)
    d = np.cos(ang)[:, None] * nvec + np.sin(ang)[:, None] * bvec
    return _periodic(GRID, S, np.arctan2(d @ upv, d @ sidev))


def collector_path(M, n, up, front, spine):
    """Spine points -> a smooth centreline that leaves the mouth along the faceplate normal, plus the
    arc position of each spine point on it. Corners are rounded so the sweep never folds on itself."""
    pts = np.array([M - 1.0 * n, M - 0.5 * n, M] + [M + a * n + b * up + c * front for a, b, c in spine])
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    fine = np.stack([np.interp(np.arange(0, arc[-1], 0.25), arc, pts[:, k]) for k in range(3)], 1)
    fine = ndimage.uniform_filter1d(fine, 13, axis=0, mode="nearest")
    fine = fine[np.r_[0, np.cumsum(np.linalg.norm(np.diff(fine, axis=0), axis=1))] >= 2.0]   # from 1 mm past M
    path = np.vstack([M, M + 0.5 * n, fine])
    farc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    keep = np.r_[0, np.nonzero(np.diff(np.floor(farc / 0.5)))[0] + 1]                     # ~0.5 mm steps
    path, farc = path[keep], farc[keep]
    stations = [0.0] + [float(farc[np.argmin(np.linalg.norm(path - q, axis=1))]) for q in pts[3:]]
    return path, farc, stations


def inside_sweep(q, path, R, fr, lo, hi):
    """True where points lie inside the tube swept along path[lo:hi] with [station, angle] radii R:
    at the nearest station, within that ring's radius in the point's own direction."""
    from scipy.spatial import cKDTree
    t, nvec, bvec = (f[lo:hi] for f in fr)
    j = cKDTree(path[lo:hi]).query(q)[1]
    v = q - path[lo:hi][j]
    along = np.einsum("ij,ij->i", v, t[j])
    radial = v - along[:, None] * t[j]
    ang = np.arctan2(np.einsum("ij,ij->i", radial, bvec[j]), np.einsum("ij,ij->i", radial, nvec[j])) % (2 * np.pi)
    k = np.round(ang / (2 * np.pi) * SEG).astype(int) % SEG
    past_end = ((j == 0) & (along < 0)) | ((j == hi - lo - 1) & (along > 0))
    return (np.linalg.norm(radial, axis=1) < R[lo:hi][j, k]) & ~past_end


def render_preview(ear, solid, c, n, up, left, png):
    """Two views for the designer to judge the look: face-on in the ear, and three-quarter."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    side = np.cross(up, n) * (-1 if left else 1)            # front on screen-left for both ears
    B = np.stack([side, up, n])
    light = np.array([0.3, 0.5, 0.8]) / np.linalg.norm([0.3, 0.5, 0.8])
    fig = plt.figure(figsize=(7, 3.6))
    for k, (el, az) in enumerate([(90, -90), (20, -50)]):
        ax = fig.add_subplot(1, 2, k + 1, projection="3d")
        for mesh, rgb, alpha in ((ear, (0.93, 0.8, 0.72), 0.3), (solid, (0.95, 0.55, 0.15), 1.0)):
            v = (mesh.vertices - c) @ B.T
            fn = trimesh.Trimesh(v, mesh.faces, process=False).face_normals * (-1 if left else 1)
            sh = (0.6 + 0.4 * np.abs(fn @ light)) if alpha < 1 else (0.25 + 0.75 * np.clip(fn @ light, 0, 1))
            ax.add_collection3d(Poly3DCollection(v[mesh.faces], edgecolor="none",
                                                 facecolors=np.c_[np.outer(sh, rgb), np.full(len(sh), alpha)]))
        r = 30
        ax.set_xlim(-r, r); ax.set_ylim(-r, r); ax.set_zlim(-r, r)
        ax.view_init(elev=el, azim=az); ax.set_axis_off()
        ax.set_title(["face-on, in the ear", "three-quarter"][k], fontsize=9)
    plt.tight_layout()
    plt.savefig(png, dpi=80)
    plt.close(fig)


def _periodic(psi, r, at):
    o = np.argsort(psi)
    return np.interp(at, psi[o], r[o], period=2 * np.pi)


def plane_basis(normal):
    """(side, up) in the plane with this normal; psi runs from side toward up. SAME convention
    for the opening and the mouth sections, so the outline maps onto the bore unmirrored."""
    up = Y - (Y @ normal) * normal
    up /= np.linalg.norm(up)
    return np.cross(up, normal), up


def concha_opening(world, wall, ear=None, prot=0.0):
    """Centre of the concha opening (rim plane) and the room for a mouth in each direction psi.

    The rim landmarks outline more than the open bowl: folds of the ear (tragus, antihelix, crus)
    overhang it. With `ear` given, cells that have ear ABOVE the faceplate are closed, so the mouth
    and anything grown out of it only open where there is sky. Returns None when nothing is open."""
    c, (u, w, n), g = world.rim_center, world.axes, world.voxel_mm
    k0 = int(round(-((world.origin - c) @ n) / g))
    mask = world.voxels[:, :, min(max(k0, 0), world.voxels.shape[2] - 1)].copy()
    o2 = np.array([(world.origin - c) @ u, (world.origin - c) @ w])
    if ear is not None:
        pts = trimesh.remesh.subdivide(ear.vertices, ear.faces)[0]
        h = (pts - c) @ n
        pts = pts[(h > prot) & (h < prot + 40)]
        ij = np.round((np.c_[(pts - c) @ u, (pts - c) @ w] - o2) / g).astype(int)
        ok = np.all((ij >= 0) & (ij < mask.shape), axis=1)
        shade = np.zeros_like(mask)
        shade[ij[ok, 0], ij[ok, 1]] = True
        # 1.5 mm: subdivided ear vertices are ~1 mm apart, so close the gaps between their shadows
        mask &= ~ndimage.binary_dilation(shade, iterations=3)
        mask = ndimage.binary_opening(mask, iterations=2)       # no slivers between folds
        if not mask.any():
            return None
        lab, nlab = ndimage.label(mask)                         # keep the biggest open patch
        mask = lab == 1 + int(np.argmax(ndimage.sum(mask, lab, range(1, nlab + 1))))
    cells = np.argwhere(mask)
    centre2 = o2 + cells.mean(0) * g
    side, up = plane_basis(n)
    grid = np.linspace(-np.pi, np.pi, 256, endpoint=False)
    steps = np.arange(0, 40, g / 2)
    room = np.empty(len(grid))
    for i, a in enumerate(grid):
        d3 = math.cos(a) * side + math.sin(a) * up
        q = centre2[None] + steps[:, None] * np.array([d3 @ u, d3 @ w])[None]
        idx = np.round((q - o2) / g).astype(int)
        ok = np.all((idx >= 0) & (idx < mask.shape), axis=1)
        inside = np.zeros(len(q), bool)
        inside[ok] = mask[idx[ok, 0], idx[ok, 1]]
        room[i] = steps[np.argmin(inside)] if not inside.all() else steps[-1]
    return c + centre2[0] * u + centre2[1] * w, grid, np.clip(room - wall, 0, None)


def mouth_outline(p, grid, room):
    """Mouth radius per psi: ellipse blended with the opening's shape, scaled to the area, then
    clipped to the room. Returns radii and the largest area this opening allows."""
    k = math.sqrt(p["mouth_stretch"])
    x, y = np.cos(grid) / k, np.sin(grid) * k                     # area-preserving stretch
    ellipse = _periodic(np.arctan2(y, x), np.hypot(x, y), grid)
    s = (1 - p["rim_conformity"]) * ellipse / ellipse.mean() + p["rim_conformity"] * room / room.mean()
    r = np.minimum(s * math.sqrt(p["mouth_mm2"] / (math.pi * np.mean(s ** 2))), room)
    return r, float(math.pi * np.mean(room ** 2))


def capsules(points, r):
    """Cylinders through `points` with a ball at every joint: a bent tube with no self-overlap,
    which a ring sweep round a sharp bend would produce and the boolean engine would reject."""
    parts = [trimesh.creation.icosphere(subdivisions=2, radius=r).apply_translation(q) for q in points]
    parts += [trimesh.creation.cylinder(radius=r, segment=[a, b], sections=48) for a, b in zip(points[:-1], points[1:])]
    return trimesh.boolean.union(parts, engine="manifold")


def profile_stations(along):
    """Stations reported in area_profile_mm2: the throat, the first station past each whole
    millimetre, and ALWAYS the outer end. Without the end the profile stopped up to 1 mm short of the
    mouth (a 304 mm2 mouth was reported as 252), and the acoustic model scored a smaller horn."""
    return np.unique(np.r_[0, np.nonzero(np.diff(np.floor(along)))[0] + 1, len(along) - 1])


def _reason(check, message, dial=None, direction=None, **values):
    r = {"check": check, "message": message, **values}
    if dial:
        r["move"] = {"dial": dial, "direction": direction}
    return r


def build(context_dir, out_dir, params, design_id="e1", log=print):
    """Build one in-concha earpiece. Returns the report dict (ok, or reasons)."""
    if not ID_RE.match(design_id):
        raise ValueError("design_id must be 1-64 letters, digits, - or _")
    p, issues = validate(params)
    report = {"design_id": design_id, "family": "concha_horn_earpiece", "params": p}
    if issues:
        return {**report, "ok": False, "reasons": [_reason("params", m) for m in issues]}

    cfg = json.load(open(os.path.join(context_dir, "context.json")))["config"]
    P, E = cfg["patient"], cfg["ear_world"]
    mesh, world = ew.build(P["ear_mesh"], E["landmarks_xlsx"], tuple(E["concha_rim_landmarks"]), E["voxel_mm"],
                           E["fit_tolerance_mm"], E["faceplate_protrusion_mm"], E["canal_opening_diameter_mm"],
                           P["ear_height_mm"])
    # S/M/L: grow or shrink the whole cast in voxel steps; pad first so a grown cast is not
    # clipped flat at the edge of the voxel box
    k_fit = int(round(p["fit_offset_mm"] / world.voxel_mm))
    if k_fit:
        v = np.pad(world.voxels, abs(k_fit))
        v = ndimage.binary_dilation(v, iterations=k_fit) if k_fit > 0 else ndimage.binary_erosion(v, iterations=-k_fit)
        world = replace(world, voxels=v, origin=world.origin - abs(k_fit) * world.voxel_mm * world.axes.sum(0))
    fit_offset = k_fit * world.voxel_mm
    prot, n, c, wall = E["faceplate_protrusion_mm"], world.axes[2], world.rim_center, p["wall_mm"]
    side, up = plane_basis(n)
    left = P.get("side", "right") == "left"
    front = -side if left else side          # side = up x n faces front on a right ear, back on a left one
    reasons, warnings = [], []

    opening = concha_opening(world, wall, mesh, prot)
    if opening is None:
        return {**report, "ok": False, "reasons": [_reason(
            "no_opening", "the ear's folds cover the whole concha opening; there is nowhere for a mouth")]}
    centre, grid, room = opening
    r_grid, mouth_max = mouth_outline(p, grid, room)
    mouth_area = float(math.pi * np.mean(r_grid ** 2))
    if mouth_area < 0.95 * p["mouth_mm2"]:
        reasons.append(_reason("mouth_fit", "the mouth is larger than this concha's opening allows",
                               "mouth_mm2", "-", max_ok_mm2=round(0.95 * mouth_max, 1),
                               alternatives=["rim_conformity +"]))

    # The bowl narrows into a neck above the canal with no room for the bore plus a wall, so the
    # seat stops at the lowest layer that has that room; the open neck below joins the canal and
    # belongs to the acoustic model's residual cavity, not to the print.
    r_t = math.sqrt(p["throat_mm2"] / math.pi)
    g = world.voxel_mm
    edt2 = ndimage.distance_transform_edt(np.pad(world.voxels, 1), sampling=(g, g, 1e6))[1:-1, 1:-1, 1:-1]
    fits = np.nonzero(edt2.max(axis=(0, 1)) >= r_t + wall + NECK_MARGIN_MM)[0]
    if not len(fits):
        return {**report, "ok": False, "reasons": [_reason(
            "throat_fit", "no layer of this concha has room for the throat plus its wall", "throat_mm2", "-")]}
    k_neck = int(fits[0])
    h_neck = float((world.origin - c) @ n + k_neck * g)
    i, j = np.unravel_index(np.argmax(edt2[:, :, k_neck]), edt2.shape[:2])
    P0 = world.origin + np.array([i, j, k_neck]) @ (world.axes * g)

    # the stem's outside is the assumed canal width, so it caps the throat. Sizes do NOT scale it:
    # the throat is an acoustic number, and the soft stem absorbs the canal's own uncertainty
    stem, canal_r = p["canal_stem_mm"], E["canal_opening_diameter_mm"] / 2
    if stem > 0 and r_t + STEM_WALL_MM > canal_r:
        reasons.append(_reason("stem_throat", "the throat does not fit inside the canal stem", "throat_mm2", "-",
                               max_ok_mm2=round(math.pi * (canal_r - STEM_WALL_MM) ** 2, 1),
                               alternatives=["canal_stem_mm 0 (no stem: the piece then relies on its fit alone)"]))

    # bore centreline: from the widest point of the neck, an S-bend that arrives square to the
    # faceplate at the mouth centre; past the faceplate it continues straight up through the hood
    M = centre + prot * n
    a = (prot - h_neck) / 3
    u = np.linspace(0, 1, 61)[1:, None]
    bez = ((1 - u) ** 3) * P0 + 3 * (1 - u) ** 2 * u * (P0 + a * n) + 3 * (1 - u) * u ** 2 * (M - a * n) + u ** 3 * M
    # with a stem the bore continues down the stem instead, so the straight drop must not cut its wall
    below = P0 + np.arange(-0.5 if stem > 0 else -2.0, 0, 0.5)[:, None] * n
    col = p["collector"]
    if col:
        cpath, carc, stations = collector_path(M, n, up, front, col["spine"])
        end_dir = (cpath[-1] - cpath[-2]) / np.linalg.norm(cpath[-1] - cpath[-2])
        above = np.vstack([cpath[1:], cpath[-1] + np.array([0.5, 1.0, 1.5])[:, None] * end_dir])  # open the end
    else:
        above = M + np.arange(0.5, p["hood_mm"] + 2.01, 0.5)[:, None] * n
    path = np.vstack([below, P0, bez, above])
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    i0, i_m = len(below), len(below) + len(bez)
    i_end = i_m + (len(cpath) - 1 if col else 0)          # last station that has an outer wall
    bore_len = arc[i_m] - arc[i0]
    s = (arc - arc[i0]) / bore_len

    t, nn, bb = frames(path)
    fr = lambda j0, j1: (t[j0:j1], nn[j0:j1], bb[j0:j1])   # noqa: E731  sub-tubes must share these frames
    ang = np.linspace(0, 2 * np.pi, SEG, endpoint=False)
    d = np.cos(ang)[:, None] * nn[i_m] + np.sin(ang)[:, None] * bb[i_m]
    r_m = _periodic(grid, r_grid, np.arctan2(d @ up, d @ side))
    gs = np.interp(s, [0, 1 / 3, 2 / 3, 1], [0, p["flare_mid1"], p["flare_mid2"], 1])
    R = r_t + (r_m[None, :] - r_t) * gs[:, None]
    if col:
        # sections blend linearly between stations; the mouth outline is station 0
        S = np.array([r_grid] + [section_on_grid(r, left) for r in col["sections"]])
        st = np.maximum.accumulate(np.array(stations)) + np.arange(len(stations)) * 1e-6
        for q in range(1, len(path) - i_m):
            a_ = carc[min(q, len(carc) - 1)]
            k = int(np.clip(np.searchsorted(st, a_, side="right") - 1, 0, len(st) - 2))
            w = float(np.clip((a_ - st[k]) / (st[k + 1] - st[k]), 0, 1))
            R[i_m + q] = ring_radii(t[i_m + q], nn[i_m + q], bb[i_m + q], (1 - w) * S[k] + w * S[k + 1])
        if np.pi * np.mean(R[i_m:i_end + 1] ** 2, axis=1).min() < p["throat_mm2"]:
            warnings.append(_reason("collector_choke", "the collector narrows below the throat area somewhere"))

    # the bore must keep `wall` of seat between it and the skin all the way up; the first few
    # percent sit at the cut floor, where the bore is MEANT to open
    ring = np.cos(ang)[None, :, None] * nn[:, None, :] + np.sin(ang)[None, :, None] * bb[:, None, :]
    surf = path[:, None, :] + R[:, :, None] * ring
    check = (s > 0.05) & (s < 1)
    pts = surf[check].reshape(-1, 3)
    edt = ndimage.distance_transform_edt(world.voxels) * world.voxel_mm
    idx = np.round((pts - world.origin) @ world.axes.T / world.voxel_mm).astype(int)
    ok = np.all((idx >= 0) & (idx < world.voxels.shape), axis=1)
    room3 = np.zeros(len(pts))
    room3[ok] = edt[tuple(idx[ok].T)]
    room3[(pts - c) @ n > prot - world.voxel_mm] = 99.0          # at the faceplate the mouth check rules
    bore_wall = float(room3.min())
    if bore_wall < wall - world.voxel_mm:
        depth = float(prot - (pts[np.argmin(room3)] - c) @ n)
        reasons.append(_reason("bore_wall", f"the bore breaks out of the seat {depth:.1f} mm below the faceplate",
                               "flare_mid2", "-", value_mm=round(bore_wall, 2), limit_mm=wall,
                               alternatives=["flare_mid1 -", "mouth_mm2 -", "throat_mm2 -"]))

    inner = tube(path, R)
    hood = None
    if p["hood_mm"] > 0:
        j0, j1 = i_m - 2, len(path)
        wall_tube = tube(path[j0:j1], R[j0:j1] + wall, fr=fr(j0, j1))
        fwd = np.array([0.0, 0.0, -1.0 if P.get("side", "right") == "right" else 1.0])
        az, el = math.radians(p["aim_yaw_deg"]), math.radians(p["aim_pitch_deg"])
        aim = math.cos(el) * (math.sin(az) * np.array([1.0, 0, 0]) + math.cos(az) * fwd) + math.sin(el) * Y
        ap = aim - (aim @ n) * n
        # hood height falls from hood_mm on the side away from the talker to 0 on the talker's side;
        # a talker straight out (no in-plane direction) gets an even, half-height collar
        h = p["hood_mm"]
        tilt = (h / 2) / r_grid.max() * ap / np.linalg.norm(ap) if np.linalg.norm(ap) > 0.3 else 0 * n
        N = -(n + tilt)
        N /= np.linalg.norm(N)
        T = trimesh.geometry.align_vectors([0, 0, 1.0], N)
        T[:3, 3] = M + (h / 2) * n + 100 * N
        hood = trimesh.boolean.intersection([wall_tube, trimesh.creation.box([200, 200, 200], transform=T)],
                                            engine="manifold")

    tab = None
    if p["tab_mm"] > 0:
        # psi runs from `side`, which faces front on a right ear and back on a left one
        deg = p["tab_side_deg"] if P.get("side", "right") == "right" else 180 - p["tab_side_deg"]
        psi = (math.radians(deg) + math.pi) % (2 * math.pi) - math.pi
        edge = math.cos(psi) * side + math.sin(psi) * up
        base = M + (float(_periodic(grid, room, np.array([psi]))[0]) + wall / 2) * edge   # mid faceplate rim
        lean = (n + 0.8 * edge) / np.linalg.norm(n + 0.8 * edge)
        tab = capsules([base - 1.0 * n, base + p["tab_mm"] * lean], 0.8)

    collector = None
    if col:
        collector = tube(path[i_m - 2:i_end + 1], R[i_m - 2:i_end + 1] + wall, fr=fr(i_m - 2, i_end + 1))
        head = float(collector.vertices[:, 0].min() - mesh.vertices[:, 0].min())
        if head < CLEAR_MM:   # ponytail: the head is the plane through the pinna's most medial point
            reasons.append(_reason("collector_head", "the collector runs into the side of the head", "collector",
                                   "turn the spine outward, away from the head", value_mm=round(head, 2)))
        reach = float(np.linalg.norm(collector.vertices - M, axis=1).max())
        if reach > MAX_REACH_MM:
            reasons.append(_reason("collector_reach", "the collector reaches too far from the ear", "collector",
                                   "shorten the spine or shrink the sections", value_mm=round(reach, 1),
                                   limit_mm=MAX_REACH_MM))

    # parts above the faceplate must clear the skin; below it the seat is the cast of the skin. The
    # collector's base sits ON the faceplate edge, so its first 2 mm get the seat's fit tolerance.
    proud = {"hood": (hood, "hood_mm", "-", ["aim_yaw_deg (moves which side the hood is on)"], False),
             "tab": (tab, "tab_side_deg", "move", ["tab_mm -"], False),
             "collector": (collector, "collector", None, [], True)}
    proud = {k: v for k, v in proud.items() if v[0] is not None}
    if proud:
        ear_pts = trimesh.remesh.subdivide(mesh.vertices, mesh.faces)[0]
        height = (ear_pts - c) @ n
        ear_pts, height = ear_pts[height > prot + 0.5], height[height > prot + 0.5]
        for name, (part, dial, way, alt, base_zone) in proud.items():
            if not len(ear_pts):
                break
            if name == "collector":
                # trimesh decides inside/outside by ray casting, which misfires on this sweep (it
                # flagged skin 30 mm from the axis as 19 mm inside); the sweep itself knows exactly
                _, dist, _ = trimesh.proximity.closest_point(part, ear_pts)
                clear = np.where(inside_sweep(ear_pts, path, R + wall, (t, nn, bb), i_m - 2, i_end + 1), -dist, dist)
            else:
                clear = -trimesh.proximity.signed_distance(part, ear_pts)
            limit = np.where(height < prot + 2.0, E["fit_tolerance_mm"], CLEAR_MM) if base_zone else CLEAR_MM
            if np.any(clear < limit):
                where = ""
                if name == "collector":   # tell the designer which side to pull away from
                    q = ear_pts[np.argmin(clear - limit)]
                    v = q - path[i_m + np.argmin(np.linalg.norm(path[i_m:i_end + 1] - q, axis=1))]
                    fv, uv = v @ front, v @ up
                    where = (("front" if fv > 0 else "back") if abs(fv) >= abs(uv) else ("upper" if uv > 0 else "lower"))
                    way = f"pull the spine or shrink the sections away from the {where} side"
                    where = f" on its {where} side"
                reasons.append(_reason(f"{name}_clearance", f"the {name} touches the ear{where}", dial, way,
                                       value_mm=round(float(clear.min()), 2), limit_mm=CLEAR_MM, alternatives=alt))
    if reasons:
        return {**report, "ok": False, "reasons": reasons, "warnings": warnings}

    seat = ew.shell_space_mesh(world)
    trimesh.smoothing.filter_taubin(seat, iterations=25)
    T = trimesh.geometry.align_vectors([0, 0, 1.0], n)
    T[:3, 3] = c + h_neck * n + 100 * n
    seat = trimesh.boolean.intersection([seat, trimesh.creation.box([200, 200, 200], transform=T)], engine="manifold")
    cut = [inner]
    extra = [part for part in (hood, tab, collector) if part is not None]
    if stem > 0:
        # stem: from the seat floor through the open neck to the assumed canal opening, then stem_mm
        # down the canal; the bore runs through it and past its tip so the end is open
        axis = world.canal_axis
        extra.append(capsules([P0 + 1.0 * n, world.canal_point, world.canal_point + stem * axis], canal_r))
        cut.append(capsules([P0, world.canal_point, world.canal_point + (stem + 1.5) * axis], r_t))
    body = trimesh.boolean.union([seat, *extra], engine="manifold") if extra else seat
    solid = trimesh.boolean.difference([body, *cut], engine="manifold")
    if not solid.is_watertight:
        return {**report, "ok": False, "reasons": [_reason("watertight", "the print solid is not watertight")]}

    out = os.path.join(out_dir, design_id)
    os.makedirs(out, exist_ok=True)
    solid.export(os.path.join(out, "earpiece_print.stl"))
    view = solid.copy()
    view.visual.face_colors = [243, 140, 40, 255]
    scene = trimesh.Scene()
    scene.add_geometry(view, node_name="earpiece", geom_name="earpiece")
    scene.export(os.path.join(out, "earpiece.glb"))
    ear = mesh.copy()
    ear.visual = trimesh.visual.ColorVisuals(ear, vertex_colors=np.tile([214, 160, 140, 110], (len(ear.vertices), 1)))
    scene.add_geometry(ear, node_name="ear", geom_name="ear")
    scene.export(os.path.join(out, "earpiece_in_ear.glb"))
    render_preview(mesh, solid, c, n, up, left, os.path.join(out, "preview.png"))
    # area along the bore from the throat, ~1 mm apart: what the acoustic model (spec 07) consumes
    along = arc[i0:i_end + 1] - arc[i0]
    pick = profile_stations(along)
    area = np.pi * np.mean(R[i0:i_end + 1] ** 2, axis=1)

    k = slice(None, None, 8)
    report.update({
        "ok": True,
        "warnings": warnings,
        "checks": {"bore_wall_mm": round(bore_wall, 2), "watertight": True},
        "seat_floor_mm": round(h_neck + world.max_depth_mm, 1),   # open neck left below the seat
        "geometry": {
            "mouth_mm2": round(mouth_area, 1), "mouth_mm2_max": round(mouth_max, 1),
            "mouth_width_mm": round(float(np.ptp(r_grid * np.cos(grid))), 1),
            "mouth_height_mm": round(float(np.ptp(r_grid * np.sin(grid))), 1),
            "throat_mm2": p["throat_mm2"], "bore_length_mm": round(float(bore_len), 1),
            "canal_stem_mm": stem, "canal_stem_od_mm": round(2 * canal_r, 2) if stem > 0 else None,
            "fit_offset_mm": fit_offset, "tab_mm": p["tab_mm"],
            "proud_of_concha_mm": round(float(((solid.vertices - c) @ n).max()), 1),
            "collector": bool(col), "reach_mm": round(reach, 1) if col else 0.0,
            "collector_mouth_mm2": round(float(area[-1]), 1),
            "print_volume_cc": round(solid.volume / 1000, 2),
        },
        # (side, up) mm in the faceplate plane; for the frontend and the agent
        "mouth_outline_mm": [[round(float(r * math.cos(q)), 2), round(float(r * math.sin(q)), 2)]
                             for q, r in zip(grid[k], r_grid[k])],
        "area_profile_mm2": [[round(float(along[i]), 1), round(float(area[i]), 1)] for i in pick],
        "acoustics": None,
        "files": {f: os.path.join(out, f) for f in ("earpiece.glb", "earpiece_in_ear.glb", "earpiece_print.stl",
                                                     "preview.png")},
        "notes": ["Print in a flexible resin or cast in silicone from a printed mould; rigid resin will not stay in.",
                  "The canal stem is sized to the ASSUMED canal and not checked against it; the canal is not in the mesh.",
                  "acoustics is filled by the L1 model (spec 07); nothing here predicts gain.",
                  "The canal opening position and size are assumed; a photo cannot see them.",
                  "Resin biocompatibility holds only for a validated printer, settings, wash and cure."],
    })
    json.dump(report, open(os.path.join(out, "design.json"), "w"), indent=1)
    g = report["geometry"]
    log(f"earpiece {design_id}: mouth {g['mouth_width_mm']}x{g['mouth_height_mm']} mm, "
        f"bore {g['bore_length_mm']} mm, proud {g['proud_of_concha_mm']} mm")
    return report


if __name__ == "__main__":
    if sys.argv[1:] == ["--describe"]:
        print(json.dumps({k: {"min": v[0], "max": v[1], "default": v[2], "meaning": v[3]} for k, v in PARAMS.items()}))
        sys.exit(0)
    pdir = sys.argv[1]
    result = build(os.path.join(pdir, "context"), os.path.join(pdir, "aid"), json.loads(sys.argv[2]),
                   sys.argv[3] if len(sys.argv) > 3 else "e1", log=lambda m: print(m, file=sys.stderr))
    print(json.dumps(result))
