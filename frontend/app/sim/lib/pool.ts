"use client";
// A small Web Worker pool for FDTD runs. Jobs queue FIFO; each finished run resolves its promise,
// and its frames stream to the job's onFrame. `cancel(owner)` drops queued jobs of one scene cell
// (a run already in a worker finishes and its result is ignored by the caller).
import type { EarGrid } from "./fdtd";
import type { JobOut } from "./fdtd.worker";

export const N_STEPS = 2048;      // 8.5 ms at 2.5 mm: the eardrum ring has died down well before
export const FRAME_EVERY = 4;       // frames cover the first FRAME_STEPS: the pulse crossing the box
export const FRAME_STEPS = 480;

type Job = {
  id: number; owner: string; az: number; el: number; dist?: number;
  onFrame?: (step: number, slice: Float32Array) => void;
  resolve: (spectrum: number[]) => void; reject: (e: Error) => void;
};

export class SimPool {
  private workers: Worker[] = [];
  private idle: Worker[] = [];
  private queue: Job[] = [];
  private running = new Map<Worker, Job>();
  private nextId = 1;
  private listeners = new Set<() => void>();

  constructor(grid: EarGrid, size: number) {
    for (let i = 0; i < size; i++) {
      const w = new Worker(new URL("./fdtd.worker.ts", import.meta.url), { type: "module" });
      w.onmessage = (e: MessageEvent<JobOut>) => {
        if (e.data.type === "ready") { w.postMessage({ type: "init", grid }); this.idle.push(w); this.pump(); return; }
        this.onMessage(w, e.data);
      };
      w.onerror = (e) => { const j = this.running.get(w); this.running.delete(w); this.idle.push(w); j?.reject(new Error(e.message)); this.pump(); };
      this.workers.push(w);
    }
  }

  get size() { return this.workers.length; }
  get busy() { return this.running.size; }
  get queued() { return this.queue.length; }
  subscribe(fn: () => void) { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; }
  private emit() { this.listeners.forEach((f) => f()); }

  /** `dist` (mm from the canal opening) moves the speaker in from the grid's radius: a source touching the ear. */
  run(owner: string, az: number, el: number, onFrame?: Job["onFrame"], dist?: number): Promise<number[]> {
    return new Promise((resolve, reject) => {
      this.queue.push({ id: this.nextId++, owner, az, el, dist, onFrame, resolve, reject });
      this.pump();
    });
  }

  cancel(owner: string) {
    const keep: Job[] = [];
    for (const j of this.queue) (j.owner === owner ? j.reject(new Error("cancelled")) : keep.push(j));
    this.queue = keep;
    this.emit();
  }

  private pump() {
    while (this.idle.length && this.queue.length) {
      const w = this.idle.pop()!, j = this.queue.shift()!;
      this.running.set(w, j);
      w.postMessage({ type: "run", job: j.id, az: j.az, el: j.el, dist: j.dist, nSteps: N_STEPS, frameEvery: FRAME_EVERY, frameSteps: FRAME_STEPS });
    }
    this.emit();
  }

  private onMessage(w: Worker, m: JobOut) {
    const j = this.running.get(w);
    if (!j || m.type === "ready" || m.job !== j.id) return;
    if (m.type === "frame") { j.onFrame?.(m.step, m.slice); return; }
    this.running.delete(w);
    this.idle.push(w);
    if (m.type === "done") j.resolve(m.spectrum);
    else if (m.type === "error") j.reject(new Error(m.message));
    this.pump();
  }

  dispose() {
    this.workers.forEach((w) => w.terminate());
    for (const j of [...this.queue, ...this.running.values()]) j.reject(new Error("disposed"));
    this.workers = []; this.idle = []; this.queue = []; this.running.clear();
  }
}
