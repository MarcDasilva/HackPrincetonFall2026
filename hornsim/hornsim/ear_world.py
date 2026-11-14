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
