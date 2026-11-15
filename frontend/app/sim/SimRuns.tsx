"use client";
// The lead's simulations inside the orb: one tile per scene, every speaker direction one FDTD run in
// the worker pool (SimGrid's machinery), up to 100 scenes. Tiles draw their pressure slice on a 2D
// canvas, NEVER WebGL — Chrome keeps ~16 WebGL contexts per page and drops the oldest, so 100 3D
// cells would kill the dashboard's metal rings. A tile animates ONLY while it is on screen.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { LeadScene, SimResult } from "@/lib/lead";
import { fetchGrid, type GridWithPatient } from "./lib/api";
import { bandGainDb } from "./lib/bands";
import { dtFor } from "./lib/fdtd";
import { decodeSolid as decodeHeadSolid, dtFor as headDtFor, speakerMm as headSpeakerMm, type HeadGrid, type Side } from "./lib/headFdtd";
import { SII_FREQS, sceneDeficit, toAudiogram } from "./lib/hearing";
import { API } from "@/lib/run";
import { SimPool } from "./lib/pool";
import { dirKey } from "./lib/scenes";
import { FrameStore } from "./SimGrid";
import { DEFAULT_VIEW, snapHead, type View } from "./HeadSnap";
import Analysis, { ASIDE_PX, ClipStrip, TIMELINES_PX, type HeadSlice } from "./Analysis";
import { useClipAnalysis, useClipShapes } from "./lib/clip";
import { headKey, useTwoEar, type EarGains } from "./lib/twoEar";

// ponytail: directions snap to 15° so scenes share runs — 100 scenes cost at most 13×10 runs (~1 MB of frames each); finer steps if a scene needs them.
const SNAP = 15;
const snap = (v: number) => Math.round(v / SNAP) * SNAP;
/** One run per direction AND distance: "az,el", or "az,el@dist" for a speaker `dist_mm` from the ear (lib/lead.ts). */
const keyOf = (s: { az: number; el: number; dist_mm?: number }) => dirKey(snap(s.az), snap(s.el)) + (s.dist_mm ? `@${Math.round(s.dist_mm)}` : "");
const parseKey = (k: string) => { const [dir, d] = k.split("@"), [az, el] = dir.split(",").map(Number); return { az, el, dist: d ? Number(d) : undefined }; };
/** A near speaker's run sees the 1/r of a point source (louder than at the grid's radius R); level_db means the level AT the
 * ear for it, so that factor comes out exactly — a monopole's pressure is 1/r at every frequency. */
const nearDb = (x: { dist_mm?: number }, R: number) => (x.dist_mm ? 20 * Math.log10(R / x.dist_mm) : 0);
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
  /** The dummy-head grid already in hand (the same preview case); the detail view fetches it otherwise. */
  headGrid?: HeadGrid;
  /** The picked earpiece's earpiece.glb (with `gain`): drawn in the aided ear in the tiles and the detail's head view. A
   * root-relative /api path, so the head viewer — served by the backend itself (API) — loads it from its OWN origin. */
  aidUrl?: string;
};

export default function SimRuns({ pid, ear, scenes, gain, onDone, grid: given, headGrid, aidUrl }: Props) {
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
  // The head wearing BOTH ears (lib/twoEar.ts) scores and plays every scene per ear whenever this patient has one. The
  // one-ear grid below runs ONLY without it; while the head grid is still loading (undefined) neither starts.
  const [hg, setHg] = useState<HeadGrid | null | undefined>(headGrid);
  useEffect(() => {
    if (headGrid) return setHg(headGrid);
    fetch(`/api/sim/patients/${pid}/head_grid`).then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((g: HeadGrid) => setHg(g?.shape && g?.ears?.left && g?.ears?.right ? g : null), () => setHg(null));
  }, [pid, headGrid]);
  const aided = ear ?? grid?.patient?.side ?? (grid?.left ? "left" : "right");
  const otherSide: Side = aided === "left" ? "right" : "left";
  // each ear is scored with ITS OWN hearing test; the other ear's comes with its grid (absent: the aided ear's stands in)
  const [agOtherRaw, setAgOther] = useState<Record<string, number> | null>(null);
  useEffect(() => { fetchGrid(pid, otherSide).then((g) => setAgOther(g.patient?.audiogram_db_hl ?? null), () => setAgOther(null)); }, [pid, otherSide]);
  const two = useTwoEar(hg ?? null, scenes, aided);
  const twoEar = !!hg;
  const perScene = two.perScene;
  // Keyed on the directions, NOT the scenes array: every lead poll brings a fresh array, and a new pool would restart every run.
  const dirs = [REF, ...new Set(scenes.flatMap((s) => s.sources.map(keyOf)))].join(";");
  useEffect(() => {
    if (!grid || hg !== null) return;
    const p = new SimPool(grid, Math.max(1, Math.min(8, (navigator.hardwareConcurrency || 4) - 1)));
    setPool(p);
    // Every direction queued at once, FIFO: the pool works through them whether or not the orb is open.
    for (const k of dirs.split(";")) {
      const { az: a, el: e, dist } = parseKey(k);
      store.reset(k);
      p.run("lead", a, e, (_, slice) => store.add(k, slice), dist).then((sp) => setSpectra((s) => ({ ...s, [k]: sp })), () => {});
    }
    return () => p.dispose();
  }, [grid, dirs, store, hg]);
  const busy = useSyncExternalStore(
    (fn) => pool?.subscribe(fn) ?? (() => {}),
    () => (pool ? pool.busy : 0),
    () => 0,
  );

  const audiogram = grid?.patient?.audiogram_db_hl;
  // Every number scores the clip that actually plays (its own band spectrum), NOT a standard speech spectrum.
  const shapesBy = useClipShapes(scenes);
  const results = useMemo(() => {
    if (twoEar && audiogram) return scenes.map((s, i) => earResult(s, perScene[i]?.[aided as Side].gains, shapesBy[i], toAudiogram(audiogram), gain));
    const ref = spectra[REF];
    if (!ref || !audiogram) return scenes.map(() => null);
    const ag = toAudiogram(audiogram);
    return scenes.map((s) => {
      const sh = shapesBy[scenes.indexOf(s)];
      const srcs = s.sources.map((x, k) => (spectra[keyOf(x)] && sh[k] ? { role: x.role, az: x.az, el: x.el, levelDb: x.level_db, gainDb: bandGainDb(spectra[keyOf(x)], ref).map((g) => g - nearDb(x, grid!.radius_mm)), shapeDb: sh[k]! } : null));
      return srcs.every(Boolean) ? sceneDeficit(srcs as NonNullable<(typeof srcs)[number]>[], ag, gain) : null;
    });
  }, [spectra, scenes, audiogram, gain, twoEar, perScene, aided, shapesBy.flat().filter(Boolean).length]); // eslint-disable-line react-hooks/exhaustive-deps
  /** The OTHER ear, per scene: its own gains and hearing test, no earpiece (it is not aided). Null without the head. */
  const resultsOther = useMemo(() => scenes.map((s, i) => (twoEar && audiogram ? earResult(s, perScene[i]?.[otherSide].gains, shapesBy[i], toAudiogram(agOtherRaw ?? audiogram)) : null)),
    [scenes, twoEar, perScene, otherSide, agOtherRaw, audiogram, shapesBy.flat().filter(Boolean).length]); // eslint-disable-line react-hooks/exhaustive-deps
  /** Per scene, per source: its direction gain per SII band, null until that direction's run is done (the clip analysis reads it). */
  const gains = useMemo(() => {
    if (twoEar) return scenes.map((_, i) => perScene[i]?.[aided as Side].gains ?? scenes[i].sources.map(() => null));
    const ref = spectra[REF];
    return scenes.map((s) => s.sources.map((x) => (ref && grid && spectra[keyOf(x)] ? bandGainDb(spectra[keyOf(x)], ref).map((g) => g - nearDb(x, grid.radius_mm)) : null)));
  }, [spectra, scenes, twoEar, perScene, aided]); // eslint-disable-line react-hooks/exhaustive-deps
  const ag = useMemo(() => (audiogram ? toAudiogram(audiogram) : null), [audiogram]);
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
  const status = (i: number) => (results[i] ? "done" : twoEar ? (two.busy ? "running" : "queued") : scenes[i].sources.some((x) => !spectra[keyOf(x)]) ? "running" : "queued");
  const side = ear ?? grid.patient?.side ?? (grid.left ? "left" : "right");
  if (open !== null && scenes[open]) return <Detail pid={pid} side={side} grid={grid} aidUrl={aidUrl} headGrid={hg ?? undefined} scene={scenes[open]} store={store} result={results[open]} status={status(open)} gain={gain} gains={gains[open]} keyOf={keyOf} onBack={() => setOpen(null)}
    two={twoEar ? two : null} ears={twoEar ? { aided: perScene[open][aided as Side], other: perScene[open][otherSide], otherSide, agOther: toAudiogram(agOtherRaw ?? audiogram ?? {}) } : null} />;
  return (
    <div data-testid="sim-runs" style={{ ...PAGE, padding: "0 32px 40px" }}>
      <header style={{ display: "flex", gap: 12, alignItems: "baseline", margin: "6px 0 28px 52px" }}>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>{gain ? "With your earpiece" : "Simulations"}</h2>
        <span data-testid="sim-progress" style={{ color: L.muted, fontSize: 13, fontVariantNumeric: "tabular-nums" }}>{done === scenes.length ? `${done}` : `${done} of ${scenes.length} done · ${twoEar ? two.busy : busy} running`}</span>
      </header>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "32px 24px" }}>
        {scenes.map((s, i) => (
          <Tile key={s.id} pid={pid} aidUrl={aidUrl} left={grid.left} scene={s} result={results[i]} other={resultsOther[i] ? { side: otherSide, result: resultsOther[i] } : undefined} aided={aided} status={status(i)} gains={gains[i]} ag={ag} gain={gain} onOpen={() => setOpen(i)} />
        ))}
      </div>
    </div>
  );
}

type Res = ReturnType<typeof sceneDeficit>;
/** One ear's result for a scene from its per-source gains and clip spectra; null until every source has both. */
function earResult(s: LeadScene, g: (number[] | null)[] | undefined, sh: (number[] | null)[], ag: ReturnType<typeof toAudiogram>, device?: number[]): Res {
  if (!g || g.some((x) => !x) || sh.some((x) => !x)) return null;
  return sceneDeficit(s.sources.map((x, k) => ({ role: x.role, az: x.az, el: x.el, levelDb: x.level_db, gainDb: g[k]!, shapeDb: sh[k]! })), ag, device);
}
type Status = "done" | "running" | "queued";
/**
 * The page sits on the platform's backdrop (the dark grid the orb zooms into), so its text is light; the figures stay white
 * lab cards on it. ONE grey for everything secondary; colour ONLY in the wave fields, where it is data.
 */
const L = { ink: "#e6e8eb", muted: "#8a8f98", card: "#ffffff", radius: 12 };
const PAGE: React.CSSProperties = { color: L.ink, minHeight: "100%", fontFamily: "Inter, system-ui, -apple-system, sans-serif" };
const pct = (v?: number) => (v === undefined ? "–" : `${Math.round(v * 100)}%`);
const label: React.CSSProperties = { fontSize: 12, color: L.muted, margin: "0 0 8px" };

/** Speech heard. No aid: the patient as they are, normal hearing in the tooltip. With the aid: normal hearing against the aided ear — the gap the earpiece leaves. */
function Sii({ result, big }: { result: Res; big?: boolean }) {
  const st: React.CSSProperties = { fontSize: big ? 28 : 13, fontVariantNumeric: "tabular-nums", letterSpacing: big ? "-0.01em" : undefined };
  if (result?.siiAided !== undefined)
    return <span data-testid="sim-sii" title={`Without the aid ${pct(result.siiUnaided)}`} style={st}><span style={{ color: L.muted }}>normal </span>{pct(result.siiHealthy)}<span style={{ color: L.muted }}> · aid </span>{pct(result.siiAided)}</span>;
  return <span data-testid="sim-sii" title={`Normal hearing ${pct(result?.siiHealthy)}`} style={st}>{pct(result?.siiUnaided)}</span>;
}

/**
 * The overview: the scene as a measurement rig. Drag turns it and the wheel zooms — each move re-draws the tile through
 * HeadSnap's ONE shared renderer, so a tile never holds a WebGL context of its own. A click without a drag opens the scene.
 */
function Tile({ pid, aidUrl, left, scene, result, other, aided, status, gains, ag, gain, onOpen }: { pid: string; aidUrl?: string; left: boolean; scene: LeadScene; result: Res; other?: { side: string; result: Res }; aided: string; status: Status; gains: (number[] | null)[]; ag: ReturnType<typeof toAudiogram> | null; gain?: number[]; onOpen: () => void }) {
  // The whole clip, not just its average: how much speech gets through moment to moment (Analysis.ClipStrip).
  const clipA = useClipAnalysis(scene.sources, gains, ag, gain);
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<View>({ ...DEFAULT_VIEW });
  const drag = useRef<{ x: number; y: number; moved: boolean; pan: boolean } | null>(null);
  const frame = useRef(0);
  // through a ref: the on-screen observer below is set up ONCE, and its first-render draw drew the tile without the
  // earpiece picked since — the validation's tiles never showed it
  const drawRef = useRef(() => {});
  const draw = () => drawRef.current();
  drawRef.current = () => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => void snapHead(pid, left, scene.sources, canvas.current!, view.current, aidUrl));
  };
  // Snapshot ONLY once the tile is on screen: every snapHead is a full 3D render, and 100 tiles snapping on mount — the
  // overlay mounts hidden as soon as the scenes exist — froze the page for minutes (software WebGL ~1.7 s each).
  const seen = useRef(false);
  useEffect(() => {
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting && !seen.current) { seen.current = true; draw(); } });
    io.observe(canvas.current!);
    return () => io.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (seen.current) draw(); return () => cancelAnimationFrame(frame.current); }, [pid, left, scene, aidUrl]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // Non-passive, or the page scrolls instead of the rig zooming.
    const c = canvas.current!;
    const wheel = (e: WheelEvent) => { e.preventDefault(); view.current.zoom = Math.min(4, Math.max(0.6, view.current.zoom * Math.exp(-e.deltaY * 0.0015))); draw(); };
    c.addEventListener("wheel", wheel, { passive: false });
    return () => c.removeEventListener("wheel", wheel);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  // Left-drag turns the rig, middle-drag moves it; only a left click without a drag opens the scene.
  const down = (e: React.PointerEvent) => {
    if (e.button > 1) return;
    if (e.button === 1) e.preventDefault();      // no browser autoscroll
    drag.current = { x: e.clientX, y: e.clientY, moved: e.button === 1, pan: e.button === 1 };
    (e.target as Element).setPointerCapture(e.pointerId);
  };
  const move = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    d.moved = true;
    if (d.pan) {
      const h = (e.currentTarget as Element).getBoundingClientRect().height || 1;
      view.current.panX = (view.current.panX ?? 0) + dx / h;
      view.current.panY = (view.current.panY ?? 0) + dy / h;
    } else {
      view.current.yaw -= dx * 0.5;
      view.current.pitch += dy * 0.3;
    }
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
        style={{ width: "100%", aspectRatio: "7 / 5", display: "block", opacity: result ? 1 : 0.45, cursor: "grab", touchAction: "none", borderRadius: L.radius, background: L.card }} />
      <figcaption onClick={onOpen} style={{ display: "flex", justifyContent: "space-between", gap: 12, marginTop: 10, fontSize: 13, cursor: "pointer" }}>
        <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{scene.name}</span>
        {result ? <span style={{ whiteSpace: "nowrap" }}>
          {other && <span style={{ color: L.muted }}>{aided[0].toUpperCase()} </span>}<Sii result={result} />
          {other && <span data-testid="sim-sii-other" title={`${earName(other.side)} ear, its own hearing test, no earpiece`}><span style={{ color: L.muted }}> · {other.side[0].toUpperCase()} </span>{pct(other.result?.siiUnaided)}</span>}
        </span> : <span style={{ color: L.muted }}>{status}</span>}
      </figcaption>
      <ClipStrip A={clipA} />
    </figure>
  );
}

const earName = (s: string) => (s === "left" ? "Left" : "Right");

/** The backend's wave runs: five directions on each ear's OWN side (0 front … 180 behind), the far side a flat wall (wavesim.py). */
const RUN_AZ = [0, 45, 90, 135, 180];
/** The run for `ear` nearest the scene's main source, measured FROM that ear; null when the source is on the far side of the head for it — those runs cannot show it. */
function earRun(scene: LeadScene, ear: string, aided: string) {
  const main = scene.sources.find((s) => s.role === "talker") ?? scene.sources[0];
  const rel = (((ear === aided ? main.az : 360 - main.az) % 360) + 360) % 360;
  if (rel > 180) return { main, rel, run: null };
  const near = RUN_AZ.reduce((b, a) => (Math.abs(a - rel) < Math.abs(b - rel) ? a : b));
  return { main, rel, run: { az: near, tag: `az${String(near).padStart(3, "0")}_el+00` } };
}

/** The runs' frame (rel) is the aided ear's; a source the head stands between gets no wave run, and says where to look. */
function FarSide({ ear, rel, then }: { ear: string; rel: number; then: string }) {
  return (
    <div style={{ height: "100%", minHeight: 0, borderRadius: 10, border: `1px dashed ${L.muted}`, display: "flex", alignItems: "center", justifyContent: "center", padding: 16, textAlign: "center", fontSize: 12, lineHeight: 1.5, color: L.muted }}>
      The source is on the far side of the head for the {ear} ear ({Math.round(360 - rel)}° round from its side). The ear&apos;s own wave runs only cover its side; {then}.
    </div>
  );
}

/** Any run loads the ear's geometry; `silent=1` (wave_viewer.html) blanks its field — the ear alone, for a source on the far side. */
const SILENT_RUN = "az090_el+00";

const CROP_CELLS = 40; // 120 mm at the head grid's 3 mm: the ear, its side of the head, and the air the sound arrives through

/** One simulation opened, on ONE screen: a (the head's wavefronts) spans its column; b, c this ear; d, e the other ear; the
 * clip's timelines under them; the charts and numbers beside. EVERY figure shows the clip at the timeline's t: c and e are
 * painted by Analysis from the head run, a, b and d are the backend viewers on the SAME clock (Analysis sync). */
function Detail({ pid, aidUrl, side, grid, headGrid: given, scene, result, status, gain, gains, onBack, two, ears }: { pid: string; aidUrl?: string; side: string; grid: GridWithPatient; headGrid?: HeadGrid; scene: LeadScene; store: FrameStore; result: Res; status: Status; gain?: number[]; gains: (number[] | null)[]; keyOf: (s: { az: number; el: number }) => string; onBack: () => void;
  two: ReturnType<typeof useTwoEar> | null; ears: { aided: EarGains; other: EarGains; otherSide: Side; agOther: ReturnType<typeof toAudiogram> } | null }) {
  const ag = grid.patient?.audiogram_db_hl ?? {};
  const [headGrid, setHeadGrid] = useState<HeadGrid | null>(given ?? null);
  const [headErr, setHeadErr] = useState<string | null>(null);
  useEffect(() => {
    if (given) return;
    fetch(`/api/sim/patients/${pid}/head_grid`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      // Checked before use: anything else at that URL would crash the field painters.
      .then((g: HeadGrid) => (g?.shape && g?.ears?.left && g?.ears?.right ? setHeadGrid(g) : Promise.reject(new Error("not a head grid"))))
      .catch((e: Error) => setHeadErr(e.message));
  }, [pid, given]);
  // the scene's runs come from SimRuns' ONE two-ear pool (lib/twoEar.ts); without a head there are none
  const head = { store: two?.store ?? { get: () => undefined }, every: two?.every ?? 0, running: (two?.busy ?? 0) > 0, eardrum: (e: Side) => two?.eardrum(scene, e) ?? null };
  const other = side === "left" ? "right" : "left";
  // The slice the worker records (headFdtd.ts runPlaneWave): one row at ear height through both canals.
  const slice = useMemo<HeadSlice | null>(() => {
    if (!headGrid || !head.every) return null;
    const [nx, ny, nz] = headGrid.shape, solid3 = decodeHeadSolid(headGrid);
    const row = Math.round((headGrid.ears.left.receiver[1] + headGrid.ears.right.receiver[1]) / 2);
    const solid = new Uint8Array(nx * nz);
    for (let i = 0; i < nx; i++) for (let l = 0; l < nz; l++) solid[i * nz + l] = solid3[i * ny * nz + row * nz + l];
    // the wave timeline traces the aided ear: the air cell in this row nearest its eardrum receiver
    const [ri, , rl] = headGrid.ears[side as Side].receiver;
    let probe = ri * nz + rl, best = Infinity;
    for (let i = ri - 6; i <= ri + 6; i++) for (let l = rl - 6; l <= rl + 6; l++) {
      if (i < 0 || l < 0 || i >= nx || l >= nz || solid[i * nz + l]) continue;
      const d = (i - ri) ** 2 + (l - rl) ** 2;
      if (d < best) { best = d; probe = i * nz + l; }
    }
    const keys = scene.sources.map((s) => headKey(s, side));
    return { frames: () => keys.map((k) => head.store.get(k)), step: head.every * headDtFor(headGrid), nx, nz, solid, probe, probeLabel: `the ${side} ear canal` };
  }, [headGrid, head.every, head.store, scene, side]);
  const mine = earRun(scene, side, side), theirs = earRun(scene, other, side);
  // The tag rides URL-encoded: a raw "+" in "el+00" arrives as a space and the viewers fall back to their default direction (WaveBento).
  const q = (tag: string) => `embed=1&run=${encodeURIComponent(tag)}`;
  // the picked earpiece rides into the AIDED ear's viewers only; the other ear wears none
  const piece = aidUrl ? `&piece=${encodeURIComponent(aidUrl)}` : "";
  // The scene's speakers for the head viewer (head_viewer.html ?src): it draws them before ANY wave run exists, as HeadSnap does.
  const spk = scene.sources.map((x) => [x.az, x.el, x.role, x.dist_mm ?? ""].join(",")).join(";");
  const view: React.CSSProperties = { width: "100%", height: "100%", border: 0, borderRadius: 10, display: "block", background: "#fbfaf8" };
  // ONE screen: the cell is the largest square that fits beside the charts AND two rows above the timelines. a, the full head
  // model, is WIDE: at least 1.5 cells, plus whatever width the row has left; captions are a title line only.
  const CAP = 26, GAP = 16, WIDE = 1.5;
  const cell = `min(calc((100vw - 64px - ${ASIDE_PX}px - 32px - ${2 * GAP}px) / ${2 + WIDE}), calc((100vh - 20px - 60px - 40px - ${TIMELINES_PX}px - ${2 * CAP}px) / 2))`;
  const fig = (letter: string, title: string, body: React.ReactNode, tall = false) => (
    <figure style={{ margin: 0, minWidth: 0, gridRow: tall ? "1 / span 2" : undefined, display: "flex", flexDirection: "column" }}>
      <div style={{ height: tall ? `calc(2 * ${cell} + ${CAP}px)` : cell, position: "relative" }}>{body}</div>
      <figcaption style={{ height: CAP, overflow: "hidden", paddingTop: 7, fontSize: 11.5, lineHeight: 1.4 }}>
        <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", marginRight: 7 }}>{letter}</span>{title}
      </figcaption>
    </figure>
  );
  const waiting = (text: string) => <div style={{ height: "100%", borderRadius: 10, background: "rgba(255,255,255,0.06)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, color: L.muted, padding: 16, textAlign: "center" }}>{text}</div>;
  /** Where the sound comes from: each source's direction from the head, at the view's edge. */
  const dots = () => headGrid && scene.sources.map((s, k) => {
    const d = headSpeakerMm(headGrid, Number(headKey(s, side).split(",")[0]), 0, 1), n = Math.hypot(d[0], d[2]) || 1;
    return <span key={k} title={`S${k + 1} ${s.role}`} style={{ position: "absolute", left: `${50 + (d[0] / n) * 44}%`, top: `${50 + (d[2] / n) * 44}%`, transform: "translate(-50%, -50%)", fontSize: 10, lineHeight: "16px", width: 16, textAlign: "center", borderRadius: 8, background: "#111", color: "#fff" }}>{k + 1}</span>;
  });
  const crops = useMemo(() => {
    if (!headGrid) return null;
    const [nx, , nz] = headGrid.shape;
    const at = (v: number, o: number, len: number) => Math.min(len - CROP_CELLS, Math.max(0, Math.round((v - o) / headGrid.dx_mm) - CROP_CELLS / 2));
    const ear = (e: Side) => ({ i0: at(headGrid.ears[e].canal_point_mm[0], headGrid.origin_mm[0], nx), l0: at(headGrid.ears[e].canal_point_mm[2], headGrid.origin_mm[2], nz), w: CROP_CELLS, h: CROP_CELLS });
    return { left: ear("left"), right: ear("right") };
  }, [headGrid]);
  const kv = (k: string, v: React.ReactNode) => <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "2px 0" }}><span style={{ color: L.muted }}>{k}</span><span style={{ fontVariantNumeric: "tabular-nums", textAlign: "right" }}>{v}</span></div>;
  const tiny: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "4px 2px", fontSize: 10.5, textAlign: "center", fontVariantNumeric: "tabular-nums" };
  const hz = (f: number) => (f >= 1000 ? `${f / 1000}k` : `${f}`);
  const loading = waiting(headErr ? `No head grid for this patient (${headErr}).` : "Simulating the head…");
  return (
    <div data-testid="sim-detail" style={{ ...PAGE, padding: "0 32px 24px", boxSizing: "border-box" }}>
      {/* Lifted onto the Exit X's row (fixed at top 20, 40 tall): the overlay's 56px top pad minus 36. */}
      <header style={{ display: "flex", gap: 14, alignItems: "center", margin: "-36px 0 20px 52px", height: 40 }}>
        <button type="button" aria-label="All simulations" onClick={onBack} style={{ border: 0, background: "none", color: L.muted, cursor: "pointer", fontSize: 18, padding: 0, lineHeight: 1 }}>←</button>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>{scene.name}</h2>
        {status !== "done" && <span style={{ color: L.muted, fontSize: 13 }}>{status}</span>}
      </header>
      <Analysis grid={grid} scene={scene} head={slice} gains={gains} gain={gain} side={side}
        other={ears ? { side: ears.otherSide, gains: ears.other.gains, ag: ears.agOther } : undefined}
        delays={ears ? { aided: ears.aided.delays, other: ears.other.delays } : undefined}
        figures={(View, sync) => (
          <div style={{ display: "grid", gridTemplateColumns: `minmax(calc(${WIDE} * ${cell}), 1fr) ${cell} ${cell}`, gap: `0 ${GAP}px` }}>
            {fig("a", "Wavefronts around the head",
              mine.run ? <iframe ref={sync("a")} data-testid="sim-3d" title="Wavefronts around the head" src={`${API}/api/patients/${pid}/head/viewer.html?${q(mine.run.tag)}&rig=1&ear=${side}&aided=${side}&src=${encodeURIComponent(spk)}${piece}`} style={view} />
                : <FarSide ear={side} rel={mine.rel} then="c shows what reaches it round the head" />, true)}
            {fig("b", `Slices, ${side} ear`,
              mine.run ? <iframe ref={sync("b")} data-testid="sim-ear" title={`Wave slices, ${side} ear`} src={`${API}/api/patients/${pid}/waves/${side}/index.html?${q(mine.run.tag)}&disp=slices${piece}`} style={view} />
                : <iframe data-testid="sim-ear" title={`${side} ear, no direct wave`} src={`${API}/api/patients/${pid}/waves/${side}/index.html?${q(SILENT_RUN)}&disp=slices&silent=1${piece}`} style={view} />)}
            {fig("c", `Field at the ${side} ear`,
              slice && crops ? <><View crop={crops[side as Side]} testid="sim-slice" />{dots()}</> : loading)}
            {fig("d", `Slices, ${other} ear`,
              theirs.run ? <iframe ref={sync("d")} data-testid="sim-ear-other" title={`Wave slices, ${other} ear`} src={`${API}/api/patients/${pid}/waves/${other}/index.html?${q(theirs.run.tag)}&disp=slices`} style={view} />
                : <iframe data-testid="sim-ear-other" title={`${other} ear, no direct wave`} src={`${API}/api/patients/${pid}/waves/${other}/index.html?${q(SILENT_RUN)}&disp=slices&silent=1`} style={view} />)}
            {fig("e", `Field at the ${other} ear`,
              slice && crops ? <><View crop={crops[other as Side]} testid="sim-slice-other" />{dots()}</> : loading)}
          </div>
        )}
        info={<>
          <div>
            <p style={label}>Speech heard</p>
            <Sii result={result} big />
          </div>
          {result && (
            <div data-testid="sim-deficit">
              <p style={label}>Hearing lost, dB</p>
              <div style={tiny}>{SII_FREQS.map((f, i) => <div key={f}><div style={{ color: L.muted }}>{hz(f)}</div><div>{Math.round(result.deficit[i])}</div></div>)}</div>
            </div>
          )}
          <div>
            <p style={label}>Hearing test, dB HL{grid.patient?.audiogram_is_example ? " (example)" : ""}</p>
            <div style={tiny}>{Object.entries(ag).map(([f, v]) => <div key={f}><div style={{ color: L.muted }}>{hz(Number(f))}</div><div>{v}</div></div>)}</div>
          </div>
          <div>
            <p style={label}>Method</p>
            {kv("Aided ear", earName(side))}
            {kv("a, b, d", "ear runs, source 120 mm, main talker")}
            {kv("c, e", headGrid ? `head ${headGrid.shape.join("×")}, ${headGrid.dx_mm} mm` : "head grid")}
            {kv("c, e sources", "far talkers, plane clicks")}
            {kv("Speech numbers", `ear grid ${grid.shape.join("×")}, ${grid.dx_mm} mm`)}
            {kv("Time step", `${(dtFor(grid) * 1e6).toFixed(2)} µs`)}
          </div>
          <p style={{ margin: 0, color: L.muted, lineHeight: 1.45, fontSize: 11 }}>
            Every figure shows this clip at t. a, b, d: each ear simulated alone, a flat wall for the head, so only sources on its own side. c, e and the eardrum trace: one run on a head wearing both ears, so the far ear sits in the head&apos;s shadow. Directions snap to {SNAP}°.
          </p>
        </>} />
    </div>
  );
}
