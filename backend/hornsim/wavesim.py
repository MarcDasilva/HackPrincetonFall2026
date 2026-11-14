"""Wave simulation: a speaker near the patient's ear, sound stepped through time on a 3D grid.

    python -m hornsim.wavesim <out_dir> [--ear ear.ply] [--left] [--az 0 45 90 135 180] [--el 0]
                              [--dist 120] [--tones 2000 4000 8000] [--dx 1.0]

Without --ear it uses the AudioEar model's average ear (not anyone's ear). With a patient, pass
<patient_dir>/ear/ear.ply from earrecon.

Geometry (mm, AudioEar canonical frame: +x lateral, +y up, -z forward for a right ear):
  ear     the mesh is the pinna surface as the camera sees it, so it is a height field along x.
          Everything medial of that surface is solid.
  head    outside the ear's outline, a flat rigid plane at the canal opening's depth (x_head).
  canal   a rigid tube carved from the canal opening along the canal axis, closed at the eardrum.
          Opening position, axis and diameter come from hornsim.ear_world (assumed: a photo cannot
          see the canal).

Physics: linear acoustics, FDTD on a staggered grid (pressure at cell centres, velocity on faces),
rigid walls, absorbing box edges, a lossy eardrum. Per speaker position:
  click, with the ear and in free field -> their ear's transfer function (with ÷ without) and the
          pulse animation; a speech clip filtered by it is what reaches their eardrum
  tones   steady sine waves -> the complex amplitude of every slice cell and ear-surface point,
          relative to the incident wave; the viewer animates the phase and maps the level, and
          the time-averaged intensity gives the energy-flow streamlines

Writes <out_dir>/: index.html (viewer), ear.json, runs.json, <tag>_*.png data images, *.wav.
Serve the folder (`python -m http.server -d <out_dir>`) and open index.html.
"""
import argparse
import json
import math
import os
import shutil
import time

import numpy as np
import soundfile as sf
import torch
import trimesh
from PIL import Image

from . import ear_world as ew
from .context import load_defaults

HERE = os.path.dirname(os.path.abspath(__file__))
C = 343.0                 # speed of sound, m/s
CANAL_LEN_MM = 25.0       # opening to eardrum; ASSUMPTION, typical adult
MARGIN_MM = 15.0          # air between the farthest object and the box edge
# Eardrum loss as a resistance relative to air's characteristic impedance. A CALIBRATION KNOB, not a
# measured value: a rigid, lossless eardrum makes the canal ring with a ~40 dB peak, far above the
# published 10-20 dB open-ear gain. 3.0 puts the average ear's eardrum peak at 2.6 kHz, 18.3 dB
# (check 5 in specs/03-wave-sim.md); 1.0 erases the canal resonance, 8.0 gives 26 dB.
EARDRUM_Z = 3.0
CLICK_SIGMA = 25e-6       # s; click spectrum is still -15 dB at 12 kHz, enough to divide by
N_FRAMES = 120
N_VOL_FRAMES = 60         # 3D click frames; each is a whole 2 mm box, so fewer than the 2D slices
TONE_AMP = 0.3
PULSE_LIM = 2.5           # pulse frames span ±2.5 × the arriving pulse's peak
PHASOR_LIM = 16.0         # stored tone amplitudes span ±16 × the incident wave (the viewer shows ±2)


def device():
    return torch.device("mps" if torch.backends.mps.is_available() else
                        "cuda" if torch.cuda.is_available() else "cpu")


# ---------------------------------------------------------------- geometry

def load_ear(ear_path, left, cfg):
    """Mesh + ear world (canal opening, axis) from the SAME code the rest of hornsim uses."""
    E = cfg["ear_world"]
    mesh, world = ew.build(ear_path, E["landmarks_xlsx"], tuple(E["concha_rim_landmarks"]), E["voxel_mm"],
                           E["fit_tolerance_mm"], E["faceplate_protrusion_mm"], E["canal_opening_diameter_mm"],
                           None)          # the mesh is already in mm; do NOT rescale it
    front = np.array([0.0, 0.0, 1.0 if left else -1.0])   # earrecon mirrors z for a left ear
    return mesh, world, front


def speaker_position(world, front, az, el, dist):
    """az 0 = in front, 90 = straight out from the ear, 180 = behind; el up from the horizontal."""
    a, e = math.radians(az), math.radians(el)
    d = math.cos(e) * (math.cos(a) * front + math.sin(a) * np.array([1.0, 0, 0])) + math.sin(e) * np.array([0, 1.0, 0])
    return world.canal_point + dist * d


def grid_for(mesh, world, speakers, dx):
    """Box covering ear, canal and every speaker, plus margin. Returns origin (mm), shape."""
    canal_end = world.canal_point + world.canal_axis * CANAL_LEN_MM
    pts = np.vstack([mesh.bounds, canal_end, *speakers])
    pad = MARGIN_MM
    lo, hi = pts.min(0) - pad, pts.max(0) + pad
    shape = tuple(int(math.ceil(s / dx)) + 1 for s in hi - lo)
    return lo, shape


def solid_mask(mesh, world, x_head, origin, shape, dx):
    nx, ny, nz = shape
    xs, ys, zs = (origin[i] + dx * np.arange(shape[i]) for i in range(3))
    yy, zz = np.meshgrid(ys, zs, indexing="ij")
    start = np.stack([np.full(yy.size, mesh.bounds[1][0] + 1.0), yy.ravel(), zz.ravel()], 1)
    loc, ray, _ = mesh.ray.intersects_location(start, np.tile([-1.0, 0, 0], (len(start), 1)), multiple_hits=False)
    surface = np.full(yy.size, x_head)            # outside the ear's outline: head plane
    surface[ray] = loc[:, 0]                      # inside it: the pinna's own surface
    solid = xs[:, None, None] < surface.reshape(ny, nz)[None]

    # canal: carve a tube, closed at CANAL_LEN_MM
    r_canal = world.canal_diameter_mm / 2
    for i in range(nx):                           # per x-slab keeps memory flat
        rel = np.stack(np.meshgrid(xs[i:i + 1], ys, zs, indexing="ij"), -1)[0] - world.canal_point
        t = rel @ world.canal_axis
        r = np.linalg.norm(rel - t[..., None] * world.canal_axis, axis=-1)
        solid[i] &= ~((t > -3) & (t < CANAL_LEN_MM) & (r < r_canal))
    return solid


def eardrum_cells(world, origin, shape, dx):
    """Air cells touching the closed end of the canal: the eardrum's one lossy face each."""
    idx = np.indices(shape).reshape(3, -1).T
    rel = origin + idx * dx - world.canal_point
    t = rel @ world.canal_axis
    r = np.linalg.norm(rel - t[:, None] * world.canal_axis, axis=1)
    hit = (t >= CANAL_LEN_MM - dx) & (t < CANAL_LEN_MM) & (r < world.canal_diameter_mm / 2)
    return hit.reshape(shape)


def to_index(p, origin, dx, shape):
    i = np.round((np.asarray(p) - origin) / dx).astype(int)
    if np.any(i < 0) or np.any(i >= shape):
        raise ValueError(f"point {p} is outside the grid")
    return tuple(i)


# ---------------------------------------------------------------- solver

def pool2(a):
    """2×2×2 block mean (drops an odd last cell). Written by hand because MPS lacks avg_pool3d."""
    nx, ny, nz = (n // 2 for n in a.shape[-3:])
    return a[..., :2 * nx, :2 * ny, :2 * nz].reshape(*a.shape[:-3], nx, 2, ny, 2, nz, 2).mean((-5, -3, -1))


def fdtd(solid, src, signal, receivers, dev, eardrum=None, frames=None, dft=None, vol=None):
    """Step pressure and velocity through `len(signal)` time steps.

    frames: {"every", "n", "slices": {name: (axis, index)}, "surf_lin"} -> instantaneous snapshots
    dft:    {"hz", "dt", "start", "slices", "surf_lin", "flow_y", "full"} -> complex amplitude A of the
            steady tone, with p(t) = Re{A·e^(iωt)}, on each slice and at the ear-surface samples, plus
            the in-plane velocity on the horizontal slice for the time-averaged intensity; with
            "full", also over the whole box at 2 mm ("volume").
    vol:    {"every", "n"} -> whole-box snapshots at 2 mm ("vframes"), for the 3D click.
    Returns {"traces", "frames", "surface", "phasor", "surface_phasor", "velocity"}.
    """
    nx, ny, nz = solid.shape
    n_steps = len(signal)
    courant = 0.99 / math.sqrt(3)                 # stability limit for 3D FDTD
    f32 = dict(device=dev, dtype=torch.float32)

    air = torch.from_numpy(~solid).to(dev)
    p = torch.zeros(solid.shape, **f32)
    vx = torch.zeros((nx - 1, ny, nz), **f32)
    vy = torch.zeros((nx, ny - 1, nz), **f32)
    vz = torch.zeros((nx, ny, nz - 1), **f32)
    # a face moves ONLY between two air cells — that is the rigid wall
    ox = (air[1:] & air[:-1]).float(); oy = (air[:, 1:] & air[:, :-1]).float(); oz = (air[:, :, 1:] & air[:, :, :-1]).float()

    # Box faces absorb: their outward velocity equals pressure / air impedance, so a wave leaves at
    # every frequency. A sponge layer does NOT work here — at speech frequencies a few cm of sponge
    # is thin next to the wavelength and the box rings like a closed room. The eardrum is the same
    # boundary with a higher impedance. Both are applied implicitly (divide, don't subtract) so
    # corner cells with three open faces stay stable.
    loss = np.zeros(solid.shape, np.float32)
    for ax in range(3):
        for end in (0, -1):
            sl = [slice(None)] * 3; sl[ax] = end
            loss[tuple(sl)] += 1.0
    if eardrum is not None:
        loss += eardrum / EARDRUM_Z
    loss[solid] = 0
    absorb = torch.from_numpy(1 / (1 + courant * loss)).to(dev)

    rec_lin = torch.tensor([np.ravel_multi_index(r, solid.shape) for r in receivers], device=dev)
    traces = torch.zeros((n_steps, len(receivers)), **f32)
    sig = torch.from_numpy(signal.astype(np.float32)).to(dev)
    if frames:
        fr = {k: torch.zeros((frames["n"],) + tuple(np.delete(solid.shape, ax)), **f32) for k, (ax, _) in frames["slices"].items()}
        fs_lin = torch.from_numpy(frames["surf_lin"]).to(dev)
        fsurf = torch.zeros((frames["n"], len(frames["surf_lin"])), **f32)
    if dft:
        w, dt = 2 * math.pi * dft["hz"], dft["dt"]
        acc = {k: torch.zeros((2,) + tuple(np.delete(solid.shape, ax)), **f32) for k, (ax, _) in dft["slices"].items()}
        ds_lin = torch.from_numpy(dft["surf_lin"]).to(dev)
        accs = torch.zeros((2, len(dft["surf_lin"])), **f32)
        accv = torch.zeros((4, nx, nz), **f32)    # re/im of cell-centred vx and vz on the horizontal slice
        fy = dft["flow_y"]
        if dft.get("full"):
            vre = torch.zeros_like(p); vim = torch.zeros_like(p)
    if vol:
        vfr = torch.zeros((vol["n"],) + tuple(n // 2 for n in solid.shape), **f32)

    for t in range(n_steps):
        vx -= courant * (p[1:] - p[:-1]); vx *= ox
        vy -= courant * (p[:, 1:] - p[:, :-1]); vy *= oy
        vz -= courant * (p[:, :, 1:] - p[:, :, :-1]); vz *= oz
        p[:-1] -= courant * vx; p[1:] += courant * vx
        p[:, :-1] -= courant * vy; p[:, 1:] += courant * vy
        p[:, :, :-1] -= courant * vz; p[:, :, 1:] += courant * vz
        p[src] += sig[t]
        p *= absorb
        traces[t] = p.view(-1)[rec_lin]
        if frames and t % frames["every"] == 0 and t // frames["every"] < frames["n"]:
            f = t // frames["every"]
            for k, (ax, i) in frames["slices"].items():
                fr[k][f] = p.select(ax, i)
            fsurf[f] = p.view(-1)[fs_lin]
        if vol and t % vol["every"] == 0 and t // vol["every"] < vol["n"]:
            vfr[t // vol["every"]] = pool2(p)
        if dft and t >= dft["start"]:
            c, s = math.cos(w * t * dt), -math.sin(w * t * dt)
            for k, (ax, i) in dft["slices"].items():
                sl = p.select(ax, i); acc[k][0] += sl * c; acc[k][1] += sl * s
            ps = p.view(-1)[ds_lin]; accs[0] += ps * c; accs[1] += ps * s
            cx = torch.zeros((nx, nz), **f32); cx[1:] += vx[:, fy, :]; cx[:-1] += vx[:, fy, :]
            cz = torch.zeros((nx, nz), **f32); cz[:, 1:] += vz[:, fy, :]; cz[:, :-1] += vz[:, fy, :]
            accv[0] += cx * c; accv[1] += cx * s; accv[2] += cz * c; accv[3] += cz * s
            if dft.get("full"):
                vre += p * c; vim += p * s

    out = {"traces": traces.cpu().numpy()}
    if frames:
        out["frames"] = {k: v.cpu().numpy() for k, v in fr.items()}
        out["surface"] = fsurf.cpu().numpy()
    if dft:
        k = 2.0 / (n_steps - dft["start"])
        cpx = lambda a: (a[0] + 1j * a[1]).cpu().numpy() * k
        out["phasor"] = {name: cpx(a) for name, a in acc.items()}
        out["surface_phasor"] = cpx(accs)
        v = accv.cpu().numpy() * k * 0.5          # the 0.5 undoes summing two faces
        out["velocity"] = (v[0] + 1j * v[1], v[2] + 1j * v[3])
        if dft.get("full"):
            out["volume"] = (pool2(vre) * k).cpu().numpy() + 1j * (pool2(vim) * k).cpu().numpy()
    if vol:
        out["vframes"] = vfr.cpu().numpy()
    return out


def click(n_steps, dt):
    t = np.arange(n_steps) * dt - 4 * CLICK_SIGMA
    return -t / CLICK_SIGMA * np.exp(-t ** 2 / (2 * CLICK_SIGMA ** 2))   # no DC: injects no net volume


def tone(n_steps, dt, f, amp=TONE_AMP):
    t = np.arange(n_steps) * dt
    ramp = np.clip(t * f / 3, 0, 1)                                     # 3-period fade-in
    return amp * ramp * np.sin(2 * np.pi * f * t)


# ---------------------------------------------------------------- outputs

def save_u16(values, lim, path, mask=None):
    """Signed values clipped to ±lim -> RGB PNG: R = high byte, G = low byte, B = 255 where solid.
    16 bits keep the contour lines smooth; NO alpha channel, because browsers premultiply it."""
    q = np.round((np.clip(values / lim, -1, 1) * 0.5 + 0.5) * 65535).astype(np.uint16)
    rgb = np.zeros(values.shape + (3,), np.uint8)
    rgb[..., 0], rgb[..., 1] = q >> 8, q & 255
    if mask is not None:
        rgb[..., 2] = mask * 255
    Image.fromarray(rgb).save(path, optimize=True)
    return os.path.basename(path)


def save_volume(vol, lim, path, mask=None):
    """(X, Y, Z) or (F, X, Y, Z) values -> one PNG of z-slice tiles (rows = y, columns = x), frames
    one after another. 16-bit R/G + mask in B for a single volume; 8-bit grey for frame stacks.
    The viewer rebuilds a 3D texture from it in x-fastest order."""
    v = vol if vol.ndim == 4 else vol[None]
    F, X, Y, Z = v.shape
    n = F * Z
    cols = int(math.ceil(math.sqrt(n * Y / X)))   # roughly square image
    rows = int(math.ceil(n / cols))
    u8 = vol.ndim == 4
    img = np.zeros((rows * Y, cols * X) + (() if u8 else (3,)), np.uint8)
    for f in range(F):
        for z in range(Z):
            r, c = divmod(f * Z + z, cols)
            tile = np.clip(v[f, :, :, z].T / lim, -1, 1)
            ys, xs = slice(r * Y, (r + 1) * Y), slice(c * X, (c + 1) * X)
            if u8:
                img[ys, xs] = np.round(128 + 127 * tile)
            else:
                q = np.round((tile * 0.5 + 0.5) * 65535).astype(np.uint16)
                img[ys, xs, 0], img[ys, xs, 1] = q >> 8, q & 255
                if mask is not None:
                    img[ys, xs, 2] = mask[:, :, z].T * 255
    Image.fromarray(img).save(path, optimize=True)
    return {"file": os.path.basename(path), "cols": cols, "frames": F, "lim": lim}


def save_atlas(frames, lim, path, cols=None):
    """(F, A, B) signed frames -> one greyscale PNG grid, linear, 128 = zero, ±lim = 1 / 255."""
    F, A, B = frames.shape
    cols = cols or int(math.ceil(math.sqrt(F)))
    rows = int(math.ceil(F / cols))
    img = np.full((rows * A, cols * B), 128, np.uint8)
    q = np.round(128 + 127 * np.clip(frames / lim, -1, 1)).astype(np.uint8)
    for f in range(F):
        r, c = divmod(f, cols)
        img[r * A:(r + 1) * A, c * B:(c + 1) * B] = q[f]
    Image.fromarray(img).save(path, optimize=True)
    return {"file": os.path.basename(path), "frames": F, "cols": cols, "tile": [A, B], "lim": lim}


def streamlines(Ix, Iz, solid2d, x0, z0, dx, seed_xz, n=72, r0=10.0, step=0.5, max_len=400.0):
    """Energy paths on the horizontal slice: lines everywhere tangent to the time-averaged intensity,
    started on a small circle around the speaker. Each line stops at a wall, the box edge, or where
    the flow fades. Returns polylines in mm as [[x, z], ...]."""
    mag = np.hypot(Ix, Iz)
    mag[solid2d] = 0
    floor = np.percentile(mag[mag > 0], 5)
    nx, nz = Ix.shape

    def direction(x, z):
        fi, fk = (x - x0) / dx, (z - z0) / dx
        i, k = int(fi), int(fk)
        if not (0 <= i < nx - 1 and 0 <= k < nz - 1):
            return None
        a, b = fi - i, fk - k
        wts = ((i, k, (1 - a) * (1 - b)), (i + 1, k, a * (1 - b)), (i, k + 1, (1 - a) * b), (i + 1, k + 1, a * b))
        if any(solid2d[ii, kk] and w_ > 0.25 for ii, kk, w_ in wts):
            return None
        u = sum(w_ * Ix[ii, kk] for ii, kk, w_ in wts); v = sum(w_ * Iz[ii, kk] for ii, kk, w_ in wts)
        m = math.hypot(u, v)
        return None if m < floor else (u / m, v / m)

    lines = []
    for j in range(n):
        a = 2 * math.pi * j / n
        x, z = seed_xz[0] + r0 * math.cos(a), seed_xz[1] + r0 * math.sin(a)
        pts, walked = [[x, z]], 0.0
        while walked < max_len:
            d1 = direction(x, z)
            if d1 is None:
                break
            d2 = direction(x + d1[0] * step / 2, z + d1[1] * step / 2) or d1   # midpoint (RK2)
            x, z = x + d2[0] * step, z + d2[1] * step
            walked += step
            if walked % 2.0 < step:
                pts.append([round(x, 2), round(z, 2)])
        if len(pts) > 3:
            lines.append(pts)
    return lines


def transfer(trace, ref, dt, fmax=12000):
    n = 1 << int(math.ceil(math.log2(len(trace) * 4)))
    f = np.fft.rfftfreq(n, dt)
    H = np.fft.rfft(trace, n) / np.fft.rfft(ref, n)
    keep = (f >= 100) & (f <= fmax)
    return f[keep], H[keep]


def apply_transfer(x, fs, f, H):
    n = 1 << int(math.ceil(math.log2(len(x) + 4096)))
    X = np.fft.rfft(x, n)
    fx = np.fft.rfftfreq(n, 1 / fs)
    Hx = np.interp(fx, f, H.real, left=1.0, right=0.0) + 1j * np.interp(fx, f, H.imag, left=0.0, right=0.0)
    return np.fft.irfft(X * Hx, n)[: len(x)]


# ---------------------------------------------------------------- driver

def simulate(out, ear_path, left=False, azimuths=(90,), elevations=(0,), dist=120.0, tones_hz=(2000, 4000, 8000),
             dx=1.0, clip="clean_1", landmarks_xlsx=None, log=print):
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    cfg = load_defaults()
    cfg["ear_world"]["landmarks_xlsx"] = landmarks_xlsx or os.environ.get(
        "LANDMARKS_XLSX", os.path.join(HERE, "..", "third_party", "AudioEar", "data", "55_landmarks.xlsx"))
    mesh, world, front = load_ear(ear_path, left, cfg)
    x_head = float(world.canal_point[0])          # head plane flush with the canal opening
    dev = device()
    dt = 0.99 / math.sqrt(3) * dx * 1e-3 / C
    surf_pts = mesh.vertices + 1.5 * mesh.vertex_normals   # 1.5 mm out along each normal, so samples sit in air
    speech, fs = sf.read(os.path.join(HERE, "..", "assets", "speech", f"{clip}.wav"))
    runs, audio = [], {"free": speech}

    for el in elevations:
        for az in azimuths:
            t1 = time.time()
            tag = f"az{az:03.0f}_el{el:+03.0f}"
            spk = speaker_position(world, front, az, el, dist)
            origin, shape = grid_for(mesh, world, [spk], dx)        # one box per position keeps each small
            solid = solid_mask(mesh, world, x_head, origin, shape, dx)
            drum = eardrum_cells(world, origin, shape, dx) & ~solid
            rec = [to_index(world.canal_point + world.canal_axis * 1.5, origin, dx, shape),
                   to_index(world.canal_point + world.canal_axis * (CANAL_LEN_MM - 1.5), origin, dx, shape)]
            for r in rec:
                assert not solid[r], "receiver landed inside the wall; check the canal axis"
            s = to_index(spk, origin, dx, shape)
            while solid[s]:                            # a grazing speaker can sit in the head plane
                s = (s[0] + 1, s[1], s[2])
            spk = origin + np.array(s) * dx
            cy, cz = to_index(world.canal_point, origin, dx, shape)[1:]
            slices = {"h": (1, cy), "v": (2, cz)}      # horizontal (x-z) and vertical (x-y) through the canal
            si = np.clip(np.round((surf_pts - origin) / dx).astype(int), 0, np.array(shape) - 1)
            surf_lin = np.ravel_multi_index(si.T, shape)
            masks = {"h": solid[:, cy, :], "v": solid[:, :, cz]}

            # 1 · click: the numbers (transfer functions, audio) and the pulse animation
            n_click = int(6e-3 / dt)
            reach_s = (np.linalg.norm(spk - world.canal_point) + CANAL_LEN_MM + 20) * 1e-3 / C
            every = max(1, int(math.ceil((reach_s + 4 * CLICK_SIGMA + 1e-4) / dt / N_FRAMES)))
            sig = click(n_click, dt)
            every3 = int(math.ceil(every * N_FRAMES / N_VOL_FRAMES))
            ear = fdtd(solid, s, sig, rec, dev, drum,
                       frames={"every": every, "n": N_FRAMES, "slices": slices, "surf_lin": surf_lin},
                       vol={"every": every3, "n": N_VOL_FRAMES})
            ref = fdtd(np.zeros_like(solid), s, sig, rec[:1], dev)["traces"][:, 0]

            # self-check: in free field the click reaches the entrance at distance / c
            r_m = np.linalg.norm((np.array(rec[0]) - np.array(s)) * dx) * 1e-3
            arrive = np.argmax(np.abs(ref)) * dt - 4 * CLICK_SIGMA
            assert abs(arrive - r_m / C) < 2 * CLICK_SIGMA, f"free-field arrival {arrive * 1e6:.0f} us vs {r_m / C * 1e6:.0f} us"

            f, H_ent = transfer(ear["traces"][:, 0], ref, dt)
            _, H_drum = transfer(ear["traces"][:, 1], ref, dt)
            np.savez(os.path.join(out, f"{tag}_transfer.npz"), freqs_hz=f, entrance=H_ent, eardrum=H_drum)
            audio[tag] = apply_transfer(speech, fs, f, H_drum)

            # Pulse frames are scaled to the click's free-field peak at the canal entrance, so 1.0 is
            # "as strong as the arriving pulse". Near the speaker it saturates; that is expected.
            peak = np.abs(ref).max()
            files = {"pulse": {k: save_atlas(v / peak, PULSE_LIM, os.path.join(out, f"{tag}_pulse_{k}.png"))
                               for k, v in ear["frames"].items()},
                     "masks": {k: save_u16(np.zeros(m.shape), 1, os.path.join(out, f"{tag}_mask_{k}.png"), m)
                               for k, m in masks.items()}}
            files["pulse"]["surface"] = save_atlas(ear["surface"][:, None, :] / peak, PULSE_LIM,
                                                   os.path.join(out, f"{tag}_pulse_surface.png"), cols=1)
            files["pulse"]["frame_us"] = round(every * dt * 1e6, 3)
            files["pulse"]["vol"] = save_volume(ear["vframes"] / peak, PULSE_LIM, os.path.join(out, f"{tag}_pulse_vol.png"))
            files["pulse"]["vol"]["frame_us"] = round(every3 * dt * 1e6, 3)
            vmask = solid[:2 * (shape[0] // 2), :2 * (shape[1] // 2), :2 * (shape[2] // 2)].reshape(
                shape[0] // 2, 2, shape[1] // 2, 2, shape[2] // 2, 2).mean((1, 3, 5)) > 0.5
            files["volume"] = {"dims": list(vmask.shape), "box_min": np.round(origin - dx / 2, 2).tolist(),
                               "box_size": [2 * dx * n for n in vmask.shape]}

            # 2 · steady tones: complex amplitude relative to the incident wave at the canal entrance
            n_fft = 1 << int(math.ceil(math.log2(n_click * 4)))
            ff = np.fft.rfftfreq(n_fft, dt)
            G_free = np.fft.rfft(ref, n_fft) / np.fft.rfft(sig, n_fft)    # source -> entrance, open air
            files["tones"] = []
            for hz in tones_hz:
                n_t = int((reach_s + 10 / hz) / dt)                        # ramp, arrival, settle
                start = n_t - int(round(2 / hz / dt))                     # average the last 2 periods
                tn = fdtd(solid, s, tone(n_t, dt, hz), rec, dev, drum,
                          dft={"hz": hz, "dt": dt, "start": start, "full": True, "slices": slices, "surf_lin": surf_lin, "flow_y": cy})
                inc = TONE_AMP * np.abs(G_free[np.argmin(np.abs(ff - hz))])
                A = {k: v / inc for k, v in tn["phasor"].items()}
                As = tn["surface_phasor"] / inc
                Vx, Vz = (v / inc for v in tn["velocity"])
                Ix, Iz = (0.5 * np.real(A["h"] * np.conj(V)) for V in (Vx, Vz))   # time-averaged intensity
                o = {"hz": hz, "wavelength_mm": round(C / hz * 1000, 1), "lim": PHASOR_LIM}
                for k in ("h", "v"):
                    o[k] = {"re": save_u16(A[k].real, PHASOR_LIM, os.path.join(out, f"{tag}_{hz}_{k}_re.png")),
                            "im": save_u16(A[k].imag, PHASOR_LIM, os.path.join(out, f"{tag}_{hz}_{k}_im.png"))}
                o["surface"] = {"re": save_u16(As.real[None], PHASOR_LIM, os.path.join(out, f"{tag}_{hz}_surface_re.png")),
                                "im": save_u16(As.imag[None], PHASOR_LIM, os.path.join(out, f"{tag}_{hz}_surface_im.png"))}
                o["vol"] = {"re": save_volume(tn["volume"].real / inc, PHASOR_LIM, os.path.join(out, f"{tag}_{hz}_vol_re.png"), vmask),
                            "im": save_volume(tn["volume"].imag / inc, PHASOR_LIM, os.path.join(out, f"{tag}_{hz}_vol_im.png"))}
                o["streamlines"] = streamlines(Ix, Iz, masks["h"], origin[0], origin[2], dx, (spk[0], spk[2]))
                o["entrance_db"] = round(float(20 * np.log10(np.abs(A["h"][rec[0][0], rec[0][2]]) + 1e-9)), 1)
                files["tones"].append(o)

            db = lambda H: np.round(20 * np.log10(np.abs(H) + 1e-12), 2).tolist()
            pick = np.unique(np.geomspace(1, len(f) - 1, 160).astype(int))
            fpk = f[np.argmax(np.abs(H_drum))]
            lab = lambda ax: (origin[ax] + dx * np.array([0, shape[ax] - 1])).round(2).tolist()
            runs.append({"tag": tag, "az": az, "el": el, "speaker_mm": np.round(spk, 2).tolist(), "files": files,
                         "audio": f"{tag}.wav",
                         "planes": {"h": {"y": round(float(origin[1] + dx * cy), 2), "x": lab(0), "z": lab(2)},
                                    "v": {"z": round(float(origin[2] + dx * cz), 2), "x": lab(0), "y": lab(1)}},
                         "transfer": {"freqs_hz": np.round(f[pick]).tolist(), "entrance_db": db(H_ent[pick]),
                                      "eardrum_db": db(H_drum[pick])},
                         "eardrum_peak_hz": round(float(fpk))})
            log(f"{tag}: grid {shape} {np.prod(shape) / 1e6:.1f} M cells; eardrum gain peaks at {fpk:.0f} Hz "
                f"({20 * np.log10(np.abs(H_drum).max()):.1f} dB); free-field arrival ok  ({time.time() - t1:.1f}s)")

    # one shared level so directions stay comparable by ear
    g = 0.9 / max(np.abs(a).max() for a in audio.values())
    for k, a in audio.items():
        sf.write(os.path.join(out, f"{k}.wav"), a * g, fs)

    json.dump({"note": "mm, AudioEar frame: +x lateral, +y up; forward is " + ("+z" if left else "-z"),
               "ear": {"verts": np.round(mesh.vertices, 2).ravel().tolist(), "faces": mesh.faces.ravel().tolist()},
               "canal": {"point": np.round(world.canal_point, 2).tolist(), "axis": np.round(world.canal_axis, 4).tolist(),
                         "length_mm": CANAL_LEN_MM, "diameter_mm": world.canal_diameter_mm},
               "x_head": round(x_head, 2), "front": front.tolist(), "dx_mm": dx, "dist_mm": dist, "clip": clip,
               "side": "left" if left else "right",
               "assumptions": ["Pressure is shown relative to the incoming wave at the canal entrance (1.0 = the wave "
                               "as it would arrive with no ear there). Values near the speaker exceed the colour range.",
                               "Canal opening, axis, 7.5 mm diameter and 25 mm length are assumed; a photo cannot see them.",
                               "The head is a flat rigid wall; only the outer ear is from the photo.",
                               "Grid: 1 mm cells, accurate to about 10 kHz."]},
              open(os.path.join(out, "ear.json"), "w"))
    json.dump(runs, open(os.path.join(out, "runs.json"), "w"))
    shutil.copy(os.path.join(HERE, "wave_viewer.html"), os.path.join(out, "index.html"))
    log(f"done in {time.time() - t0:.0f}s -> {out}")
    return runs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--ear", help="ear.ply from earrecon; default: the model's average ear")
    ap.add_argument("--left", action="store_true")
    ap.add_argument("--az", type=float, nargs="+", default=[90])
    ap.add_argument("--el", type=float, nargs="+", default=[0])
    ap.add_argument("--dist", type=float, default=120.0, help="speaker distance from the canal opening, mm")
    ap.add_argument("--tones", type=float, nargs="+", default=[2000, 4000, 8000], help="steady tones to show (Hz)")
    ap.add_argument("--dx", type=float, default=1.0, help="grid cell, mm")
    a = ap.parse_args()
    ear = a.ear
    if not ear:
        from earrecon.reconstruct import mean_ear
        ear = mean_ear(os.path.join(a.out, "mean_ear"))
    simulate(a.out, ear, a.left, a.az, a.el, a.dist, [int(t) for t in a.tones], a.dx)
