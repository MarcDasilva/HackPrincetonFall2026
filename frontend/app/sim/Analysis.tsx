"use client";
// One scene played through its simulation. ONE clock, clip time t: "Real time" plays the clip as this ear hears it
// and the field flickers (waves cross the ear in under a millisecond, too fast to see); "Slow motion" advances the
// SAME t thousands of times slower with no audio, so the wavefronts walk in. Every chart reads t.
import { useEffect, useMemo, useRef, useState } from "react";
import type { LeadScene } from "@/lib/lead";
import type { GridWithPatient } from "./lib/api";
import { hearingLevel, SII_FREQS, toAudiogram, type Audiogram } from "./lib/hearing";
import { CLIPS, cumulate, fieldAt, highpass, HOP, looped, pointAt, renderMix, SR, useClipAnalysis, WIN, type ClipAnalysis, type Cond, type FieldRun } from "./lib/clip";

const INK = "#e6e8eb", MUTED = "#8a8f98", CARD = "#ffffff", CARD_INK = "#5d646e";
/** Pressure colours, the SAME as SimRuns' EarField and the 3D figure: orange up, blue down. */
const UP = [235, 104, 52], DOWN = [57, 135, 229];
/** One colour per listener, used by every chart. */
const COND: Record<Cond, { label: string; color: string }> = {
  healthy: { label: "Normal hearing", color: "#9aa0a8" },
  you: { label: "You", color: "#d95926" },
  aided: { label: "With the aid", color: "#2a78d6" },
};
/** The eardrum trace is physics, the SAME for every listener: no listener colour. */
const EAR = "#2b2f36";
export const ASIDE_PX = 320;
const SPEEDS = [2000, 10000, 20000, 50000];
const WAVE_WIN = 2e-3;   // the wave timeline spans 2 ms of sound around t
const fmtHz = (f: number) => (f >= 1000 ? `${f / 1000}k` : `${f}`);
const label: React.CSSProperties = { fontSize: 12, color: MUTED, margin: "0 0 8px" };
const card: React.CSSProperties = { background: CARD, borderRadius: 10, display: "block", width: "100%" };
const btn = (on: boolean): React.CSSProperties => ({ border: "1px solid rgba(255,255,255,0.18)", background: on ? INK : "transparent", color: on ? "#111" : INK, borderRadius: 999, padding: "5px 12px", fontSize: 12, cursor: "pointer", whiteSpace: "nowrap" });

type Props = {
  grid: GridWithPatient; scene: LeadScene;
  /** The head simulation every figure is drawn from; null until its grid is loaded. */
  head: HeadSlice | null;
  /** per source, its direction gain per SII band (null until its run is done) */
  gains: (number[] | null)[] | null;
  /** the picked design's insertion gain per band (the AIDED ear only) */
  gain?: number[];
  /** the aided ear */
  side?: string;
  /** The other ear from the SAME head runs (lib/twoEar.ts): its own gains and hearing test. With it, the charts switch
   * ear and playback is stereo — each ear its own mix, hearing loss and arrival delay. */
  other?: { side: string; gains: (number[] | null)[] | null; ag: Audiogram | null };
  /** per source, how much later the sound reaches each ear than the earlier one (s) */
  delays?: { aided: (number | null)[]; other: (number | null)[] };
  /** the right-hand column's static rows (numbers, hearing test, method) */
  info: React.ReactNode;
  /** The figure grid above the timelines. `View` draws one window of the clip-driven field; EVERY view is painted from
   * the SAME field at the SAME t, on ONE colour scale. `sync(key)` is a ref for a backend viewer iframe: it gets the main
   * source's clip and every t, and draws its own click frames at that t (head_viewer.html / wave_viewer.html clock). */
  figures: (View: (p: { crop: Crop; testid: string }) => React.ReactElement, sync: (key: string) => (el: HTMLIFrameElement | null) => void) => React.ReactNode;
};

/** One horizontal slice of the head run: its frames per source (same order as scene.sources), the time between frames,
 * the slice size, which cells are solid, and the cell whose pressure the wave timeline traces (the aided ear's canal). */
export type HeadSlice = { frames: () => (Float32Array[] | undefined)[]; step: number; nx: number; nz: number; solid: Uint8Array; probe: number; probeLabel: string };
/** A window into the slice, in cells: x from i0, z from l0. */
export type Crop = { i0: number; l0: number; w: number; h: number };

/** Height the timelines and their captions take under the figures (SimRuns sizes its figure cells to leave it). */
export const TIMELINES_PX = 236;

export default function Analysis({ grid, scene, head, gains, gain, side = "right", other, delays, info, figures }: Props) {
  const [clip, setClip] = useState<string>(CLIPS[0]);
  const ag = useMemo(() => (grid.patient?.audiogram_db_hl ? toAudiogram(grid.patient.audiogram_db_hl) : null), [grid]);
  const Aided = useClipAnalysis(scene.sources, gains, ag, gain, clip);
  const Other = useClipAnalysis(scene.sources, other?.gains ?? null, other?.ag ?? null, undefined, clip);
  // the charts show ONE ear at a time; the earpiece is only ever in the aided one
  const [earView, setEarView] = useState<"aided" | "other">("aided");
  const A = earView === "other" && Other ? Other : Aided;
  const [cond0, setCond] = useState<Cond>(gain ? "aided" : "you");
  const cond: Cond = A === Other && cond0 === "aided" ? "you" : cond0;
  const [mode, setMode] = useState<"stop" | "real" | "slow">("stop");
  const [speed, setSpeed] = useState(20000);
  const [t, setT] = useState(0.5);
  const tRef = useRef(t);
  tRef.current = t;

  // audio: each listener's mix rendered once, ALL at the healthy mix's scale so a hearing loss sounds quieter
  const audio = useRef<{ ctx?: AudioContext; node?: AudioBufferSourceNode; startAt: number; bufs: Map<string, AudioBuffer>; scale?: number }>({ startAt: 0, bufs: new Map() });
  // With the other ear: STEREO, each channel that ear's own mix (its gains and delays), its own hearing loss, and the
  // earpiece in the aided ear only. Without it: the aided ear in mono, as before.
  const buffer = (c: Cond) => {
    const au = audio.current, k = `${clip}|${c}`;
    if (!Aided || !ag) return null;
    if (!au.bufs.has(k)) {
      const ears = [{ side, A: Aided, ag, device: gain, d: delays?.aided }, ...(Other && other?.ag ? [{ side: other.side, A: Other, ag: other.ag, device: undefined, d: delays?.other }] : [])];
      const mix = (e: (typeof ears)[number], cc: Cond) => {
        const hl = hearingLevel(e.ag, SII_FREQS);
        return renderMix(e.A, SII_FREQS.map((_, b) => (cc === "healthy" ? 0 : -hl[b] + (cc === "aided" && e.device ? e.device[b] : 0))), e.d);
      };
      // a loop, NEVER Math.max(...samples): two 5 s channels are 240k arguments and overflow the call stack
      if (au.scale === undefined) { let m = 1e-9; for (const e of ears) for (const v of mix(e, "healthy")) m = Math.max(m, Math.abs(v)); au.scale = 0.5 / m; }
      const xs = ears.map((e) => mix(e, c)), n = Math.max(...xs.map((x) => x.length));
      const b = au.ctx!.createBuffer(ears.length > 1 ? 2 : 1, n, SR);
      ears.forEach((e, i) => b.copyToChannel(Float32Array.from(xs[i], (v) => v * au.scale!), ears.length > 1 ? (e.side === "left" ? 0 : 1) : 0));
      au.bufs.set(k, b);
    }
    return au.bufs.get(k)!;
  };
  const stopAudio = () => { const au = audio.current; try { au.node?.stop(); } catch { /* already ended */ } au.node = undefined; };
  const startAudio = (from: number, c = cond) => {
    const au = audio.current;
    au.ctx ??= new AudioContext({ sampleRate: SR });
    void au.ctx.resume();
    stopAudio();
    const b = buffer(c);
    if (!b) return;
    const n = au.ctx.createBufferSource();
    n.buffer = b;
    n.connect(au.ctx.destination);
    n.start(0, from);
    au.node = n;
    au.startAt = au.ctx.currentTime - from;
  };
  useEffect(() => { audio.current.bufs.clear(); audio.current.scale = undefined; stopAudio(); setMode("stop"); }, [Aided, Other]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { stopAudio(); void audio.current.ctx?.close(); }, []);

  // the clock
  useEffect(() => {
    if (mode === "stop" || !Aided) return;
    let raf = 0, last = performance.now(), shown = 0;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      const au = audio.current;
      let nt = mode === "real" && au.ctx ? au.ctx.currentTime - au.startAt : tRef.current + (now - last) / 1000 / speed;
      last = now;
      if (nt >= Aided.duration) { nt = Aided.duration; setMode("stop"); stopAudio(); }
      tRef.current = nt;
      if (now - shown > 33) { shown = now; setT(nt); }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [mode, speed, Aided]);

  const seek = (nt: number) => {
    if (!Aided) return;
    nt = Math.min(Aided.duration, Math.max(0, nt));
    tRef.current = nt; setT(nt);
    if (mode === "real") startAudio(nt);
  };
  const playReal = () => {
    if (mode === "real") { stopAudio(); setMode("stop"); return; }
    const from = Aided && tRef.current >= Aided.duration - 0.01 ? 0 : tRef.current;
    seek(from); startAudio(from); setMode("real");
  };
  const playSlow = () => { stopAudio(); setMode(mode === "slow" ? "stop" : "slow"); };
  const pickCond = (c: Cond) => { setCond(c); if (mode === "real") startAudio(tRef.current, c); };

  // the field's ingredients: each source's head-run frames (summed over time, lib/clip.ts), level and clip. Frames stream
  // in while the runs finish, so they are re-read until the count stops growing.
  // Speech's energy sits at 100–300 Hz, wavelengths over a metre: the whole head sits in ONE slow swell. Above 1 kHz
  // (where the consonants and this hearing loss live) the wavelengths fit the picture, so that is the default view.
  const [band, setBand] = useState<"hi" | "all">("hi");
  const U = useMemo(() => (Aided ? Aided.srcs.map((x) => (band === "hi" ? highpass(looped(x.x, Aided.n), 1000) : looped(x.x, Aided.n))) : []), [Aided, band]);
  const [runs, setRuns] = useState<FieldRun[]>([]);
  useEffect(() => {
    if (!Aided || !head) return;
    let n = -1;
    const poll = () => {
      const fs = head.frames(), m = fs.reduce((k, f) => k + (f?.length ?? 0), 0);
      if (m === n) return;
      n = m;
      setRuns(fs.map((f, i) => ({ frames: cumulate(f ?? []), a: 10 ** ((scene.sources[i].level_db - 65) / 20), U: U[i] })));
    };
    poll();
    const id = window.setInterval(poll, 500);
    return () => window.clearInterval(id);
  }, [Aided, head, scene, U]);
  const views = useRef(new Map<string, { canvas: HTMLCanvasElement; crop: Crop }>());
  // Middle-drag slides a view's window over the slice, per view, in cells; the painter repaints when one moves.
  const pans = useRef(new Map<string, { di: number; dl: number }>());
  const panned = useRef(false);
  const View = useMemo(() => function View({ crop, testid }: { crop: Crop; testid: string }) {
    const drag = useRef<{ x: number; y: number } | null>(null);
    return <canvas data-testid={testid} width={crop.w} height={crop.h}
      onPointerDown={(e) => { if (e.button !== 1) return; e.preventDefault(); drag.current = { x: e.clientX, y: e.clientY }; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!d) return;
        const r = e.currentTarget.getBoundingClientRect(), p = pans.current.get(testid) ?? { di: 0, dl: 0 };
        pans.current.set(testid, { di: p.di + ((e.clientX - d.x) / r.width) * crop.w, dl: p.dl + ((e.clientY - d.y) / r.height) * crop.h });
        drag.current = { x: e.clientX, y: e.clientY };
        panned.current = true;
      }}
      onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
      ref={(c) => { if (c) views.current.set(testid, { canvas: c, crop }); else views.current.delete(testid); }}
      style={{ width: "100%", height: "100%", borderRadius: 10, display: "block", background: "#fff", imageRendering: "pixelated" }} />;
  }, []);
  usePainter(head, runs, tRef, views, pans, panned);

  // The backend viewers simulate ONE speaker each, so they play the main source's clip (the same filtered signal as the
  // page's fields). They announce themselves ('auris-ready') once loaded; the clip goes then, and again when it changes.
  const frames = useRef(new Map<string, HTMLIFrameElement>());
  const main = Math.max(0, scene.sources.findIndex((x) => x.role === "talker"));
  const sendClip = (w: Window | null | undefined) => { if (w && U[main]) w.postMessage({ type: "auris-clip", u: U[main], sr: SR, t: tRef.current }, "*"); };
  useEffect(() => { for (const f of frames.current.values()) sendClip(f.contentWindow); }, [U]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const on = (e: MessageEvent) => { if (e.data?.type === "auris-ready" && [...frames.current.values()].some((f) => f.contentWindow === e.source)) sendClip(e.source as Window); };
    window.addEventListener("message", on);
    return () => window.removeEventListener("message", on);
  }, [U]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { for (const f of frames.current.values()) f.contentWindow?.postMessage({ type: "auris-t", t }, "*"); }, [t]);
  const sync = useMemo(() => (key: string) => (el: HTMLIFrameElement | null) => { if (el) frames.current.set(key, el); else frames.current.delete(key); }, []);
  const frame = A ? Math.min(A.frames - 1, Math.max(0, Math.floor((t * SR - WIN / 2) / HOP))) : 0;

  const conds: Cond[] = gain && A === Aided ? ["healthy", "you", "aided"] : ["healthy", "you"];   // the earpiece is in the aided ear only
  return (
    <div data-testid="sim-analysis" style={{ display: "grid", gridTemplateColumns: `minmax(0, 1fr) ${ASIDE_PX}px`, gap: 32, alignItems: "start" }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", marginBottom: 16, fontSize: 12 }}>
          {/* clipNames: a source with its own bank `sound` ignores the speech pick, so the menu only shows when one would use it */}
          {scene.sources.some((x) => !x.sound) && <label style={{ color: MUTED }}>Clip{" "}
            <select data-testid="clip-select" value={clip} onChange={(e) => setClip(e.target.value)}
              style={{ background: "transparent", color: INK, border: "1px solid rgba(255,255,255,0.18)", borderRadius: 6, padding: "4px 6px", fontSize: 12 }}>
              {CLIPS.map((c, i) => <option key={c} value={c} style={{ color: "#111" }}>Speech {i + 1}</option>)}
            </select>
          </label>}
          <span style={{ color: MUTED }}>{Aided ? Aided.srcs.map((s) => `${s.role}: ${s.clip.replace(/^bank:/, "").replace("_noise", "").replace(/_/g, " ")}`).join(" · ") : "loading clips…"}</span>
          <label style={{ color: MUTED }}>Field shows{" "}
            <select data-testid="field-band" value={band} onChange={(e) => setBand(e.target.value as "hi" | "all")}
              style={{ background: "transparent", color: INK, border: "1px solid rgba(255,255,255,0.18)", borderRadius: 6, padding: "4px 6px", fontSize: 12 }}>
              <option value="hi" style={{ color: "#111" }}>Above 1 kHz</option>
              <option value="all" style={{ color: "#111" }}>Full sound</option>
            </select>
          </label>
          <span style={{ flex: 1 }} />
          {/* which ear the charts show; playback is stereo and plays BOTH */}
          {other && Other && (
            <span role="group" aria-label="Ear" style={{ display: "flex", gap: 6 }}>
              {([["aided", side], ["other", other.side]] as const).map(([k, s]) => (
                <button key={k} type="button" data-testid={`ear-${s}`} aria-pressed={earView === k} onClick={() => setEarView(k)} style={btn(earView === k)}>
                  {s === "left" ? "Left" : "Right"} ear{k === "aided" && gain ? " (aid)" : ""}
                </button>
              ))}
            </span>
          )}
          <span role="group" aria-label="Listener" style={{ display: "flex", gap: 6 }}>
            {conds.map((c) => <button key={c} type="button" aria-pressed={cond === c} onClick={() => pickCond(c)} style={btn(cond === c)}>{COND[c].label}</button>)}
          </span>
        </div>
        {figures(View, sync)}
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 11, color: MUTED, margin: "4px 0 10px", fontVariantNumeric: "tabular-nums" }}>
          <span>t = {(t * 1000).toFixed(3)} ms{mode === "slow" ? ` · slowed ${speed.toLocaleString()}×` : mode === "real" ? " · real time" : ""}</span>
          <span>Every figure is this clip at this instant.</span>
        </div>
        <ClipTimeline A={Aided} t={t} onSeek={seek} playing={mode === "real"} onPlay={playReal} />
        <WaveTimeline A={Aided} runs={runs} t={t} step={head?.step ?? 1} cell={head?.probe ?? 0} probe={head?.probeLabel ?? "the eardrum"} onSeek={seek} playing={mode === "slow"} onPlay={playSlow} speed={speed} onSpeed={setSpeed} />
      </div>
      {/* ONE screen: the header on the Exit X's row (top 20 + 40), the gap above (20 + 20) and the bottom pad (24) take 128px — a 100vh cap here scrolled the page. Long info scrolls INSIDE the column. */}
      <aside data-testid="sim-info" style={{ fontSize: 13, position: "sticky", top: 16, maxHeight: "calc(100vh - 128px)", overflowY: "auto", scrollbarWidth: "none", display: "flex", flexDirection: "column", gap: 22 }}>
        <SiiChart A={A} t={t} conds={conds} onSeek={seek} />
        <Spectrogram A={A} t={t} cond={cond} onSeek={seek} />
        <NowChart A={A} frame={frame} cond={cond} />
        {info}
      </aside>
    </div>
  );
}

/** Paints every registered view from ONE field: computed once per t (and whenever more frames arrive), smoothed, then each
 * view copies its window. ONE fixed scale per scene for all of them — the same t ALWAYS paints the same picture (a running
 * peak would make it depend on how you got there), and a quieter ear or a gap between words reads quieter. */
function usePainter(head: HeadSlice | null, runs: FieldRun[], tRef: React.MutableRefObject<number>, views: React.MutableRefObject<Map<string, { canvas: HTMLCanvasElement; crop: Crop }>>,
  pans: React.MutableRefObject<Map<string, { di: number; dl: number }>>, panned: React.MutableRefObject<boolean>) {
  useEffect(() => {
    if (!head) return;
    const { nx, nz, solid } = head;
    const raw = new Float32Array(nx * nz), sum = new Float32Array(nx * nz);
    let raf = 0, last = -1, painted = new Set<HTMLCanvasElement>();
    // the scale: at 64 instants, the level 98% of cells stay under, then a loud-but-typical one of those (80th percentile).
    // A box-wide rule is right HERE because the head run's source is a plane wave, as strong everywhere; the backend viewers'
    // point speaker falls off as 1/r, so they scale to the wave arriving at the ear instead (clockScale there).
    const dur = Math.max(0, ...runs.map((r) => r.U.length / SR));
    const peaks: number[] = [];
    for (let k = 0; k < 64; k++) {
      fieldAt(raw, runs, ((k + 0.5) / 64) * dur, head.step);
      const v: number[] = [];
      for (let j = 0; j < raw.length; j += 7) v.push(Math.abs(raw[j]));
      v.sort((x, y) => x - y);
      peaks.push(v[Math.floor(0.98 * (v.length - 1))] || 0);
    }
    peaks.sort((x, y) => x - y);
    const peak = Math.max(1e-12, peaks[Math.floor(0.8 * (peaks.length - 1))]);
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const t = tRef.current, vs = [...views.current.values()];
      // a view that mounted since the last paint needs one even when t has not moved
      if (t === last && vs.every((v) => painted.has(v.canvas)) && !panned.current) return;
      panned.current = false;
      last = t;
      painted = new Set(vs.map((v) => v.canvas));
      fieldAt(raw, runs, t, head.step);
      // 3×3 binomial smooth: the frames carry one-cell grid noise (FDTD content past what the grid resolves, aliased by
      // the frame spacing); 8 kHz speech spans many cells per wavelength, so real wavefronts pass untouched.
      for (let i = 0; i < nx; i++) for (let l = 0; l < nz; l++) {
        let v = 0, w = 0;
        for (let di = -1; di <= 1; di++) for (let dl = -1; dl <= 1; dl++) {
          const a = i + di, b = l + dl;
          if (a < 0 || b < 0 || a >= nx || b >= nz || solid[a * nz + b]) continue;
          const k = (2 - Math.abs(di)) * (2 - Math.abs(dl));
          v += k * raw[a * nz + b]; w += k;
        }
        sum[i * nz + l] = w ? v / w : 0;
      }
      for (const [key, { canvas, crop: c0 }] of views.current) {
        // the picture follows the pointer: the window moves the other way
        const p = pans.current.get(key), crop = p ? { ...c0, i0: c0.i0 - Math.round(p.di), l0: c0.l0 - Math.round(p.dl) } : c0;
        const ctx = canvas.getContext("2d")!, img = ctx.createImageData(crop.w, crop.h);
        for (let c = 0; c < crop.w; c++) for (let r = 0; r < crop.h; r++) {
          const i = crop.i0 + c, l = crop.l0 + r, o = (r * crop.w + c) * 4;
          if (i < 0 || l < 0 || i >= nx || l >= nz) { img.data.set([255, 255, 255, 255], o); continue; }   // past the slice: open air
          if (solid[i * nz + l]) { img.data.set([201, 196, 188, 255], o); continue; }
          const v = sum[i * nz + l] / peak, a = Math.min(1, Math.abs(v) * 1.6), c0 = v >= 0 ? UP : DOWN;
          img.data.set([255 - (255 - c0[0]) * a, 255 - (255 - c0[1]) * a, 255 - (255 - c0[2]) * a, 255], o);
        }
        ctx.putImageData(img, 0, 0);
      }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [head, runs, tRef, views, pans, panned]);
}

/** Pointer x on an element → 0..1, for click-and-drag seeking. */
function useScrub(onFrac: (f: number) => void) {
  const on = useRef(false);
  const f = (e: React.PointerEvent) => { const r = (e.currentTarget as Element).getBoundingClientRect(); onFrac(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))); };
  return {
    onPointerDown: (e: React.PointerEvent) => { on.current = true; (e.currentTarget as Element).setPointerCapture(e.pointerId); f(e); },
    onPointerMove: (e: React.PointerEvent) => { if (on.current) f(e); },
    onPointerUp: () => { on.current = false; },
    style: { cursor: "ew-resize", touchAction: "none" } as React.CSSProperties,
  };
}

const playBtn = (playing: boolean, text: string, onClick: () => void, testid: string) => (
  <button type="button" data-testid={testid} onClick={onClick} style={{ ...btn(playing), minWidth: 128 }}>{playing ? "❚❚ Pause" : `▶ ${text}`}</button>
);

/** The whole clip, seconds: its waveform at the speaker and the playhead. Plays at real time WITH audio. */
function ClipTimeline({ A, t, onSeek, playing, onPlay }: { A: ClipAnalysis | null; t: number; onSeek: (t: number) => void; playing: boolean; onPlay: () => void }) {
  const W = 600, H = 44;
  const path = useMemo(() => {
    if (!A) return "";
    const n = A.talk.length, per = Math.ceil(n / W);
    let m = 1e-9;
    for (let i = 0; i < n; i++) m = Math.max(m, Math.abs(A.talk[i]));
    let d = "";
    for (let x = 0; x < W; x++) {
      let hi = 0;
      for (let i = x * per; i < Math.min(n, (x + 1) * per); i++) hi = Math.max(hi, Math.abs(A.talk[i]));
      const h = (hi / m) * (H / 2 - 4);
      d += `M${x},${H / 2 - h}V${H / 2 + h}`;
    }
    return d;
  }, [A]);
  const scrub = useScrub((f) => A && onSeek(f * A.duration));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr)", gap: "4px 14px", alignItems: "center", marginBottom: 10 }}>
      {playBtn(playing, "Real time", onPlay, "play-real")}
      <svg data-testid="clip-timeline" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" {...scrub} style={{ ...card, height: H, ...scrub.style }}>
        <path d={path} stroke="#c9c4bc" strokeWidth={1} />
        {A && <path d={path} stroke={CARD_INK} strokeWidth={1} clipPath="url(#played)" />}
        <defs><clipPath id="played"><rect x={0} y={0} width={A ? (t / A.duration) * W : 0} height={H} /></clipPath></defs>
        {A && <line x1={(t / A.duration) * W} x2={(t / A.duration) * W} y1={0} y2={H} stroke="#111" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
      </svg>
      <span />
      <span style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: MUTED, fontVariantNumeric: "tabular-nums" }}>
        <span>Clip, real time</span><span>{t.toFixed(2)} s / {A ? A.duration.toFixed(2) : "–"} s</span>
      </span>
    </div>
  );
}

/** 2 ms around t: the clip at the speaker and the pressure the simulation puts at the eardrum. Plays SLOWED, no audio. */
function WaveTimeline({ A, runs, t, step, cell, probe, onSeek, playing, onPlay, speed, onSpeed }: {
  A: ClipAnalysis | null; runs: FieldRun[]; t: number; step: number; cell: number; probe: string; onSeek: (t: number) => void;
  playing: boolean; onPlay: () => void; speed: number; onSpeed: (s: number) => void;
}) {
  const W = 600, H = 60, P = 160;
  const t0 = t - WAVE_WIN / 2;
  const lines = useMemo(() => {
    if (!A || !runs.length) return null;
    const src: number[] = [], ear: number[] = [];
    for (let i = 0; i < P; i++) {
      const tt = t0 + (i / (P - 1)) * WAVE_WIN;
      // linear between samples: 2 ms is only 48 of them
      const kf = tt * SR, k0 = Math.floor(kf), fr = kf - k0;
      src.push(runs.reduce((v, r) => v + (k0 >= 0 && k0 + 1 < r.U.length ? r.a * (r.U[k0] + fr * (r.U[k0 + 1] - r.U[k0])) : 0), 0));
      ear.push(pointAt(runs, tt, step, cell));
    }
    const path = (v: number[]) => { const m = Math.max(1e-12, ...v.map(Math.abs)); return v.map((y, i) => `${i ? "L" : "M"}${(i / (P - 1)) * W},${H / 2 - (y / m) * (H / 2 - 6)}`).join(""); };
    return { src: path(src), ear: path(ear) };
  }, [A, runs, t0, step, cell]);
  // drag moves t by the pixels dragged, at this window's scale (µs per pixel)
  const drag = useRef<{ x: number; t: number } | null>(null);
  const ticks = [-1, -0.5, 0, 0.5, 1];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr)", gap: "4px 14px", alignItems: "center" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {playBtn(playing, "Slow motion", onPlay, "play-slow")}
        <select data-testid="speed" aria-label="Slow motion speed" value={speed} onChange={(e) => onSpeed(+e.target.value)}
          style={{ background: "transparent", color: INK, border: "1px solid rgba(255,255,255,0.18)", borderRadius: 6, padding: "3px 4px", fontSize: 11 }}>
          {SPEEDS.map((s) => <option key={s} value={s} style={{ color: "#111" }}>{s.toLocaleString()}× slower</option>)}
        </select>
      </div>
      <svg data-testid="wave-timeline" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ ...card, height: H, cursor: "ew-resize", touchAction: "none" }}
        onPointerDown={(e) => { drag.current = { x: e.clientX, t }; (e.currentTarget as Element).setPointerCapture(e.pointerId); }}
        onPointerMove={(e) => { const d = drag.current; if (!d) return; const w = (e.currentTarget as Element).getBoundingClientRect().width; onSeek(d.t - ((e.clientX - d.x) / w) * WAVE_WIN); }}
        onPointerUp={() => { drag.current = null; }}>
        {ticks.map((m) => <line key={m} x1={(0.5 + m / 2) * W} x2={(0.5 + m / 2) * W} y1={0} y2={H} stroke="#eceae6" vectorEffect="non-scaling-stroke" />)}
        <line x1={0} x2={W} y1={H / 2} y2={H / 2} stroke="#eceae6" vectorEffect="non-scaling-stroke" />
        {lines && <path d={lines.src} fill="none" stroke="#9aa0a8" strokeWidth={1.2} strokeDasharray="3 2" vectorEffect="non-scaling-stroke" />}
        {lines && <path d={lines.ear} fill="none" stroke={EAR} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />}
        <line x1={W / 2} x2={W / 2} y1={0} y2={H} stroke="#111" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      </svg>
      <span />
      <span style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 11, color: MUTED, fontVariantNumeric: "tabular-nums" }}>
        <span>−1 ms</span>
        <span><span style={{ color: "#9aa0a8" }}>- - clip at the speaker</span> · <span style={{ color: INK }}>— pressure at {probe}</span> · each scaled to fit · 1 ms takes {(speed / 1000).toLocaleString()} s</span>
        <span>+1 ms</span>
      </span>
    </div>
  );
}

const chartBox = (title: string, note: string, body: React.ReactNode, testid: string) => (
  <div data-testid={testid}>
    <p style={label}>{title}</p>
    {body}
    <p style={{ fontSize: 11, color: MUTED, margin: "6px 0 0", lineHeight: 1.45 }}>{note}</p>
  </div>
);

/** Short-time SII over the whole clip, one line per listener, playhead at t. */
function SiiChart({ A, t, conds, onSeek }: { A: ClipAnalysis | null; t: number; conds: Cond[]; onSeek: (t: number) => void }) {
  const W = 360, H = 120, pl = 34, pb = 16;
  const scrub = useScrub((f) => A && onSeek(f * A.duration));
  const x = (i: number) => pl + (i / Math.max(1, (A?.frames ?? 2) - 1)) * (W - pl - 4);
  const y = (v: number) => 6 + (1 - v) * (H - pb - 6);
  const now = A ? Math.min(A.frames - 1, Math.max(0, Math.floor((t * SR - WIN / 2) / HOP))) : 0;
  return chartBox("Speech heard over the clip", "Short-time SII on 43 ms frames: gaps between words drop to 0. The big number above is the whole clip.", (
    <svg viewBox={`0 0 ${W} ${H}`} {...scrub} style={{ ...card, ...scrub.style }}>
      {[0, 0.5, 1].map((v) => (
        <g key={v}><line x1={pl} x2={W - 4} y1={y(v)} y2={y(v)} stroke="#eceae6" /><text x={pl - 4} y={y(v) + 3} fontSize={9} fill={CARD_INK} textAnchor="end">{v * 100}%</text></g>
      ))}
      {A && conds.map((c) => {
        const v = A.sii[c];
        return v && <path key={c} d={v.map((s, i) => `${i ? "L" : "M"}${x(i)},${y(s)}`).join("")} fill="none" stroke={COND[c].color} strokeWidth={c === "healthy" ? 1.2 : 1.8} strokeLinejoin="round" />;
      })}
      {A && <line x1={x(now)} x2={x(now)} y1={4} y2={H - pb} stroke="#111" strokeWidth={1.2} />}
      {A && conds.map((c) => A.sii[c] && <circle key={c} cx={x(now)} cy={y(A.sii[c]![now])} r={3} fill={COND[c].color} stroke="#fff" strokeWidth={1.2} />)}
      <text x={pl} y={H - 4} fontSize={9} fill={CARD_INK}>0 s</text>
      <text x={W - 4} y={H - 4} fontSize={9} fill={CARD_INK} textAnchor="end">{A ? `${A.duration.toFixed(1)} s` : ""}</text>
    </svg>
  ), "chart-sii");
}

/** Audibility per band over time for the chosen listener: grey where the band is below threshold or masked. */
function Spectrogram({ A, t, cond, onSeek }: { A: ClipAnalysis | null; t: number; cond: Cond; onSeek: (t: number) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const aud = A?.aud[cond];
    if (!A || !aud) return;
    const c = canvas.current!, nb = SII_FREQS.length;
    c.width = A.frames; c.height = nb;
    const ctx = c.getContext("2d")!, img = ctx.createImageData(A.frames, nb);
    for (let f = 0; f < A.frames; f++) for (let b = 0; b < nb; b++) {
      const v = (aud[f][b] + 15) / 30, o = ((nb - 1 - b) * A.frames + f) * 4;   // low bands at the bottom
      img.data.set(v <= 0 ? [236, 233, 228, 255] : [255 - (255 - UP[0]) * v, 255 - (255 - UP[1]) * v, 255 - (255 - UP[2]) * v, 255], o);
    }
    ctx.putImageData(img, 0, 0);
  }, [A, cond]);
  const scrub = useScrub((f) => A && onSeek(f * A.duration));
  return chartBox(`What ${cond === "healthy" ? "normal hearing" : cond === "aided" ? "you hear with the aid" : "you hear"}, per band`,
    "SII audibility per one-third-octave band, 160 Hz (bottom) to 8 kHz (top): grey is below threshold or masked, full orange is 30 dB above.", (
      <div {...scrub} style={{ position: "relative", ...scrub.style }}>
        <canvas ref={canvas} style={{ ...card, height: 108, imageRendering: "pixelated" }} />
        {A && <div style={{ position: "absolute", top: 0, bottom: 0, left: `${(t / A.duration) * 100}%`, width: 1.5, background: "#111" }} />}
        <span style={{ position: "absolute", left: 6, top: 4, fontSize: 9, color: CARD_INK }}>8k</span>
        <span style={{ position: "absolute", left: 6, bottom: 4, fontSize: 9, color: CARD_INK }}>160</span>
      </div>
    ), "chart-spectrogram");
}

/** The frame under the playhead: how far above threshold each band is, this listener filled, normal hearing outlined. */
function NowChart({ A, frame, cond }: { A: ClipAnalysis | null; frame: number; cond: Cond }) {
  const W = 360, H = 110, pl = 26, pb = 16, nb = SII_FREQS.length, bw = (W - pl - 4) / nb;
  const y = (v: number) => 6 + (1 - v / 30) * (H - pb - 6);
  const mine = A?.aud[cond]?.[frame], ref = A?.aud.healthy?.[frame];
  return chartBox("Right now, per band", "dB above threshold in this frame (0–30). Outline: the same frame with normal hearing.", (
    <svg viewBox={`0 0 ${W} ${H}`} style={card}>
      {[0, 15, 30].map((v) => <g key={v}><line x1={pl} x2={W - 4} y1={y(v)} y2={y(v)} stroke="#eceae6" /><text x={pl - 4} y={y(v) + 3} fontSize={9} fill={CARD_INK} textAnchor="end">{v}</text></g>)}
      {SII_FREQS.map((f, b) => {
        const x = pl + b * bw;
        const m = mine ? mine[b] + 15 : 0, r = ref ? ref[b] + 15 : 0;
        return (
          <g key={f}>
            {m > 0 && <rect x={x + 2} y={y(m)} width={bw - 4} height={y(0) - y(m)} rx={1.5} fill={COND[cond].color} />}
            {cond !== "healthy" && r > 0 && <rect x={x + 1.5} y={y(r)} width={bw - 3} height={y(0) - y(r)} rx={1.5} fill="none" stroke="#8a8f98" strokeWidth={1} strokeDasharray="2 1.5" />}
            {b % 3 === 0 && <text x={x + bw / 2} y={H - 4} fontSize={9} fill={CARD_INK} textAnchor="middle">{fmtHz(f)}</text>}
          </g>
        );
      })}
    </svg>
  ), "chart-now");
}

/** The tile's strip: speech heard across the whole clip, you (and with the aid), normal hearing faint behind. */
export function ClipStrip({ A }: { A: ClipAnalysis | null }) {
  const W = 260, H = 28;
  if (!A) return <div style={{ height: H }} />;
  const x = (i: number) => (i / Math.max(1, A.frames - 1)) * W, y = (v: number) => 2 + (1 - v) * (H - 4);
  const line = (v?: number[]) => v?.map((s, i) => `${i ? "L" : "M"}${x(i)},${y(s)}`).join("") ?? "";
  return (
    <svg data-testid="sim-strip" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: H, display: "block", marginTop: 6 }}
      aria-label="Speech heard across the clip">
      <title>Speech heard across the clip: normal hearing (grey), you (orange){A.sii.aided ? ", with the aid (blue)" : ""}</title>
      <path d={line(A.sii.healthy)} fill="none" stroke="rgba(255,255,255,0.28)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      <path d={line(A.sii.you)} fill="none" stroke={COND.you.color} strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
      {A.sii.aided && <path d={line(A.sii.aided)} fill="none" stroke={COND.aided.color} strokeWidth={1.4} vectorEffect="non-scaling-stroke" />}
    </svg>
  );
}
