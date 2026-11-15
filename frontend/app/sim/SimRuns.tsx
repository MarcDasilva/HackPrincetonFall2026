"use client";
// The lead's simulations inside the orb: one tile per scene, every speaker direction one FDTD run in
// the worker pool (SimGrid's machinery), up to 100 scenes. Tiles draw their pressure slice on a 2D
// canvas, NEVER WebGL — Chrome keeps ~16 WebGL contexts per page and drops the oldest, so 100 3D
// cells would kill the dashboard's metal rings. A tile animates ONLY while it is on screen.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { LeadScene, SimResult } from "@/lib/lead";
import { fetchGrid, type GridWithPatient } from "./lib/api";
import { bandGainDb } from "./lib/bands";
import { decodeSolid, dtFor } from "./lib/fdtd";
import { API } from "@/lib/run";
import { SII_FREQS, sceneDeficit, toAudiogram } from "./lib/hearing";
import { SimPool } from "./lib/pool";
import { dirKey } from "./lib/scenes";
import { FrameStore } from "./SimGrid";
import { DEFAULT_VIEW, snapHead, type View } from "./HeadSnap";

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
  /** The ear grid already in hand (a preview without the sim backend); fetched from it otherwise. */
  grid?: GridWithPatient;
};

export default function SimRuns({ pid, ear, scenes, gain, onDone, grid: given }: Props) {
  const [grid, setGrid] = useState<GridWithPatient | null>(given ?? null);
  const [err, setErr] = useState<string | null>(null);
  const [spectra, setSpectra] = useState<Record<string, number[]>>({});
  const store = useMemo(() => new FrameStore(), []);
  const [open, setOpen] = useState<number | null>(null);
  const [pool, setPool] = useState<SimPool | null>(null);

  useEffect(() => {
    if (given) return;
    fetchGrid(pid, ear ?? undefined).then(setGrid, (e: Error) => setErr(e.message));
  }, [pid, ear, given]);
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

  if (err) return <p data-testid="sim-runs-error" style={{ color: "#b42318", padding: 24 }}>Could not load this ear for simulation: {err}</p>;
  if (!grid) return <p style={{ color: L.muted, padding: 24 }}>Loading…</p>;
  const status = (i: number) => (results[i] ? "done" : scenes[i].sources.some((x) => !spectra[keyOf(x)]) ? "running" : "queued");
  const side = ear ?? grid.patient?.side ?? (grid.left ? "left" : "right");
  if (open !== null && scenes[open]) return <Detail pid={pid} side={side} grid={grid} scene={scenes[open]} store={store} result={results[open]} status={status(open)} gain={gain} onBack={() => setOpen(null)} />;
  return (
    <div data-testid="sim-runs" style={{ ...PAGE, padding: "0 32px 40px" }}>
      <header style={{ display: "flex", gap: 12, alignItems: "baseline", margin: "6px 0 28px 52px" }}>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>{gain ? "Validation" : "Simulations"}</h2>
        <span data-testid="sim-progress" style={{ color: L.muted, fontSize: 13, fontVariantNumeric: "tabular-nums" }}>{done === scenes.length ? `${done}` : `${done} of ${scenes.length} done · ${busy} running`}</span>
      </header>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "32px 24px" }}>
        {scenes.map((s, i) => (
          <Tile key={s.id} pid={pid} left={grid.left} scene={s} result={results[i]} status={status(i)} onOpen={() => setOpen(i)} />
        ))}
      </div>
    </div>
  );
}

type Res = ReturnType<typeof sceneDeficit>;
type Status = "done" | "running" | "queued";
/** Black on white, ONE grey for everything secondary. Colour stays ONLY in the wave fields, where it is data. */
const L = { ink: "#111111", muted: "#8a8a8a", hair: "#ededed", paper: "#ffffff" };
const PAGE: React.CSSProperties = { background: L.paper, color: L.ink, minHeight: "100%", fontFamily: "Inter, system-ui, -apple-system, sans-serif" };
const pct = (v?: number) => (v === undefined ? "–" : `${Math.round(v * 100)}%`);
const label: React.CSSProperties = { fontSize: 12, color: L.muted, margin: "0 0 8px" };

/** Speech heard as the patient hears it: unaided, then with the aid when there is one. Normal hearing rides in the tooltip. */
function Sii({ result, big }: { result: Res; big?: boolean }) {
  return (
    <span data-testid="sim-sii" title={`Normal hearing ${pct(result?.siiHealthy)}`} style={{ fontSize: big ? 28 : 13, fontVariantNumeric: "tabular-nums", letterSpacing: big ? "-0.01em" : undefined }}>
      {pct(result?.siiUnaided)}{result?.siiAided !== undefined && <span style={{ color: L.muted }}> → <span style={{ color: L.ink }}>{pct(result.siiAided)}</span></span>}
    </span>
  );
}

/**
 * The overview: the scene as a measurement rig. Drag turns it and the wheel zooms — each move re-draws the tile through
 * HeadSnap's ONE shared renderer, so a tile never holds a WebGL context of its own. A click without a drag opens the scene.
 */
function Tile({ pid, left, scene, result, status, onOpen }: { pid: string; left: boolean; scene: LeadScene; result: Res; status: Status; onOpen: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<View>({ ...DEFAULT_VIEW });
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const frame = useRef(0);
  const draw = () => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => void snapHead(pid, left, scene.sources, canvas.current!, view.current));
  };
  useEffect(() => { draw(); return () => cancelAnimationFrame(frame.current); }, [pid, left, scene]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // Non-passive, or the page scrolls instead of the rig zooming.
    const c = canvas.current!;
    const wheel = (e: WheelEvent) => { e.preventDefault(); view.current.zoom = Math.min(4, Math.max(0.6, view.current.zoom * Math.exp(-e.deltaY * 0.0015))); draw(); };
    c.addEventListener("wheel", wheel, { passive: false });
    return () => c.removeEventListener("wheel", wheel);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  const down = (e: React.PointerEvent) => { drag.current = { x: e.clientX, y: e.clientY, moved: false }; (e.target as Element).setPointerCapture(e.pointerId); };
  const move = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true;
    view.current.yaw -= dx * 0.5;
    view.current.pitch += dy * 0.3;
    d.x = e.clientX; d.y = e.clientY;
    draw();
  };
  const up = () => { const d = drag.current; drag.current = null; if (d && !d.moved) onOpen(); };
  return (
    <figure data-testid="sim-tile" data-done={!!result || undefined} title={scene.why}
      role="button" tabIndex={0} aria-label={`Open ${scene.name}`} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen())}
      className="sim-tile" style={{ margin: 0 }}>
      <style>{`.sim-tile:focus-visible{outline:none}.sim-tile:focus-visible canvas{opacity:.75}`}</style>
      <canvas ref={canvas} width={560} height={400} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => { drag.current = null; }}
        style={{ width: "100%", aspectRatio: "7 / 5", display: "block", opacity: result ? 1 : 0.45, cursor: "grab", touchAction: "none" }} />
      <figcaption onClick={onOpen} style={{ display: "flex", justifyContent: "space-between", gap: 12, marginTop: 10, fontSize: 13, cursor: "pointer" }}>
        <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{scene.name}</span>
        {result ? <Sii result={result} /> : <span style={{ color: L.muted }}>{status}</span>}
      </figcaption>
    </figure>
  );
}

/** The scene's live pressure field, top-down through the canal opening: the level-weighted sum of its sources' runs (linear acoustics). Red/blue match the wave viewers. */
function Slice({ grid, scene, store }: { grid: GridWithPatient; scene: LeadScene; store: FrameStore }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const solid = useMemo(() => decodeSolid(grid), [grid]);
  useEffect(() => {
    const c = canvas.current!;
    const [nx, ny, nz] = grid.shape;
    const ctx = c.getContext("2d")!;
    const img = ctx.createImageData(nx, nz);
    const sum = new Float32Array(nx * nz);
    const POS = [200, 65, 58], NEG = [47, 95, 208];
    let raf = 0, frame = 0, last = 0, peak = 1e-6;
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (now - last < 40) return;
      last = now;
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
        if (solid[i * ny * nz + grid.receiver[1] * nz + l]) { img.data.set([201, 196, 188, 255], o); continue; }
        const a = Math.min(1, Math.abs(v) * 1.6), c0 = v >= 0 ? POS : NEG;
        img.data.set([255 - (255 - c0[0]) * a, 255 - (255 - c0[1]) * a, 255 - (255 - c0[2]) * a, 255], o);
      }
      ctx.putImageData(img, 0, 0);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [grid, scene, store, solid]);
  return <canvas ref={canvas} data-testid="sim-slice" width={grid.shape[0]} height={grid.shape[2]} style={{ width: "100%", aspectRatio: "1", imageRendering: "pixelated", borderRadius: 10, display: "block" }} />;
}

/** The backend's wave runs are five fixed directions in the ear plane; the viewers show the one nearest the scene's main source. */
const RUN_AZ = [0, 45, 90, 135, 180];
function nearestRun(scene: LeadScene) {
  const main = scene.sources.find((s) => s.role === "talker") ?? scene.sources[0];
  // Fold to 0–180: the runs cover one side, and a source at 200° is the mirror of one at 160°.
  const a = ((main.az % 360) + 360) % 360, az = a > 180 ? 360 - a : a;
  const near = RUN_AZ.reduce((b, a) => (Math.abs(a - az) < Math.abs(b - az) ? a : b));
  return { az: near, tag: `az${String(near).padStart(3, "0")}_el+00`, main };
}

/** One simulation opened: the head's 3D field and the ear's slices side by side, the live pixel field below, the numbers beside them. */
function Detail({ pid, side, grid, scene, store, result, status, gain, onBack }: { pid: string; side: string; grid: GridWithPatient; scene: LeadScene; store: FrameStore; result: Res; status: Status; gain?: number[]; onBack: () => void }) {
  const ag = grid.patient?.audiogram_db_hl ?? {};
  const [nx, ny, nz] = grid.shape;
  const frames = Math.max(0, ...scene.sources.map((s) => store.get(keyOf(s))?.length ?? 0));
  const run = nearestRun(scene);
  // The tag rides URL-encoded: a raw "+" in "el+00" arrives as a space and the viewers fall back to their default direction (WaveBento).
  const q = `embed=1&run=${encodeURIComponent(run.tag)}`;
  const view: React.CSSProperties = { width: "100%", height: 420, border: 0, borderRadius: 10, display: "block", background: "#fbfaf8" };
  const kv = (k: string, v: React.ReactNode) => <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "3px 0" }}><span style={{ color: L.muted }}>{k}</span><span style={{ fontVariantNumeric: "tabular-nums" }}>{v}</span></div>;
  return (
    <div data-testid="sim-detail" style={{ ...PAGE, padding: "0 32px 40px" }}>
      <header style={{ display: "flex", gap: 14, alignItems: "center", margin: "0 0 24px 52px", minHeight: 40 }}>
        <button type="button" aria-label="All simulations" onClick={onBack} style={{ border: 0, background: "none", color: L.muted, cursor: "pointer", fontSize: 18, padding: 0, lineHeight: 1 }}>←</button>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>{scene.name}</h2>
        {status !== "done" && <span style={{ color: L.muted, fontSize: 13 }}>{status}</span>}
      </header>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 260px", gap: 40, alignItems: "start" }}>
        <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 28 }}>
          {/* Side by side: the head's 3D field (the SAME rig as the thumbnails, via the viewer's ?rig=1) and the ear's 2D slices for that direction. */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
            <figure style={{ margin: 0 }}>
              <iframe data-testid="sim-3d" title="3D wave field on the head" src={`${API}/api/patients/${pid}/head/viewer.html?${q}&rig=1&ear=${side}`} style={view} />
            </figure>
            <figure style={{ margin: 0 }}>
              <iframe data-testid="sim-2d-lab" title="2D wave slices" src={`${API}/api/patients/${pid}/waves/${side}/index.html?${q}&disp=slices`} style={view} />
            </figure>
          </div>
          <figure style={{ margin: 0, maxWidth: 340 }}>
            <Slice grid={grid} scene={scene} store={store} />
          </figure>
        </div>
        <aside data-testid="sim-info" style={{ fontSize: 13, position: "sticky", top: 16, maxHeight: "calc(100vh - 32px)", overflowY: "auto", scrollbarWidth: "none" }}>
          <p style={label}>Speech heard</p>
          <Sii result={result} big />
          <p style={{ ...label, marginTop: 28 }}>{scene.sound}</p>
          {scene.sources.map((s, i) => kv(s.role, `${s.az}° · ${s.level_db} dB`))}
          {/* Everything known about the run, ALWAYS shown: plain label/value rows, no boxes. */}
          <div style={{ marginTop: 28, display: "flex", flexDirection: "column", gap: 24 }}>
              <p style={{ margin: 0, color: L.muted, lineHeight: 1.5 }}>{scene.why}</p>
              <div>
                {kv("Normal hearing", pct(result?.siiHealthy))}
                {kv("You", pct(result?.siiUnaided))}
                {gain && kv("With the aid", pct(result?.siiAided))}
                {kv("Scene weight", scene.weight)}
              </div>
              {result && (
                <div data-testid="sim-deficit">
                  <p style={label}>Hearing lost, dB</p>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "6px 4px", fontSize: 11, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>
                    {SII_FREQS.map((f, i) => <div key={f}><div style={{ color: L.muted }}>{f >= 1000 ? `${f / 1000}k` : f}</div><div>{Math.round(result.deficit[i])}</div></div>)}
                  </div>
                </div>
              )}
              <div>
                <p style={label}>Hearing test, dB HL{grid.patient?.audiogram_is_example ? " (example)" : ""}</p>
                {Object.entries(ag).map(([f, v]) => kv(Number(f) >= 1000 ? `${Number(f) / 1000} kHz` : `${f} Hz`, v))}
              </div>
              <div>
                <p style={label}>Method</p>
                {kv("Ear", grid.left ? "Left" : "Right")}
                {kv("Wave run shown", `${run.az}°`)}
                {kv("Grid", `${nx}×${ny}×${nz}, ${grid.dx_mm} mm`)}
                {kv("Time step", `${(dtFor(grid) * 1e6).toFixed(2)} µs`)}
                {kv("Speaker", `${grid.radius_mm} mm`)}
                {kv("Canal", `${grid.canal_len_mm} × ⌀${grid.canal_diameter_mm} mm`)}
                {kv("Frames", frames)}
              </div>
              <p style={{ margin: 0, color: L.muted, lineHeight: 1.5, fontSize: 12 }}>
                3D: simulated field near the ear; outer spheres are the same source in open air. Directions snap to {SNAP}°. Pixel view: every source summed, seen from above.
              </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
