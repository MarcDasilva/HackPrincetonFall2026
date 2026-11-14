// Port of backend/hornsim/wavesim.py `fdtd` (linear acoustics, staggered grid, rigid walls,
// absorbing box faces, lossy eardrum) for one click from one speaker. Pure TS: runs in a Web
// Worker in the browser and under node for checks. Units are grid cells and time steps; the
// update is the backend's, term for term.

export type EarGrid = {
  shape: [number, number, number];
  dx_mm: number;
  origin_mm: [number, number, number];
  radius_mm: number;
  canal_len_mm: number;
  eardrum_z: number;
  solid_b64: string;
  eardrum: number[];
  receiver: [number, number, number];
  canal_point_mm: [number, number, number];
  canal_axis: [number, number, number];
  canal_diameter_mm: number;
  front: [number, number, number];
  x_head_mm: number;
  left: boolean;
  ear: string;
  mesh: { verts: number[]; faces: number[] };
};

export const C_AIR = 343.0;
export const COURANT = 0.99 / Math.sqrt(3);
export const CLICK_SIGMA = 25e-6;

export function dtFor(grid: EarGrid) {
  return (COURANT * grid.dx_mm * 1e-3) / C_AIR;
}

export function decodeSolid(grid: EarGrid): Uint8Array {
  const n = grid.shape[0] * grid.shape[1] * grid.shape[2];
  const bin = typeof atob === "function" ? atob(grid.solid_b64) : Buffer.from(grid.solid_b64, "base64").toString("binary");
  const out = new Uint8Array(n);
  for (let i = 0; i < n; i++) out[i] = (bin.charCodeAt(i >> 3) >> (7 - (i & 7))) & 1; // np.packbits is MSB first
  return out;
}

/** az 0 = front, 90 = straight out from the ear, 180 = behind; el up from horizontal (wavesim.speaker_position). */
export function speakerMm(grid: EarGrid, az: number, el: number, dist = grid.radius_mm): [number, number, number] {
  const a = (az * Math.PI) / 180, e = (el * Math.PI) / 180;
  const f = grid.front, c = grid.canal_point_mm;
  const d = [
    Math.cos(e) * (Math.cos(a) * f[0] + Math.sin(a) * 1),
    Math.cos(e) * (Math.cos(a) * f[1]) + Math.sin(e),
    Math.cos(e) * (Math.cos(a) * f[2]),
  ];
  return [c[0] + dist * d[0], c[1] + dist * d[1], c[2] + dist * d[2]];
}

export function click(nSteps: number, dt: number) {
  const s = new Float32Array(nSteps);
  for (let t = 0; t < nSteps; t++) {
    const tt = t * dt - 4 * CLICK_SIGMA;
    s[t] = (-tt / CLICK_SIGMA) * Math.exp(-(tt * tt) / (2 * CLICK_SIGMA * CLICK_SIGMA));
  }
  return s;
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

/** Returns the pressure trace at the receiver for a click at grid cell `src` (array of [i,j,k] summed sources). */
export function runClick(grid: EarGrid, solid: Uint8Array, srcs: [number, number, number][], opt: FdtdOptions): Float32Array {
  const [nx, ny, nz] = grid.shape;
  const N = nx * ny * nz;
  const sy = nz, sx = ny * nz; // strides, C order (x, y, z)
  const k = COURANT;
  const p = new Float32Array(N);
  const vx = new Float32Array(N), vy = new Float32Array(N), vz = new Float32Array(N); // face (i+½) stored at i
  // open faces: only between two air cells
  const ox = new Uint8Array(N), oy = new Uint8Array(N), oz = new Uint8Array(N);
  for (let i = 0; i < nx; i++)
    for (let j = 0; j < ny; j++)
      for (let l = 0; l < nz; l++) {
        const q = i * sx + j * sy + l;
        if (solid[q]) continue;
        if (i < nx - 1 && !solid[q + sx]) ox[q] = 1;
        if (j < ny - 1 && !solid[q + sy]) oy[q] = 1;
        if (l < nz - 1 && !solid[q + 1]) oz[q] = 1;
      }
  // implicit absorption: box faces (impedance of air) and the eardrum (EARDRUM_Z × air)
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
  for (const q of grid.eardrum) loss[q] += 1 / grid.eardrum_z;
  const absorbIdx: number[] = [], absorbVal: number[] = [];
  for (let q = 0; q < N; q++) {
    if (solid[q]) continue;
    if (loss[q] > 0) { absorbIdx.push(q); absorbVal.push(1 / (1 + k * loss[q])); }
  }
  const aIdx = Int32Array.from(absorbIdx), aVal = Float32Array.from(absorbVal);
  // solid cells stay at zero pressure-change: zeroing velocities around them is enough, but the
  // backend also multiplies solid p by absorb=1, so p in solid only changes via its closed faces (= 0).
  const sig = click(opt.nSteps, dtFor(grid));
  const srcLin = srcs.map(([i, j, l]) => i * sx + j * sy + l);
  const [ri, rj, rl] = grid.receiver;
  const rec = ri * sx + rj * sy + rl;
  const trace = new Float32Array(opt.nSteps);
  const sliceY = opt.sliceY ?? rj;

  for (let t = 0; t < opt.nSteps; t++) {
    // velocities from pressure gradients
    for (let q = 0; q < N - sx; q++) if (ox[q]) vx[q] -= k * (p[q + sx] - p[q]); else vx[q] = 0;
    for (let q = 0; q < N - sy; q++) if (oy[q]) vy[q] -= k * (p[q + sy] - p[q]); else vy[q] = 0;
    for (let q = 0; q < N - 1; q++) if (oz[q]) vz[q] -= k * (p[q + 1] - p[q]); else vz[q] = 0;
    // pressure from velocity divergence (face q sits between cell q and q+stride)
    for (let q = 0; q < N - sx; q++) { const v = vx[q]; if (v) { p[q] -= k * v; p[q + sx] += k * v; } }
    for (let q = 0; q < N - sy; q++) { const v = vy[q]; if (v) { p[q] -= k * v; p[q + sy] += k * v; } }
    for (let q = 0; q < N - 1; q++) { const v = vz[q]; if (v) { p[q] -= k * v; p[q + 1] += k * v; } }
    for (const s of srcLin) p[s] += sig[t];
    for (let m = 0; m < aIdx.length; m++) p[aIdx[m]] *= aVal[m];
    trace[t] = p[rec];
    if (opt.onFrame && opt.frameEvery && t % opt.frameEvery === 0 && t < (opt.frameSteps ?? Infinity)) {
      const sl = new Float32Array(nx * nz);
      for (let i = 0; i < nx; i++) for (let l = 0; l < nz; l++) sl[i * nz + l] = p[i * sx + sliceY * sy + l];
      opt.onFrame(t, sl);
    }
    if (opt.shouldStop?.()) break;
  }
  return trace;
}

/** Cell index of a point in mm; pushed outward along +x until it is in air (wavesim does the same). */
export function toCell(grid: EarGrid, solid: Uint8Array, pmm: [number, number, number]): [number, number, number] {
  const [nx, ny, nz] = grid.shape;
  const c = pmm.map((v, a) => Math.min(grid.shape[a] - 2, Math.max(1, Math.round((v - grid.origin_mm[a]) / grid.dx_mm)))) as [number, number, number];
  while (c[0] < nx - 2 && solid[c[0] * ny * nz + c[1] * nz + c[2]]) c[0]++;
  return c;
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
