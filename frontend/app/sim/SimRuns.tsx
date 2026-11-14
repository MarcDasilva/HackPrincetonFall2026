"use client";
// The lead's simulations inside the orb: one tile per scene, every speaker direction one FDTD run in
// the worker pool (SimGrid's machinery), up to 100 scenes. Tiles draw their pressure slice on a 2D
// canvas, NEVER WebGL — Chrome keeps ~16 WebGL contexts per page and drops the oldest, so 100 3D
// cells would kill the dashboard's metal rings. A tile animates ONLY while it is on screen.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { LeadScene, SimResult } from "@/lib/lead";
import { fetchGrid, type GridWithPatient } from "./lib/api";
import { bandGainDb } from "./lib/bands";
import { decodeSolid } from "./lib/fdtd";
import { sceneDeficit, toAudiogram } from "./lib/hearing";
import { SimPool } from "./lib/pool";
import { dirKey } from "./lib/scenes";
import { FrameStore } from "./SimGrid";

// ponytail: directions snap to 15° so scenes share runs — 100 scenes cost at most 13×10 runs (~1 MB of frames each); finer steps if a scene needs them.
const SNAP = 15;
const snap = (v: number) => Math.round(v / SNAP) * SNAP;
const keyOf = (s: { az: number; el: number }) => dirKey(snap(s.az), snap(s.el));
const REF = dirKey(0, 0);

export type Outcome = { results: SimResult[]; audiogram_db_hl: Record<string, number>; aided?: (number | undefined)[] };

type Props = {
  pid: string;
  ear?: string | null;
  scenes: LeadScene[];
  /** The picked design's insertion gain per SII band: tiles then show aided vs unaided (the validation). */
  gain?: number[];
  /** Fires once every scene has its result, and again whenever `gain` changes the aided numbers. */
  onDone: (o: Outcome) => void;
};

export default function SimRuns({ pid, ear, scenes, gain, onDone }: Props) {
  const [grid, setGrid] = useState<GridWithPatient | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [spectra, setSpectra] = useState<Record<string, number[]>>({});
  const store = useMemo(() => new FrameStore(), []);
  const [pool, setPool] = useState<SimPool | null>(null);

  useEffect(() => {
    fetchGrid(pid, ear ?? undefined).then(setGrid, (e: Error) => setErr(e.message));
  }, [pid, ear]);
  // Keyed on the directions, NOT the scenes array: every lead poll brings a fresh array, and a new pool would restart every run.
  const dirs = [REF, ...new Set(scenes.flatMap((s) => s.sources.map(keyOf)))].join(";");
  useEffect(() => {
    if (!grid) return;
    const p = new SimPool(grid, Math.max(1, Math.min(8, (navigator.hardwareConcurrency || 4) - 1)));
    setPool(p);
    // Every direction queued at once, FIFO: the pool works through them whether or not the orb is open.
    for (const k of dirs.split(";")) {
      const [a, e] = k.split(",").map(Number);
      store.reset(k);
      p.run("lead", a, e, (_, slice) => store.add(k, slice)).then((sp) => setSpectra((s) => ({ ...s, [k]: sp })), () => {});
    }
    return () => p.dispose();
  }, [grid, dirs, store]);
  const busy = useSyncExternalStore(
    (fn) => pool?.subscribe(fn) ?? (() => {}),
    () => (pool ? pool.busy : 0),
    () => 0,
  );

  const audiogram = grid?.patient?.audiogram_db_hl;
  const results = useMemo(() => {
    const ref = spectra[REF];
    if (!ref || !audiogram) return scenes.map(() => null);
    const ag = toAudiogram(audiogram);
    return scenes.map((s) => {
      const srcs = s.sources.map((x) => (spectra[keyOf(x)] ? { role: x.role, az: x.az, el: x.el, levelDb: x.level_db, gainDb: bandGainDb(spectra[keyOf(x)], ref) } : null));
      return srcs.every(Boolean) ? sceneDeficit(srcs as NonNullable<(typeof srcs)[number]>[], ag, gain) : null;
    });
  }, [spectra, scenes, audiogram, gain]);
  const done = results.filter(Boolean).length;

  const report = useRef(onDone);
  report.current = onDone;
  const sent = useRef<string>("");
  useEffect(() => {
    if (!audiogram || done < scenes.length) return;
    const tag = `${scenes.length}:${gain?.join(",") ?? ""}`;
    if (sent.current === tag) return;
    sent.current = tag;
    report.current({
      audiogram_db_hl: audiogram,
      results: scenes.map((s, i) => ({ id: s.id, name: s.name, weight: s.weight, sii_healthy: results[i]!.siiHealthy, sii_unaided: results[i]!.siiUnaided, deficit_db: results[i]!.deficit, deficit_weighted: results[i]!.deficitWeighted })),
      aided: gain ? results.map((r) => r?.siiAided) : undefined,
    });
  }, [done, scenes, results, audiogram, gain]);

  if (err) return <p data-testid="sim-runs-error" style={{ color: "#f87171", padding: 24 }}>Could not load this ear for simulation: {err}</p>;
  if (!grid) return <p style={{ color: "#9aa0a8", padding: 24 }}>Loading your ear…</p>;
  return (
    <div data-testid="sim-runs" style={{ padding: "0 24px 24px" }}>
      <header style={{ display: "flex", gap: 16, alignItems: "baseline", color: "#c3c2b7", margin: "4px 0 16px 48px" }}>
        <h2 style={{ margin: 0, fontSize: 18, color: "#f0efec", fontWeight: 500 }}>{gain ? "Validating your aid" : "Simulations"}</h2>
        <span data-testid="sim-progress" style={{ fontVariantNumeric: "tabular-nums" }}>{done} of {scenes.length} done · {busy} running</span>
        <span style={{ color: "#8f8e86", fontSize: 13 }}>Share of speech heard: normal hearing / you{gain ? " → with the aid" : ""}</span>
      </header>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
        {scenes.map((s, i) => (
          <Tile key={s.id} grid={grid} scene={s} store={store} result={results[i]} running={!results[i] && s.sources.some((x) => !spectra[keyOf(x)])} />
        ))}
      </div>
    </div>
  );
}

type Res = ReturnType<typeof sceneDeficit>;

function Tile({ grid, scene, store, result, running }: { grid: GridWithPatient; scene: LeadScene; store: FrameStore; result: Res; running: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const solid = useMemo(() => decodeSolid(grid), [grid]);
  useEffect(() => {
    const c = canvas.current!;
    const [nx, ny, nz] = grid.shape;
    const ctx = c.getContext("2d")!;
    const img = ctx.createImageData(nx, nz);
    const sum = new Float32Array(nx * nz);
    let raf = 0, frame = 0, last = 0, peak = 1e-6;
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (now - last < 40) return;
      last = now;
      // Linear acoustics: the scene's field is each source's field, scaled by its level.
      const runs = scene.sources.map((s) => ({ f: store.get(keyOf(s)), a: 10 ** ((s.level_db - 65) / 20) })).filter((r) => r.f?.length);
      if (!runs.length) return;
      const len = Math.max(...runs.map((r) => r.f!.length));
      frame = (frame + 1) % (len + 20);
      sum.fill(0);
      if (frame < len) for (const r of runs) { const sl = r.f![Math.min(frame, r.f!.length - 1)]; for (let k = 0; k < sum.length; k++) sum[k] += r.a * sl[k]; }
      let m = 0;
      for (let k = 0; k < sum.length; k++) m = Math.max(m, Math.abs(sum[k]));
      peak = Math.max(peak * 0.9, m, 1e-6);
      for (let i = 0; i < nx; i++) for (let l = 0; l < nz; l++) {
        const v = sum[i * nz + l] / peak, o = (l * nx + i) * 4;
        if (solid[i * ny * nz + grid.receiver[1] * nz + l]) { img.data.set([60, 62, 68, 255], o); continue; }
        const a = Math.min(1, Math.abs(v) * 1.6);
        img.data.set(v >= 0 ? [Math.round(235 * a), Math.round(104 * a), Math.round(52 * a), 255] : [Math.round(57 * a), Math.round(135 * a), Math.round(229 * a), 255], o);
      }
      ctx.putImageData(img, 0, 0);
    };
    // Only while on screen: 100 tiles animating at once would starve the workers' main-thread messages.
    const io = new IntersectionObserver(([e]) => {
      cancelAnimationFrame(raf);
      if (e.isIntersecting) raf = requestAnimationFrame(draw);
    });
    io.observe(c);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [grid, scene, store, solid]);

  const pct = (v?: number) => (v === undefined ? "–" : `${Math.round(v * 100)}%`);
  const where = scene.sources.map((s) => `${s.role} ${s.az}° ${s.level_db} dB`).join(", ");
  return (
    <figure data-testid="sim-tile" data-done={!!result || undefined} title={`${scene.why}\n${where}`}
      style={{ margin: 0, padding: 10, borderRadius: 12, background: "#1a1a19", border: "1px solid #3a3a38", color: "#c3c2b7", fontSize: 13 }}>
      <figcaption style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
        <span style={{ color: "#f0efec", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{scene.name}</span>
        <span style={{ flex: "none", color: result ? "#8f8e86" : running ? "#7aa2ff" : "#5c5f66" }}>{result ? "done" : running ? "running" : "queued"}</span>
      </figcaption>
      <canvas ref={canvas} width={grid.shape[0]} height={grid.shape[2]} style={{ width: "100%", aspectRatio: "1", imageRendering: "pixelated", borderRadius: 8, background: "#000", display: "block" }} />
      <div style={{ marginTop: 6, color: "#8f8e86", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{scene.sound} · {where}</div>
      <div data-testid="sim-sii" style={{ marginTop: 2, fontVariantNumeric: "tabular-nums" }}>
        {pct(result?.siiHealthy)} / {pct(result?.siiUnaided)}{result?.siiAided !== undefined && <> → <b style={{ color: result.siiAided > result.siiUnaided ? "#8fd18f" : "#f0efec" }}>{pct(result.siiAided)}</b></>}
      </div>
    </figure>
  );
}
