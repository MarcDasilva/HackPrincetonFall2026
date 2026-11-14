// Port of backend/hornsim/wavesim.py `fdtd` (linear acoustics, staggered grid, rigid walls,
// absorbing box faces, lossy eardrum) for one click from one speaker, on the dummy-head grid of
// backend/hornsim/head_grid.py: both ears on one head, so one run gives both eardrum traces.
// Pure TS: runs in a Web Worker in the browser and under node for checks. Units are grid cells and
// time steps; the update is the backend's, term for term, written as one fused branch-free pass
// (the face masks are 0/1 multipliers) because the head grid is ~7x the old single-ear box.

export type Side = "left" | "right";
export const SIDES: Side[] = ["left", "right"];

export type Ellipsoid = { center: [number, number, number]; axes: [number, number, number] };
/** backend hornsim/head_shape.py HeadShape.to_json: horizontal ellipse sections stacked in y (half-width w,
 * half-depth d, centre z c), plus a generic neck and shoulders. */
export type HeadShape = {
  source: string;
  profile: { y: number[]; w: number[]; d: number[]; c: number[] };
  torso: Ellipsoid;
  neck: { center_xz: [number, number]; axes_xz: [number, number]; y: [number, number] };
  meta: { measured?: boolean; breadth_mm?: number; length_mm?: number; [k: string]: unknown };
};

export type EarOnHead = {
  eardrum: number[];
  receiver: [number, number, number];
  canal_point_mm: [number, number, number];
  canal_axis: [number, number, number];
  canal_diameter_mm: number;
  mesh: { verts: number[]; faces: number[] };
  /** the pinna's lateral surface (head-frame x) on a (y, z) lattice; null outside the ear's outline */
  surface: { y0: number; z0: number; d: number; ny: number; nz: number; x: (number | null)[] };
};

export type HeadGrid = {
  version: number;
  shape: [number, number, number];
  dx_mm: number;
  origin_mm: [number, number, number];
  radius_mm: number;
  el_range: [number, number];
  canal_len_mm: number;
  eardrum_z: number;
  front: [number, number, number];
  right: [number, number, number];
  head: HeadShape;
  solid_b64: string;
  ears: Record<Side, EarOnHead>;
};

export const C_AIR = 343.0;
export const COURANT = 0.99 / Math.sqrt(3);
export const CLICK_SIGMA = 25e-6;

export function dtFor(grid: HeadGrid) {
  return (COURANT * grid.dx_mm * 1e-3) / C_AIR;
}

export function decodeSolid(grid: HeadGrid): Uint8Array {
  const n = grid.shape[0] * grid.shape[1] * grid.shape[2];
  const bin = typeof atob === "function" ? atob(grid.solid_b64) : Buffer.from(grid.solid_b64, "base64").toString("binary");
  const out = new Uint8Array(n);
  for (let i = 0; i < n; i++) out[i] = (bin.charCodeAt(i >> 3) >> (7 - (i & 7))) & 1; // np.packbits is MSB first
  return out;
}

/** Head frame: az 0 = in front, 90 = right ear side, 180 = behind, 270 = left ear side; el up from horizontal. */
export function speakerMm(grid: HeadGrid, az: number, el: number, dist = grid.radius_mm): [number, number, number] {
  const a = (az * Math.PI) / 180, e = (el * Math.PI) / 180;
  const f = grid.front, r = grid.right;
  return [0, 1, 2].map((i) => dist * (Math.cos(e) * (Math.cos(a) * f[i] + Math.sin(a) * r[i]) + (i === 1 ? Math.sin(e) : 0))) as [number, number, number];
}

export type FdtdOptions = {
  nSteps: number;
  /** emit a horizontal pressure slice (constant y = sliceY) every `frameEvery` steps */
  frameEvery?: number;
  /** stop emitting frames after this step */
  frameSteps?: number;
  sliceY?: number;
  onFrame?: (step: number, slice: Float32Array) => void;
  shouldStop?: () => boolean;
};

/** Unit propagation direction of a far talker at (az, el): from the speaker toward the head. */
export function arrivalDir(grid: HeadGrid, az: number, el: number): [number, number, number] {
  const s = speakerMm(grid, az, el, 1);
  return [-s[0], -s[1], -s[2]];
}

/** Total-field / scattered-field plane-wave source (Taflove & Hagness, Computational
 * Electrodynamics, ch. 5, written for this pressure-velocity scheme). Inside the box `tf` cells
 * (TF_MARGIN cells in from every face) the grid holds the total field: a plane click arriving
 * along `dir` plus what the head scatters. Outside it holds the scattered field only, which the
 * absorbing faces take out. So the talker is effectively far away: no 1/r near-field level
 * difference between the ears, which a point speaker a few cm from the near ear would add. */
export const TF_MARGIN = 3;

type Corr = { idx: Int32Array; coef: Float32Array; delay: Float32Array };

function planeWaveCorrections(grid: HeadGrid, solid: Uint8Array, dir: [number, number, number], P: number) {
  const [nx, ny, nz] = grid.shape, sy = nz, sx = ny * nz, dx = grid.dx_mm * 1e-3, k = COURANT;
  const lo = [TF_MARGIN, TF_MARGIN, TF_MARGIN], hi = [nx - 1 - TF_MARGIN, ny - 1 - TF_MARGIN, nz - 1 - TF_MARGIN];
  const o = grid.origin_mm.map((v) => v * 1e-3);
  const pos = (i: number, j: number, l: number, a: number, half: number) =>
    [o[0] + (i + (a === 0 ? half : 0)) * dx, o[1] + (j + (a === 1 ? half : 0)) * dx, o[2] + (l + (a === 2 ? half : 0)) * dx];
  // wavefront enters the TF box at t = 0: delay is measured from the box corner it reaches first
  let dmin = Infinity;
  for (const i of [lo[0], hi[0]]) for (const j of [lo[1], hi[1]]) for (const l of [lo[2], hi[2]]) {
    const x = pos(i, j, l, -1, 0);
    dmin = Math.min(dmin, dir[0] * x[0] + dir[1] * x[1] + dir[2] * x[2]);
  }
  const delay = (x: number[]) => (dir[0] * x[0] + dir[1] * x[1] + dir[2] * x[2] - dmin) / C_AIR;
  const v: { idx: number; coef: number; delay: number; axis: number }[] = [];
  const p: { idx: number; coef: number; delay: number }[] = [];
  const strides = [sx, sy, 1];
  for (let a = 0; a < 3; a++) {
    const s = strides[a];
    // faces on the low plane (cell lo-1 scattered | cell lo total) and high plane (hi total | hi+1 scattered)
    for (const [plane, inLow] of [[lo[a] - 1, false], [hi[a], true]] as const) {
      const r0 = a === 0 ? [plane, plane] : [lo[0], hi[0]], r1 = a === 1 ? [plane, plane] : [lo[1], hi[1]], r2 = a === 2 ? [plane, plane] : [lo[2], hi[2]];
      for (let i = r0[0]; i <= r0[1]; i++) for (let j = r1[0]; j <= r1[1]; j++) for (let l = r2[0]; l <= r2[1]; l++) {
        const q = i * sx + j * sy + l, qs = q + s;
        if (solid[q] || solid[qs]) continue;               // closed face: no flow, nothing to correct
        const ci = [i, j, l];
        const cHi = [...ci]; cHi[a] += 1;
        if (inLow) {
          // q total, q+s scattered: v_q sees total p at q+s; cell q+s sees scattered v_q
          v.push({ idx: q + P, coef: -k, delay: delay(pos(cHi[0], cHi[1], cHi[2], -1, 0)), axis: a });
          p.push({ idx: qs, coef: -k * dir[a], delay: delay(pos(i, j, l, a, 0.5)) });
        } else {
          // q scattered, q+s total
          v.push({ idx: q + P, coef: k, delay: delay(pos(i, j, l, -1, 0)), axis: a });
          p.push({ idx: q, coef: k * dir[a], delay: delay(pos(i, j, l, a, 0.5)) });
        }
      }
    }
  }
  const pack = <T extends { idx: number; coef: number; delay: number }>(xs: T[]): Corr =>
    ({ idx: Int32Array.from(xs.map((x) => x.idx)), coef: Float32Array.from(xs.map((x) => x.coef)), delay: Float32Array.from(xs.map((x) => x.delay)) });
  const byAxis = [0, 1, 2].map((a) => pack(v.filter((x) => x.axis === a)));
  return { v: byAxis, p: pack(p) };
}

/** The click waveform as a fine lookup table: incident p (= normal velocity × dir) at time τ after arrival. */
function clickTable(dt: number) {
  const h = dt / 16, n = Math.ceil((10 * CLICK_SIGMA) / h) + 2, tab = new Float32Array(n);
  for (let m = 0; m < n; m++) { const tt = m * h - 4 * CLICK_SIGMA; tab[m] = (-tt / CLICK_SIGMA) * Math.exp(-(tt * tt) / (2 * CLICK_SIGMA * CLICK_SIGMA)); }
  return (tau: number) => { const u = tau / h; if (u <= 0 || u >= n - 1) return 0; const m = u | 0, f = u - m; return tab[m] + f * (tab[m + 1] - tab[m]); };
}

/** Pressure traces at both eardrum receivers for a far talker whose plane click arrives along `dir`. */
export function runPlaneWave(grid: HeadGrid, solid: Uint8Array, dir: [number, number, number], opt: FdtdOptions): Record<Side, Float32Array> {
  const [nx, ny, nz] = grid.shape;
  const N = nx * ny * nz;
  const sy = nz, sx = ny * nz; // strides, C order (x, y, z)
  const P = sx;                // velocity arrays are offset by one x-slab so face q-stride is always in range (zeros)
  const k = COURANT;
  const p = new Float32Array(N);
  const vX = new Float32Array(N + P), vY = new Float32Array(N + P), vZ = new Float32Array(N + P); // face (i+½) at q+P
  // open faces (1) only between two air cells; 0 holds the face velocity at zero (rigid wall / box edge)
  const mX = new Float32Array(N), mY = new Float32Array(N), mZ = new Float32Array(N);
  for (let i = 0; i < nx; i++)
    for (let j = 0; j < ny; j++)
      for (let l = 0; l < nz; l++) {
        const q = i * sx + j * sy + l;
        if (solid[q]) continue;
        if (i < nx - 1 && !solid[q + sx]) mX[q] = 1;
        if (j < ny - 1 && !solid[q + sy]) mY[q] = 1;
        if (l < nz - 1 && !solid[q + 1]) mZ[q] = 1;
      }
  // implicit absorption: box faces (impedance of air) and each eardrum (EARDRUM_Z × air)
  const loss = new Float32Array(N);
  for (let i = 0; i < nx; i++)
    for (let j = 0; j < ny; j++)
      for (let l = 0; l < nz; l++) {
        let c = 0;
        if (i === 0 || i === nx - 1) c++;
        if (j === 0 || j === ny - 1) c++;
        if (l === 0 || l === nz - 1) c++;
        loss[i * sx + j * sy + l] = c;
      }
  for (const s of ["left", "right"] as Side[]) for (const q of grid.ears[s].eardrum) loss[q] += 1 / grid.eardrum_z;
  const absorbIdx: number[] = [], absorbVal: number[] = [];
  for (let q = 0; q < N; q++) {
    if (solid[q]) continue;
    if (loss[q] > 0) { absorbIdx.push(q); absorbVal.push(1 / (1 + k * loss[q])); }
  }
  const aIdx = Int32Array.from(absorbIdx), aVal = Float32Array.from(absorbVal);
  const dt = dtFor(grid), inc = clickTable(dt);
  const corr = planeWaveCorrections(grid, solid, dir, P);
  const vArr = [vX, vY, vZ];
  const lin = ([i, j, l]: number[]) => i * sx + j * sy + l;
  const recL = lin(grid.ears.left.receiver), recR = lin(grid.ears.right.receiver);
  const out = { left: new Float32Array(opt.nSteps), right: new Float32Array(opt.nSteps) };
  const sliceY = opt.sliceY ?? Math.round((grid.ears.left.receiver[1] + grid.ears.right.receiver[1]) / 2);
  const e1 = N - sx;

  for (let t = 0; t < opt.nSteps; t++) {
    // velocities from pressure gradients (masked faces stay 0)
    for (let q = 0; q < e1; q++) {
      const pq = p[q], r = q + P;
      vX[r] = mX[q] * (vX[r] - k * (p[q + sx] - pq));
      vY[r] = mY[q] * (vY[r] - k * (p[q + sy] - pq));
      vZ[r] = mZ[q] * (vZ[r] - k * (p[q + 1] - pq));
    }
    for (let q = e1; q < N - 1; q++) {          // last x-slab: no x faces (mX = 0 there)
      const pq = p[q], r = q + P;
      if (q + sy < N) vY[r] = mY[q] * (vY[r] - k * (p[q + sy] - pq));
      vZ[r] = mZ[q] * (vZ[r] - k * (p[q + 1] - pq));
    }
    const tv = t * dt, tp = (t + 0.5) * dt;      // p holds time t; the new velocities are at t + 1/2
    for (let a = 0; a < 3; a++) {                // TF/SF: faces across the box boundary (open faces only)
      const c = corr.v[a], va = vArr[a];
      for (let m = 0; m < c.idx.length; m++) va[c.idx[m]] += c.coef[m] * inc(tv - c.delay[m]);
    }
    // pressure from velocity divergence: face q sits between cell q and q+stride
    for (let q = 0; q < N; q++) {
      const r = q + P;
      p[q] += k * (vX[r - sx] - vX[r] + vY[r - sy] - vY[r] + vZ[r - 1] - vZ[r]);
    }
    for (let m = 0; m < corr.p.idx.length; m++) p[corr.p.idx[m]] += corr.p.coef[m] * inc(tp - corr.p.delay[m]);
    for (let m = 0; m < aIdx.length; m++) p[aIdx[m]] *= aVal[m];
    out.left[t] = p[recL];
    out.right[t] = p[recR];
    if (opt.onFrame && opt.frameEvery && t % opt.frameEvery === 0 && t < (opt.frameSteps ?? Infinity)) {
      const sl = new Float32Array(nx * nz);
      for (let i = 0; i < nx; i++) for (let l = 0; l < nz; l++) sl[i * nz + l] = p[i * sx + sliceY * sy + l];
      opt.onFrame(t, sl);
    }
    if (opt.shouldStop?.()) break;
  }
  return out;
}

/** |FFT| of a real trace on `freqs` (direct DFT at the needed frequencies only). */
export function spectrumAt(trace: Float32Array, dt: number, freqs: number[]): Float64Array {
  const out = new Float64Array(freqs.length);
  freqs.forEach((f, n) => {
    const w = 2 * Math.PI * f * dt;
    let re = 0, im = 0;
    for (let t = 0; t < trace.length; t++) { re += trace[t] * Math.cos(w * t); im -= trace[t] * Math.sin(w * t); }
    out[n] = Math.hypot(re, im);
  });
  return out;
}
