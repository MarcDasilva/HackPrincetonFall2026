"use client";

import { useEffect, useMemo, useState } from "react";
import type { Ear } from "@/lib/audiometry";
import { API, type Run } from "@/lib/run";

/** One speaker direction's wave run, as backend/hornsim/wavesim.py writes it to runs.json. */
type WaveRun = { tag: string; az: number; el: number; eardrum_peak_hz: number; transfer: { freqs_hz: number[]; eardrum_db: number[] } };
type EarWaves = { base: string; runs: WaveRun[] };

const EARS: Ear[] = ["left", "right"];
// Audiology convention (left blue, right red), at the steps that clear 3:1 on the dark panel surface — validated with the dataviz palette script.
const COLOR: Record<Ear, string> = { left: "#4393c3", right: "#d6604d" };
const NAME: Record<Ear, string> = { left: "Left", right: "Right" };
const T = { surface: "#1a1a19", raised: "#232322", line: "#3a3a38", ink: "#f0efec", ink2: "#c3c2b7", muted: "#8f8e86" };
const where = (r: WaveRun) => `${({ 0: "Front", 45: "Front-side", 90: "Side", 135: "Back-side", 180: "Behind" } as Record<number, string>)[r.az] ?? "Az"} ${r.az}°`;
const khz = (hz: number) => (hz >= 1000 ? `${(hz / 1000).toFixed(1)} kHz` : `${Math.round(hz)} Hz`);
/** Columns for n boxes in a w×h section: the count whose boxes come closest to `aspect` — 2:1 for two ear viewers side by side (square-ish viewers, never tall slivers), 4:3 for one head viewer. */
const cols = (n: number, w: number, h: number, aspect: number) => {
  let best = 1;
  const off = (c: number) => Math.abs(Math.log(w / c / (h / Math.ceil(n / c)) / aspect));
  for (let c = 2; c <= n; c++) if (off(c) < off(best)) best = c;
  return best;
};

/**
 * The simulations, inside the orb: one bento box per speaker direction, with the eardrum-gain panel on the right. A patient with a head model (files.head.viewer) gets ONE viewer per box — the head with both ears and both wave fields (backend/hornsim/head_viewer.html); an older patient gets the LEFT and RIGHT ear's wave field side by side (backend/hornsim/wave_viewer.html), both in embed mode.
 * Every viewer owns a WebGL context, and Chrome drops the OLDEST past ~16 per page — 5 directions × 2 ears + the dashboard's 2 is the ceiling, so the direction count is capped by the backend's 5 runs, never more.
 */
export default function WaveBento({ run }: { run: Run }) {
  const [waves, setWaves] = useState<Partial<Record<Ear, EarWaves>> | null>(null);
  // The combined head viewer's URL path, or null for a patient from before the head stage.
  const [head, setHead] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  const [focus, setFocus] = useState<string | null>(null);
  // Re-render on resize so cols() re-fits the section.
  const [, setSize] = useState(0);
  useEffect(() => {
    const on = () => setSize(window.innerWidth * 1e5 + window.innerHeight);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  // The run's own files may be stale or absent (the dev shortcut never polls), so read the patient fresh.
  useEffect(() => {
    let live = true;
    (async () => {
      const files: Run["files"] = (await (await fetch(`${API}/api/patients/${run.id}`)).json()).files;
      const out: Partial<Record<Ear, EarWaves>> = {};
      for (const ear of EARS) {
        const url = files?.[ear]?.waves;
        if (!url) continue;
        const base = url.replace(/index\.html$/, "");
        out[ear] = { base, runs: await (await fetch(`${API}${base}runs.json`)).json() };
      }
      if (!live) return;
      if (!out.left && !out.right) throw new Error("This patient has no wave simulations yet.");
      setHead(files?.head?.viewer ?? null);
      setWaves(out);
      setN((out.left ?? out.right)!.runs.length);
    })().catch((e) => live && setErr(e instanceof Error ? e.message : "Could not load the simulations."));
    return () => { live = false; };
  }, [run.id]);

  const dirs = useMemo(() => (waves?.left ?? waves?.right)?.runs ?? [], [waves]);
  if (err) return <p style={{ padding: 24, color: T.ink2 }}>{err}</p>;
  if (!waves) return <p style={{ padding: 24, color: T.muted }}>Loading simulations…</p>;
  // ponytail: the first n directions in the backend's order (front to behind); a spread pick if users want e.g. front + side + behind at n = 3.
  const shown = dirs.slice(0, n);
  const focused = shown.find((d) => d.tag === focus) ?? shown[0];
  const runOf = (ear: Ear, tag: string) => waves[ear]?.runs.find((r) => r.tag === tag);
  // The section is 4/5 of the width minus gutters, and the screen height minus the X strip and header.
  const c = cols(n, (window.innerWidth - 48) * 0.8, window.innerHeight - 110, head ? 4 / 3 : 2);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 4fr) minmax(320px, 1fr)", gap: 16, padding: "0 16px 16px", height: "calc(100vh - 56px)", boxSizing: "border-box", color: T.ink, font: "13px/1.4 system-ui, sans-serif" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0, minHeight: 0 }}>
        <header style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <h1 style={{ fontSize: 18, margin: 0, fontWeight: 600 }}>Simulations</h1>
          <label style={{ display: "flex", gap: 6, alignItems: "center", color: T.ink2 }}>directions
            <select value={n} onChange={(e) => setN(+e.target.value)} style={{ background: T.raised, color: T.ink, border: `1px solid ${T.line}`, borderRadius: 6, padding: "3px 6px" }}>
              {dirs.map((_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}
            </select>
          </label>
          <span style={{ color: T.muted, fontSize: 12 }}>Sound waves from a speaker around each ear. Drag inside a view to turn it.</span>
        </header>
        <div data-testid="wave-boxes" style={{ flex: 1, minHeight: 0, display: "grid", gap: 10, gridTemplateColumns: `repeat(${c}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${Math.ceil(n / c)}, minmax(0, 1fr))` }}>
          {shown.map((d) => (
            <div key={d.tag} data-testid="wave-box" style={{ display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0, background: T.raised, border: `1px solid ${d === focused ? T.muted : T.line}`, borderRadius: 10, overflow: "hidden" }}>
              <button type="button" onClick={() => setFocus(d.tag)} style={{ all: "unset", cursor: "pointer", padding: "6px 10px", borderBottom: `1px solid ${T.line}`, fontWeight: 600 }}>{head ? `Head, ${where(d)}` : where(d)}</button>
              {head ? (
                <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
                  {/* The tag rides URL-encoded: a raw "+" in "el+00" arrives as a space and the viewer falls back to its default direction. */}
                  <iframe title={`Head, ${where(d)}`} src={`${API}${head}?embed=1&run=${encodeURIComponent(d.tag)}`} style={{ width: "100%", height: "100%", border: 0, display: "block" }} />
                  <span style={{ position: "absolute", left: 8, bottom: 6, padding: "1px 7px", borderRadius: 999, background: "rgba(0,0,0,0.6)", color: T.ink, fontSize: 12, pointerEvents: "none" }}>Both ears</span>
                </div>
              ) : (
              <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", minHeight: 0 }}>
                {EARS.map((ear) => (
                  <div key={ear} style={{ position: "relative", minWidth: 0, borderLeft: ear === "right" ? `1px solid ${T.line}` : undefined }}>
                    {waves[ear] ? (
                      <iframe title={`${NAME[ear]} ear, ${where(d)}`} src={`${API}${waves[ear]!.base}index.html?embed=1&run=${encodeURIComponent(d.tag)}`} style={{ width: "100%", height: "100%", border: 0, display: "block" }} />
                    ) : (
                      <div style={{ height: "100%", display: "grid", placeItems: "center", color: T.muted, padding: 12, textAlign: "center" }}>No {NAME[ear].toLowerCase()} ear for this patient.</div>
                    )}
                    {/* Identity is the word, NEVER colour alone; the dot ties it to the chart. */}
                    <span style={{ position: "absolute", left: 8, bottom: 6, display: "flex", alignItems: "center", gap: 5, padding: "1px 7px", borderRadius: 999, background: "rgba(0,0,0,0.6)", color: T.ink, fontSize: 12, pointerEvents: "none" }}>
                      <i style={{ width: 8, height: 8, borderRadius: 999, background: COLOR[ear] }} />{NAME[ear]}
                    </span>
                  </div>
                ))}
              </div>
              )}
            </div>
          ))}
        </div>
      </section>
      <aside data-testid="wave-panel" style={{ alignSelf: "start", maxHeight: "100%", overflow: "auto", background: T.surface, border: `1px solid ${T.line}`, borderRadius: 10, padding: "14px 16px" }}>
        <h2 style={{ fontSize: 15, margin: 0, fontWeight: 600 }}>Gain at the eardrum</h2>
        <p style={{ color: T.ink2, margin: "6px 0 10px", fontSize: 12 }}>{focused && where(focused)}, compared with the same speaker in open air.</p>
        {focused && <GainChart lines={EARS.flatMap((ear) => { const r = runOf(ear, focused.tag); return r ? [{ ear, f: r.transfer.freqs_hz, db: r.transfer.eardrum_db }] : []; })} />}
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 14, fontSize: 12 }}>
          <caption style={{ textAlign: "left", color: T.ink2, fontWeight: 600, marginBottom: 4 }}>Eardrum peak by direction</caption>
          <thead><tr>{["Direction", "Left", "Right"].map((h) => <th key={h} style={{ textAlign: "left", color: T.muted, fontWeight: 500, borderBottom: `1px solid ${T.line}`, padding: "3px 4px" }}>{h}</th>)}</tr></thead>
          <tbody>
            {shown.map((d) => (
              <tr key={d.tag} onClick={() => setFocus(d.tag)} style={{ cursor: "pointer", background: d === focused ? T.raised : undefined }}>
                <td style={{ padding: "3px 4px", color: T.ink }}>{where(d)}</td>
                {EARS.map((ear) => { const r = runOf(ear, d.tag); return <td key={ear} style={{ padding: "3px 4px", color: T.ink2, fontVariantNumeric: "tabular-nums" }}>{r ? khz(r.eardrum_peak_hz) : "—"}</td>; })}
              </tr>
            ))}
          </tbody>
        </table>
      </aside>
    </div>
  );
}

/** Eardrum gain vs frequency, one 2px line per ear on ONE dB axis, log frequency. Direct labels at the line ends plus a legend; the crosshair reads both ears at the hovered frequency. */
function GainChart({ lines }: { lines: { ear: Ear; f: number[]; db: number[] }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 300, H = 170, L = 30, R = 44, Tp = 10, B = 24;
  const all = lines.flatMap((l) => l.db);
  const lo = Math.floor(Math.min(0, ...all) / 5) * 5, hi = Math.ceil(Math.max(10, ...all) / 5) * 5;
  const fx = (f: number) => L + ((Math.log10(f) - 2) / (Math.log10(12000) - 2)) * (W - L - R);
  const fy = (d: number) => Tp + ((hi - d) / (hi - lo)) * (H - Tp - B);
  const f0 = lines[0]?.f ?? [];
  // End labels sorted by height and pushed at least 11px apart — two ears ending at the same gain would print one name over the other.
  const ends = lines.map((l) => ({ ear: l.ear, x: fx(l.f[l.f.length - 1]) + 4, y: fy(l.db[l.db.length - 1]) + 3.5 })).sort((a, b) => a.y - b.y);
  ends.forEach((e, i) => { if (i && e.y - ends[i - 1].y < 11) e.y = ends[i - 1].y + 11; });
  const move = (e: React.PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect(), x = ((e.clientX - box.left) / box.width) * W;
    let best = 0;
    f0.forEach((f, i) => { if (Math.abs(fx(f) - x) < Math.abs(fx(f0[best]) - x)) best = i; });
    setHover(f0.length ? best : null);
  };
  return (
    <div style={{ position: "relative" }}>
      <div style={{ display: "flex", gap: 14, color: T.ink2, fontSize: 12, marginBottom: 4 }}>
        {lines.map((l) => <span key={l.ear}><i style={{ display: "inline-block", width: 14, height: 0, borderTop: `2px solid ${COLOR[l.ear]}`, marginRight: 5, verticalAlign: 3 }} />{NAME[l.ear]} ear</span>)}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Eardrum gain in dB versus frequency, left and right ear" onPointerMove={move} onPointerLeave={() => setHover(null)} style={{ display: "block", touchAction: "none" }}>
        {Array.from({ length: (hi - lo) / 5 + 1 }, (_, k) => lo + k * 5).filter((d) => d % 10 === 0).map((d) => (
          <g key={d}><line x1={L} x2={W - R} y1={fy(d)} y2={fy(d)} stroke={T.line} strokeWidth={d === 0 ? 1.2 : 1} /><text x={L - 5} y={fy(d) + 3.5} fill={T.muted} fontSize="10" textAnchor="end">{d}</text></g>
        ))}
        {[[100, "100"], [1000, "1k"], [10000, "10k"]].map(([f, s]) => <text key={s} x={fx(+f)} y={H - 8} fill={T.muted} fontSize="10" textAnchor="middle">{s}</text>)}
        <text x={L - 5} y={Tp - 1} fill={T.muted} fontSize="9" textAnchor="end">dB</text>
        {lines.map((l) => (
          <path key={l.ear} d={l.f.map((f, i) => `${i ? "L" : "M"}${fx(f).toFixed(1)},${fy(l.db[i]).toFixed(1)}`).join("")} fill="none" stroke={COLOR[l.ear]} strokeWidth="2" strokeLinejoin="round" />
        ))}
        {ends.map(({ ear, x, y }) => <text key={ear} x={x} y={y} fill={T.ink2} fontSize="10">{NAME[ear]}</text>)}
        {hover !== null && (
          <g pointerEvents="none">
            <line x1={fx(f0[hover])} x2={fx(f0[hover])} y1={Tp} y2={H - B} stroke={T.muted} strokeDasharray="2 2" />
            {lines.map((l) => <circle key={l.ear} cx={fx(l.f[hover])} cy={fy(l.db[hover])} r={4} fill={COLOR[l.ear]} stroke={T.surface} strokeWidth={2} />)}
          </g>
        )}
      </svg>
      {hover !== null && (
        <div role="status" style={{ position: "absolute", top: 22, left: `${(Math.min(fx(f0[hover]), W - 110) / W) * 100}%`, pointerEvents: "none", background: "#0f0f0e", border: `1px solid ${T.line}`, borderRadius: 6, padding: "5px 8px", fontSize: 12, color: T.ink, whiteSpace: "nowrap" }}>
          <div>{khz(f0[hover])}</div>
          {lines.map((l) => <div key={l.ear} style={{ color: T.ink2 }}>{NAME[l.ear]}: {l.db[hover].toFixed(1)} dB</div>)}
        </div>
      )}
    </div>
  );
}
