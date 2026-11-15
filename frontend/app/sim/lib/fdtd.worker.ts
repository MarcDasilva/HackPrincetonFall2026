/// <reference lib="webworker" />
// One FDTD run per message. A run is synchronous (~2 s), so a stale job finishes and the caller
// drops its result by job id.
import { bandFreqs } from "./bands";
import { decodeSolid, dtFor, runClick, speakerMm, spectrumAt, toCell, type EarGrid } from "./fdtd";

export type JobIn = { type: "init"; grid: EarGrid } | { type: "run"; job: number; az: number; el: number; nSteps: number; frameEvery: number; frameSteps: number; dist?: number };
export type JobOut =
  | { type: "frame"; job: number; step: number; slice: Float32Array }
  | { type: "done"; job: number; spectrum: number[]; ms: number }
  | { type: "ready" }
  | { type: "error"; job: number; message: string };

let grid: EarGrid | null = null;
let solid: Uint8Array | null = null;

self.onmessage = (e: MessageEvent<JobIn>) => {
  const m = e.data;
  if (m.type === "init") {
    grid = m.grid;
    solid = decodeSolid(m.grid);
    return;
  }
  if (!grid || !solid) { self.postMessage({ type: "error", job: m.job, message: "worker has no grid" } satisfies JobOut); return; }
  const t0 = performance.now();
  const src = toCell(grid, solid, speakerMm(grid, m.az, m.el, m.dist));
  const trace = runClick(grid, solid, [src], {
    nSteps: m.nSteps,
    frameEvery: m.frameEvery,
    frameSteps: m.frameSteps,
    onFrame: (step, slice) => (self as unknown as Worker).postMessage({ type: "frame", job: m.job, step, slice } satisfies JobOut, [slice.buffer]),
  });
  const spectrum = Array.from(spectrumAt(trace, dtFor(grid), bandFreqs()));
  self.postMessage({ type: "done", job: m.job, spectrum, ms: performance.now() - t0 } satisfies JobOut);
};

// the bundler may load this module after the page posts its first message, which would then be
// dropped; announce readiness so the pool sends nothing earlier
self.postMessage({ type: "ready" } satisfies JobOut);
