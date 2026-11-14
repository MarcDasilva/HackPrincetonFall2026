/// <reference lib="webworker" />
// One FDTD run per message: a far talker's plane click on the dummy head, both eardrums recorded.
// A run is synchronous (~6 s), so a stale job finishes and the caller drops its result by job id.
import { bandFreqs } from "./bands";
import { arrivalDir, decodeSolid, dtFor, runPlaneWave, spectrumAt, type HeadGrid, type Side } from "./fdtd";
import { transfer, type EarTF } from "./binaural";

export const RUN_MS = 5;        // eardrum responses have died down: 5 ms is within 0.7 dB of 8.5 ms in every band
export const FRAME_MS = 1.4;    // frames cover the wave crossing the box and the first reflections
export const N_FRAMES = 90;

export type JobIn = { type: "init"; grid: HeadGrid } | { type: "run"; job: number; az: number; el: number };
export type JobOut =
  | { type: "frame"; job: number; step: number; slice: Float32Array }
  | { type: "done"; job: number; spectrum: Record<Side, number[]>; tf: EarTF; ms: number }
  | { type: "ready" }
  | { type: "error"; job: number; message: string };

let grid: HeadGrid | null = null;
let solid: Uint8Array | null = null;

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
    const tr = runPlaneWave(grid, solid, arrivalDir(grid, m.az, m.el), {
      nSteps: Math.round((RUN_MS * 1e-3) / dt),
      frameEvery: Math.max(1, Math.round(frameSteps / N_FRAMES)),
      frameSteps,
      onFrame: (step, slice) => (self as unknown as Worker).postMessage({ type: "frame", job: m.job, step, slice } satisfies JobOut, [slice.buffer]),
    });
    const f = bandFreqs();
    const spectrum = { left: Array.from(spectrumAt(tr.left, dt, f)), right: Array.from(spectrumAt(tr.right, dt, f)) };
    const tf = { left: transfer(tr.left, dt), right: transfer(tr.right, dt) };
    self.postMessage({ type: "done", job: m.job, spectrum, tf, ms: performance.now() - t0 } satisfies JobOut);
  } catch (err) {
    self.postMessage({ type: "error", job: m.job, message: String((err as Error).message ?? err) } satisfies JobOut);
  }
};

// the bundler may load this module after the page posts its first message, which would then be
// dropped; announce readiness so the pool sends nothing earlier
self.postMessage({ type: "ready" } satisfies JobOut);

