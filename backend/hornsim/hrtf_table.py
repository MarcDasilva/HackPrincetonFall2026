"""Each ear's response to sound from every direction, computed once per head (by reciprocity).

    python -m hornsim.hrtf_table <head_grid.json> [out.npz]      # from an exported grid, for checks

The scene grid (/sim) used to run one FDTD simulation per talker direction in the browser. Here the
direction is swapped out of the loop: by acoustic reciprocity, how strongly a far sound from direction
r̂ reaches an eardrum equals how strongly a source AT that eardrum radiates toward r̂. So one run per
ear, with a click at the eardrum, gives that ear's response for every direction at once:

  1. FDTD (the same scheme as frontend lib/fdtd.ts and hornsim.wavesim: staggered grid, rigid walls,
     absorbing box faces, lossy eardrum) with a click at the eardrum receiver cell.
  2. On a closed box just inside the grid (HUYGENS_MARGIN cells in), the pressure on the two layers
     either side of each face gives P and ∂P/∂n there; their spectra are accumulated on the GPU at the
     frequencies the browser needs (FFT bins of AUDIO_N at AUDIO_SR up to TF_MAX_HZ).
  3. Kirchhoff far-field integral (time convention e^{jωt}): for each direction r̂ and wavenumber k
        F(r̂) = Σ_faces e^{jk r̂·x} [ jk (r̂·n) P − ∂P/∂n ] dS
     then divided by the click's spectrum.

F is that ear's head-related transfer function up to one factor shared by every direction and both
ears (source strength, 1/r, the jk of the integral). The browser only ever uses responses relative to
the frontal one (band gains, and listening equalised to the mean frontal magnitude), so that factor
cancels. The phase keeps the arrival time relative to the head's origin, so the delay between the
ears survives. Cells of the box that fall inside a solid (the torso crosses the box floor) contribute
nothing: the truncated torso is the same approximation the plane-wave grid makes.
"""
import base64
import json
import math
import sys
import time

import numpy as np
import torch

C = 343.0
COURANT = 0.99 / math.sqrt(3)
CLICK_SIGMA = 25e-6
AUDIO_SR, AUDIO_N, TF_MAX_HZ = 48000, 512, 12000.0     # frontend lib/binaural.ts
RUN_S = 12e-3        # long enough for an earpiece's low-frequency ring: at 5 ms an aided ear read +20 dB at 160 Hz
                     # that was only truncation (10 ms: +1 dB, 20 ms: 0 dB); highs unchanged. Open ears decay faster.
HUYGENS_MARGIN = 4
AZ_STEP, ELEVATIONS = 5, (-30, -15, 0, 15, 30, 45, 60)
CHUNK = 64


def device():
    return torch.device("mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu")


def directions():
    """(D, 3) unit vectors toward the source, head frame (+x right, +y up, -z front), and their (az, el)."""
    az = np.arange(0, 360, AZ_STEP, dtype=float)
    A, E = np.meshgrid(az, np.array(ELEVATIONS, float), indexing="ij")
    a, e = np.radians(A.ravel()), np.radians(E.ravel())
    front, right = np.array([0, 0, -1.0]), np.array([1.0, 0, 0])
    d = np.cos(e)[:, None] * (np.cos(a)[:, None] * front + np.sin(a)[:, None] * right) + np.sin(e)[:, None] * np.array([0, 1.0, 0])
    return d, np.stack([A.ravel(), E.ravel()], 1)


def bins():
    k = np.arange(1, AUDIO_N // 2 + 1)
    f = k * AUDIO_SR / AUDIO_N
    keep = f <= TF_MAX_HZ
    return k[keep], f[keep]


def click(n, dt):
    tt = np.arange(n) * dt - 4 * CLICK_SIGMA
    return (-tt / CLICK_SIGMA) * np.exp(-tt ** 2 / (2 * CLICK_SIGMA ** 2))


def _huygens(shape, solid, origin, dx):
    """Faces of a box HUYGENS_MARGIN cells in: inner/outer cell indices, centre (m), outward normal."""
    nx, ny, nz = shape
    m = HUYGENS_MARGIN
    lo, hi = np.array([m, m, m]), np.array([nx - 1 - m, ny - 1 - m, nz - 1 - m])
    inner, outer, pos, nrm = [], [], [], []
    for ax in range(3):
        o = [a for a in range(3) if a != ax]
        g = np.stack(np.meshgrid(np.arange(lo[o[0]], hi[o[0]] + 1), np.arange(lo[o[1]], hi[o[1]] + 1), indexing="ij"), -1).reshape(-1, 2)
        for sgn, plane in ((1, hi[ax]), (-1, lo[ax])):
            ci = np.zeros((len(g), 3), int); ci[:, ax] = plane; ci[:, o[0]] = g[:, 0]; ci[:, o[1]] = g[:, 1]
            co = ci.copy(); co[:, ax] += sgn
            n = np.zeros(3); n[ax] = sgn
            inner.append(ci); outer.append(co)
            pos.append(origin + (ci + 0.5 * co - 0.5 * ci) * dx)        # the face between the two cells
            nrm.append(np.tile(n, (len(g), 1)))
    inner, outer, pos, nrm = (np.concatenate(v) for v in (inner, outer, pos, nrm))
    open_ = ~(solid[tuple(inner.T)] | solid[tuple(outer.T)])
    lin = lambda c: np.ravel_multi_index(c.T, shape)
    return lin(inner[open_]), lin(outer[open_]), pos[open_] * 1e-3, nrm[open_]


def run_ear(solid, drum_mask, src, origin_mm, dx_mm, dev, log=print, dirs=None):
    """One reciprocity run: click at `src`; returns the Kirchhoff far field F[D, F] for directions(), or
    for `dirs` ((D, 3) unit vectors toward the sources) when given (the optimiser needs only a few)."""
    shape = solid.shape
    dx = dx_mm * 1e-3
    dt = COURANT * dx / C
    n = int(round(RUN_S / dt))
    f32 = dict(device=dev, dtype=torch.float32)
    air = torch.from_numpy(~solid).to(dev)
    p = torch.zeros(shape, **f32)
    vx = torch.zeros((shape[0] - 1, shape[1], shape[2]), **f32)
    vy = torch.zeros((shape[0], shape[1] - 1, shape[2]), **f32)
    vz = torch.zeros((shape[0], shape[1], shape[2] - 1), **f32)
    ox = (air[1:] & air[:-1]).float(); oy = (air[:, 1:] & air[:, :-1]).float(); oz = (air[:, :, 1:] & air[:, :, :-1]).float()
    loss = np.zeros(shape, np.float32)
    for ax in range(3):
        for end in (0, -1):
            sl = [slice(None)] * 3; sl[ax] = end
            loss[tuple(sl)] += 1.0
    loss += drum_mask.astype(np.float32) / 3.0          # EARDRUM_Z (hornsim.wavesim)
    loss[solid] = 0
    absorb = torch.from_numpy(1 / (1 + COURANT * loss)).to(dev)
    sig = torch.from_numpy(click(n, dt).astype(np.float32)).to(dev)

    ii, oo, pos, nrm = _huygens(shape, solid, np.asarray(origin_mm, float), dx_mm)
    ii_t, oo_t = torch.from_numpy(ii).to(dev), torch.from_numpy(oo).to(dev)
    kb, fb = bins()
    w = 2 * np.pi * fb
    accP = torch.zeros((2, len(fb), len(ii)), **f32)      # re/im of Σ P(t) e^{-jωt}
    accD = torch.zeros((2, len(fb), len(ii)), **f32)      # same for ∂P/∂n
    bufP = torch.zeros((CHUNK, len(ii)), **f32)
    bufD = torch.zeros((CHUNK, len(ii)), **f32)
    t0 = time.time()

    def flush(t_end, m):
        tt = (np.arange(t_end - m, t_end)) * dt
        c = torch.from_numpy(np.cos(np.outer(w, tt)).astype(np.float32)).to(dev)
        s = torch.from_numpy(-np.sin(np.outer(w, tt)).astype(np.float32)).to(dev)
        accP[0] += c @ bufP[:m]; accP[1] += s @ bufP[:m]
        accD[0] += c @ bufD[:m]; accD[1] += s @ bufD[:m]

    k = 0
    for t in range(n):
        vx -= COURANT * (p[1:] - p[:-1]); vx *= ox
        vy -= COURANT * (p[:, 1:] - p[:, :-1]); vy *= oy
        vz -= COURANT * (p[:, :, 1:] - p[:, :, :-1]); vz *= oz
        p[:-1] -= COURANT * vx; p[1:] += COURANT * vx
        p[:, :-1] -= COURANT * vy; p[:, 1:] += COURANT * vy
        p[:, :, :-1] -= COURANT * vz; p[:, :, 1:] += COURANT * vz
        p[src] += sig[t]
        p *= absorb
        pf = p.view(-1)
        pin, pout = pf[ii_t], pf[oo_t]
        bufP[k] = 0.5 * (pin + pout)
        bufD[k] = (pout - pin) / dx
        k += 1
        if k == CHUNK:
            flush(t + 1, k); k = 0
    if k:
        flush(n, k)
    log(f"  run: grid {shape} at {dx_mm} mm, {n} steps, {len(ii)} surface faces, {time.time() - t0:.0f}s on {dev}")

    # Kirchhoff far field for every direction, one frequency at a time (D x S phase matrix)
    d = directions()[0] if dirs is None else np.asarray(dirs, float)
    dirs = torch.from_numpy(d.astype(np.float32)).to(dev)
    X = torch.from_numpy(pos.astype(np.float32)).to(dev)
    Nn = torch.from_numpy(nrm.astype(np.float32)).to(dev)
    proj = dirs @ X.T                                  # (D, S) r̂·x
    cosn = dirs @ Nn.T                                 # (D, S) r̂·n
    dS = dx * dx
    clk = click(n, dt)
    tt = np.arange(n) * dt
    out = np.zeros((len(d), len(fb)), np.complex64)
    for j, wj in enumerate(w):
        kj = wj / C
        ph = kj * proj
        er, ei = torch.cos(ph), torch.sin(ph)          # e^{jk r̂·x}
        Pr, Pi = accP[0, j], accP[1, j]
        Dr, Di = accD[0, j], accD[1, j]
        # term = jk (r̂·n) P − ∂P/∂n
        Tr = -kj * cosn * Pi - Dr
        Ti = kj * cosn * Pr - Di
        Fr = ((er * Tr - ei * Ti) * dS).sum(1)
        Fi = ((er * Ti + ei * Tr) * dS).sum(1)
        cs = np.sum(clk * np.exp(-1j * wj * tt))
        out[:, j] = ((Fr.cpu().numpy() + 1j * Fi.cpu().numpy()) / cs).astype(np.complex64)
    return out


def compute(grid, dev=None, log=print):
    """Both ears' tables from a head grid dict (hornsim.head_grid.export data)."""
    dev = dev or device()
    shape = tuple(grid["shape"])
    n = int(np.prod(shape))
    solid = np.unpackbits(np.frombuffer(base64.b64decode(grid["solid_b64"]), np.uint8))[:n].reshape(shape).astype(bool)
    drum = np.zeros(n, bool)
    for s in ("left", "right"):
        drum[grid["ears"][s]["eardrum"]] = True
    drum = drum.reshape(shape)
    out = {}
    for s in ("left", "right"):
        log(f"{s} ear")
        out[s] = run_ear(solid, drum, tuple(grid["ears"][s]["receiver"]), grid["origin_mm"], grid["dx_mm"], dev, log)
    _, azel = directions()
    kb, fb = bins()
    return {"azel": azel, "bin": kb, "freq_hz": fb, "left": out["left"], "right": out["right"]}


def to_json(table):
    """Compact JSON for the browser: complex responses as base64 float32 [re, im] interleaved."""
    pack = lambda a: base64.b64encode(np.stack([a.real, a.imag], -1).astype(np.float32).ravel().tobytes()).decode()
    return {"az_step": AZ_STEP, "elevations": list(ELEVATIONS), "azel": table["azel"].tolist(),
            "bins": table["bin"].tolist(), "audio_sr": AUDIO_SR, "audio_n": AUDIO_N,
            "left_b64": pack(table["left"]), "right_b64": pack(table["right"])}


if __name__ == "__main__":
    g = json.load(open(sys.argv[1]))
    t = compute(g)
    out = sys.argv[2] if len(sys.argv) > 2 else "hrtf_table.npz"
    np.savez(out, **t)
    print("saved", out)


def unit(az, el):
    """Head-frame unit vector toward a source at (az, el), as in directions()."""
    a, e = math.radians(az), math.radians(el)
    return np.cos(e) * (np.cos(a) * np.array([0, 0, -1.0]) + np.sin(a) * np.array([1.0, 0, 0])) + np.sin(e) * np.array([0, 1.0, 0])


def band_power(H, freqs_hz=None):
    """Per SII band, mean |H|^2 over 5 log-spaced points (lib/bands.ts), interpolated on log f between bins."""
    from .scoring import SII_FREQS
    fb = bins()[1] if freqs_hz is None else freqs_hz
    ff = (SII_FREQS[:, None] * 2.0 ** (-1 / 6 + (np.arange(5) + 0.5) / 15)).ravel()
    mag = np.interp(np.log(ff), np.log(fb), np.abs(H))
    return (mag.reshape(len(SII_FREQS), 5) ** 2).mean(1)
