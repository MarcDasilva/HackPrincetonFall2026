"use client";
// BOTH ears from ONE head run per source (headFdtd.ts: the patient's two ears on one head). Each source direction (and
// distance, for a speaker at an ear) is one run that records both eardrums; a scene is then scored, and heard, per ear.
//
// Gain per ear, the convention hornsim/scoring.py needs (dB HL already holds the open ear's FRONTAL boost):
//   far talker   G_ear = S_ear(src) / S_ear(front)                   both plane waves, the same click
//   near speaker G_ear = [S_ear(src) / F(src)] / [S_ear(front) / C]   F: the same speaker with NO head, at that ear's
//                                                                     canal opening (a `free` run); C: the click
// so a near speaker's level_db means the free-field level it makes AT that ear (lib/lead.ts dist_mm), with the head's
// shadow on the other ear, and its 1/r, left in.
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { LeadScene } from "@/lib/lead";
import { bandGainDb } from "./bands";
import { dirKey } from "./scenes";
import type { HeadGrid, Side } from "./headFdtd";
import type { JobIn, JobOut } from "./headFdtd.worker";

const SNAP = 15;
const snap = (v: number) => Math.round(v / SNAP) * SNAP;
type Src = { az: number; el: number; dist_mm?: number };

/** A scene source's azimuth on the head: 0 front, 90 RIGHT ear, 270 LEFT ear. Scene az runs toward the aided ear. */
export const headAz = (s: { az: number }, aided: string) => (((aided === "right" ? s.az : 360 - s.az) % 360) + 360) % 360;
/** The ear a near speaker sits at: the side its azimuth points to (straight ahead or behind: the aided ear). */
export const nearSide = (az: number, aided: string): Side => (az > 0 && az < 180 ? "right" : az > 180 ? "left" : (aided as Side));
/** One head run per direction AND distance: "az,el", or "az,el@dist" (head-frame az). */
export const headKey = (s: Src, aided: string) => dirKey(snap(headAz(s, aided)) % 360, snap(s.el)) + (s.dist_mm ? `@${Math.round(s.dist_mm)}` : "");
export const parseKey = (k: string) => { const [dir, d] = k.split("@"), [az, el] = dir.split(",").map(Number); return { az, el, dist: d ? Number(d) : undefined }; };
const FRONT = "0,0";

type Done = Extract<JobOut, { type: "done" }>;
type Job = { id: number; msg: Omit<Extract<JobIn, { type: "run" }>, "type" | "job">; onFrame?: (step: number, s: Float32Array) => void; resolve: (d: Done) => void; reject: (e: Error) => void };

/** A small pool of head workers: the head grid is ~7× the ear box and a run takes seconds, so jobs queue FIFO. */
class HeadPool {
  private workers: Worker[] = []; private idle: Worker[] = []; private queue: Job[] = []; private running = new Map<Worker, Job>();
  private next = 1; private listeners = new Set<() => void>();
  constructor(grid: HeadGrid, size: number) {
    for (let i = 0; i < size; i++) {
      const w = new Worker(new URL("./headFdtd.worker.ts", import.meta.url), { type: "module" });
      w.onmessage = (e: MessageEvent<JobOut>) => {
        const m = e.data;
        if (m.type === "ready") { w.postMessage({ type: "init", grid }); this.idle.push(w); this.pump(); return; }
        const j = this.running.get(w);
        if (!j || m.job !== j.id) return;
        if (m.type === "frame") { j.onFrame?.(m.step, m.slice); return; }
        this.running.delete(w); this.idle.push(w);
        if (m.type === "done") j.resolve(m); else j.reject(new Error(m.message));
        this.pump();
      };
      this.workers.push(w);
    }
  }
  get busy() { return this.running.size; }
  get queued() { return this.queue.length; }
  subscribe(fn: () => void) { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; }
  run(msg: Job["msg"], onFrame?: Job["onFrame"]) {
    return new Promise<Done>((resolve, reject) => { this.queue.push({ id: this.next++, msg, onFrame, resolve, reject }); this.pump(); });
  }
  private pump() {
    while (this.idle.length && this.queue.length) {
      const w = this.idle.pop()!, j = this.queue.shift()!;
      this.running.set(w, j);
      w.postMessage({ type: "run", job: j.id, ...j.msg } satisfies JobIn);
    }
    this.listeners.forEach((f) => f());
  }
  dispose() { this.workers.forEach((w) => w.terminate()); for (const j of [...this.queue, ...this.running.values()]) j.reject(new Error("disposed")); this.workers = []; }
}

/** Frames of each run's horizontal slice, per key (the detail view's fields replay them). */
export class HeadFrames {
  private m = new Map<string, Float32Array[]>();
  add(k: string, s: Float32Array) { (this.m.get(k) ?? this.m.set(k, []).get(k)!).push(s); }
  reset(k: string) { this.m.set(k, []); }
  get(k: string) { return this.m.get(k); }
}

export type EarGains = { gains: (number[] | null)[]; delays: (number | null)[] };

/**
 * Every source of every scene on the head, queued once. Returns the frames (for the detail's fields), and per scene and
 * ear each source's band gain and arrival delay (s, relative to the earlier ear for that source), null until its runs land.
 */
export function useTwoEar(grid: HeadGrid | null, scenes: LeadScene[], aided: string) {
  const store = useMemo(() => new HeadFrames(), [grid]); // eslint-disable-line react-hooks/exhaustive-deps
  const [runs, setRuns] = useState<Record<string, Done>>({});
  const [every, setEvery] = useState(0);
  const [pool, setPool] = useState<HeadPool | null>(null);
  // keyed on the runs needed, NOT the scenes array (a fresh array each lead poll would restart them)
  const keys = [FRONT, ...new Set(scenes.flatMap((s) => s.sources.map((x) => headKey(x, aided))))].join(";");
  useEffect(() => {
    if (!grid) return;
    const p = new HeadPool(grid, Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 4) - 2)));
    setPool(p);
    for (const k of keys.split(";")) {
      const { az, el, dist } = parseKey(k), near = dist ? { ear: nearSide(az, aided), dist } : undefined;
      store.reset(k);
      p.run({ az, el, near }, (step, s) => { store.add(k, s); if (step > 0) setEvery((e) => e || step); }).then((d) => setRuns((r) => ({ ...r, [k]: d })), () => {});
      if (near) p.run({ az, el, near, free: true, frames: false }).then((d) => setRuns((r) => ({ ...r, [`free:${k}`]: d })), () => {});
    }
    return () => p.dispose();
  }, [grid, keys, aided, store]);
  const busy = useSyncExternalStore((fn) => pool?.subscribe(fn) ?? (() => {}), () => (pool ? pool.busy + pool.queued : 0), () => 0);

  const perScene = useMemo(() => scenes.map((s) => {
    const out: Record<Side, EarGains> = { left: { gains: [], delays: [] }, right: { gains: [], delays: [] } };
    const front = runs[FRONT];
    for (const x of s.sources) {
      const k = headKey(x, aided), r = runs[k], free = runs[`free:${k}`];
      const ok = front && r && (!x.dist_mm || free?.probe);
      const t0 = ok ? Math.min(r.onset.left, r.onset.right) : 0;
      for (const e of ["left", "right"] as Side[]) {
        if (!ok) { out[e].gains.push(null); out[e].delays.push(null); continue; }
        // near: S·C/F against S_front (see top); far: S against S_front
        const spec = x.dist_mm ? r.spectrum[e].map((v, i) => (v * r.click[i]) / Math.max(free!.probe![i], 1e-30)) : r.spectrum[e];
        out[e].gains.push(bandGainDb(spec, front.spectrum[e]));
        out[e].delays.push(r.onset[e] - t0);
      }
    }
    return out;
  }), [runs, scenes, aided]);

  const need = keys.split(";").length + keys.split(";").filter((k) => k.includes("@")).length;   // every run + a free run per near key
  /** Eardrum level of a scene per ear, dB re its frontal far talker at 65 dB — the head's shadow in one number. */
  const eardrum = (scene: LeadScene, ear: Side) => {
    let t = 0;
    for (const x of scene.sources) { const g = perScene[scenes.indexOf(scene)]?.[ear].gains[scene.sources.indexOf(x)]; if (!g) return null; t += 10 ** ((x.level_db - 65) / 10) * g.reduce((a, v) => a + 10 ** (v / 10), 0) / g.length; }
    return 10 * Math.log10(t || 1e-30);
  };
  return { store, every, perScene, busy, done: Object.keys(runs).length, need, eardrum };
}
