/// <reference lib="webworker" />
// One FDTD run per message: a far talker's plane click on the dummy head, both eardrums recorded.
// A run is synchronous (~6 s), so a stale job finishes and the caller drops its result by job id.
import { bandFreqs } from "./bands";
import { arrivalDir, CLICK_SIGMA, decodeSolid, dtFor, nearEarCell, runPlaneWave, spectrumAt, type HeadGrid, type Side } from "./headFdtd";

export const RUN_MS = 5;        // eardrum responses have died down: 5 ms is within 0.7 dB of 8.5 ms in every band
export const FRAME_MS = 1.4;    // frames cover the wave crossing the box and the first reflections
export const N_FRAMES = 90;

/** `near`: a point speaker `dist` mm from that ear instead of a far talker. `free`: the SAME speaker with no head or ears
 * (an empty grid), recording only the pressure at that ear's canal opening — the free-field level there, which calibrates
 * a near speaker the way the plane wave's own amplitude calibrates a far one (lib/twoEar.ts). */
export type JobIn = { type: "init"; grid: HeadGrid } | { type: "run"; job: number; az: number; el: number; near?: { ear: Side; dist: number }; free?: boolean; frames?: boolean };
export type JobOut =
  | { type: "frame"; job: number; step: number; slice: Float32Array }
  /** spectrum: |eardrum| on bands.bandFreqs; click: |the click| on the same frequencies; onset: s until each eardrum
   *  trace first reaches 20% of its peak (their difference is the ITD); probe: |free field at the ear| for `free` runs. */
  | { type: "done"; job: number; spectrum: Record<Side, number[]>; click: number[]; onset: Record<Side, number>; probe?: number[]; ms: number }
  | { type: "ready" }
  | { type: "error"; job: number; message: string };

let grid: HeadGrid | null = null;
let solid: Uint8Array | null = null;
let empty: Uint8Array | null = null;
const onsetOf = (tr: Float32Array, dt: number) => {
  let m = 0;
  for (let i = 0; i < tr.length; i++) m = Math.max(m, Math.abs(tr[i]));
  for (let i = 0; i < tr.length; i++) if (Math.abs(tr[i]) >= 0.2 * m) return i * dt;
  return 0;
};

self.onmessage = (e: MessageEvent<JobIn>) => {
  const m = e.data;
  if (m.type === "init") {
    grid = m.grid;
    solid = decodeSolid(m.grid);
    return;
  }
  if (!grid || !solid) { self.postMessage({ type: "error", job: m.job, message: "worker has no grid" } satisfies JobOut); return; }
  try {
    const t0 = performance.now();
    const dt = dtFor(grid);
    const frameSteps = Math.round((FRAME_MS * 1e-3) / dt);
    const nSteps = Math.round((RUN_MS * 1e-3) / dt);
    // the speaker cell is found against the REAL head either way, so the free run's speaker sits where the real one does
    const point = m.near ? nearEarCell(grid, solid, m.near.ear, m.az, m.el, m.near.dist) : undefined;
    const g = grid, round = (v: number, a: number) => Math.round((v - g.origin_mm[a]) / g.dx_mm);
    const probe = m.free && m.near ? (g.ears[m.near.ear].canal_point_mm.map(round) as [number, number, number]) : undefined;
    const tr = runPlaneWave(grid, m.free ? (empty ??= new Uint8Array(solid.length)) : solid, arrivalDir(grid, m.az, m.el), {
      nSteps,
      frameEvery: m.frames === false ? undefined : Math.max(1, Math.round(frameSteps / N_FRAMES)),
      frameSteps,
      onFrame: m.frames === false ? undefined : (step, slice) => (self as unknown as Worker).postMessage({ type: "frame", job: m.job, step, slice } satisfies JobOut, [slice.buffer]),
      point, probe,
    });
    const f = bandFreqs();
    const spectrum = { left: Array.from(spectrumAt(tr.left, dt, f)), right: Array.from(spectrumAt(tr.right, dt, f)) };
    // the click the run was driven with (headFdtd.ts clickTable): a plane wave's incident pressure IS this click
    const c = new Float32Array(nSteps);
    for (let t = 0; t < nSteps; t++) { const tt = t * dt - 4 * CLICK_SIGMA; c[t] = (-tt / CLICK_SIGMA) * Math.exp(-(tt * tt) / (2 * CLICK_SIGMA * CLICK_SIGMA)); }
    self.postMessage({ type: "done", job: m.job, spectrum, click: Array.from(spectrumAt(c, dt, f)), onset: { left: onsetOf(tr.left, dt), right: onsetOf(tr.right, dt) },
      probe: tr.probe ? Array.from(spectrumAt(tr.probe, dt, f)) : undefined, ms: performance.now() - t0 } satisfies JobOut);
  } catch (err) {
    self.postMessage({ type: "error", job: m.job, message: String((err as Error).message ?? err) } satisfies JobOut);
  }
};

// the bundler may load this module after the page posts its first message, which would then be
// dropped; announce readiness so the pool sends nothing earlier
self.postMessage({ type: "ready" } satisfies JobOut);
