"use client";

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

// SAME scales as the wave viewer (backend/hornsim/wave_viewer.html): viridis for level, ColorBrewer RdBu for signed change.
const VIRIDIS = ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"];
const RDBU = ["#b2182b", "#d6604d", "#f4a582", "#fddbc7", "#f7f7f7", "#d1e5f0", "#92c5de", "#4393c3", "#2166ac"];

const ramp = (stops: string[]) => (t: number) => {
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const [a, b] = [stops[i], stops[i + 1]].map((h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16)));
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * (x - i))).join(",")})`;
};
export const viridis = ramp(VIRIDIS);
/** t in [-1, 1]: -1 red, 0 neutral grey-white, +1 blue. */
export const rdbu = (t: number) => ramp(RDBU)((t + 1) / 2);

export const INK = "#1d1f23", MUTED = "#5d636c", GRID = "#e4e6e9", PLATE = "#fbfbfa";
// Two categorical hues (patient A/B, measured vs reference curves); passes the dataviz CVD validator on PLATE. Single-series lines use INK.
export const SERIES = ["#2563eb", "#c2410c"];

export const hz = (f: number) => (f >= 1000 ? `${+(f / 1000).toFixed(f % 1000 ? 1 : 0)}k` : `${f}`);
export const FREQ_TICKS = [125, 250, 500, 1000, 2000, 4000, 8000];

export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    if (ref.current) ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

type Axis = { domain: [number, number]; ticks: number[]; label: string; log?: boolean; reverse?: boolean; fmt?: (v: number) => string };
export type Scales = { sx: (v: number) => number; sy: (v: number) => number; w: number; h: number; hover: number | null };

const M = { l: 48, r: 14, t: 10, b: 38 };

/** SVG figure drawn at its real pixel width, so text stays the SAME size on phone and desktop. `readout` turns the hovered x into a crosshair label. */
export function Plot({ x, y, height = 240, children, readout }: {
  x: Axis; y: Axis; height?: number; children: (s: Scales) => ReactNode; readout?: (xv: number) => string | null;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hx, setHx] = useState<number | null>(null);
  const w = Math.max(0, width - M.l - M.r), h = height - M.t - M.b;
  const lin = (d: [number, number], r: [number, number], log?: boolean) => {
    const f = log ? Math.log : (v: number) => v;
    return (v: number) => r[0] + ((f(v) - f(d[0])) / (f(d[1]) - f(d[0]))) * (r[1] - r[0]);
  };
  const sx = lin(x.domain, [0, w], x.log);
  const sy = lin(y.domain, y.reverse ? [0, h] : [h, 0]);
  const inv = (px: number) => (x.log ? Math.exp(Math.log(x.domain[0]) + (px / w) * Math.log(x.domain[1] / x.domain[0])) : x.domain[0] + (px / w) * (x.domain[1] - x.domain[0]));
  const text = hx !== null && readout ? readout(hx) : null;
  return (
    <div ref={ref} style={{ width: "100%", position: "relative" }}>
      {width > 0 && (
        <svg width={width} height={height} style={{ display: "block", font: "11px system-ui, sans-serif", fontVariantNumeric: "tabular-nums" }}
          onPointerMove={readout ? (e) => {
            const px = e.clientX - e.currentTarget.getBoundingClientRect().left - M.l;
            setHx(px >= 0 && px <= w ? inv(px) : null);
          } : undefined}
          onPointerLeave={() => setHx(null)}>
          <g transform={`translate(${M.l},${M.t})`}>
            {y.ticks.map((t) => (
              <g key={`y${t}`}>
                <line x1={0} x2={w} y1={sy(t)} y2={sy(t)} stroke={GRID} />
                <text x={-6} y={sy(t)} dy="0.32em" textAnchor="end" fill={MUTED}>{(y.fmt ?? String)(t)}</text>
              </g>
            ))}
            {x.ticks.map((t) => (
              <g key={`x${t}`}>
                <line x1={sx(t)} x2={sx(t)} y1={0} y2={h} stroke={GRID} />
                <text x={sx(t)} y={h + 14} textAnchor="middle" fill={MUTED}>{(x.fmt ?? String)(t)}</text>
              </g>
            ))}
            <rect width={w} height={h} fill="none" stroke="#c9ccd1" />
            <text x={w / 2} y={h + 31} textAnchor="middle" fill={INK}>{x.label}</text>
            <text transform={`translate(${-36},${h / 2}) rotate(-90)`} textAnchor="middle" fill={INK}>{y.label}</text>
            <svg width={w} height={h} overflow="hidden">{children({ sx, sy, w, h, hover: hx })}</svg>
            {text && hx !== null && (
              <g pointerEvents="none">
                <line x1={sx(hx)} x2={sx(hx)} y1={0} y2={h} stroke={MUTED} strokeDasharray="2 3" />
                <text x={Math.min(sx(hx) + 6, w - 4)} y={12} textAnchor={sx(hx) > w - 160 ? "end" : "start"} fill={INK}
                  stroke={PLATE} strokeWidth={3} paintOrder="stroke">{text}</text>
              </g>
            )}
          </g>
        </svg>
      )}
    </div>
  );
}

/** Polyline path from paired arrays; nulls break the line. */
export const path = (xs: number[], ys: (number | null)[], sx: (v: number) => number, sy: (v: number) => number) =>
  xs.map((x, i) => (ys[i] == null ? "" : `${i && ys[i - 1] != null ? "L" : "M"}${sx(x).toFixed(1)},${sy(ys[i]!).toFixed(1)}`)).join("");

/** Value at x on a log-frequency curve, for crosshair readouts. */
export const at = (xs: number[], ys: number[], x: number) => {
  let i = 0;
  while (i < xs.length - 2 && xs[i + 1] < x) i++;
  const t = Math.min(1, Math.max(0, Math.log(x / xs[i]) / Math.log(xs[i + 1] / xs[i])));
  return ys[i] + (ys[i + 1] - ys[i]) * t;
};

export function ColorBar({ scale, domain, ticks, label, fmt = String }: {
  scale: (t: number) => string; domain: [number, number]; ticks: number[]; label: string; fmt?: (v: number) => string;
}) {
  const stops = Array.from({ length: 11 }, (_, i) => `${scale(domain[0] < 0 ? (i / 10) * 2 - 1 : i / 10)} ${i * 10}%`);
  return (
    <figure style={{ margin: 0, maxWidth: 280, width: "100%" }}>
      <figcaption style={{ fontSize: 12, color: INK, marginBottom: 4 }}>{label}</figcaption>
      <div style={{ height: 10, borderRadius: 2, background: `linear-gradient(90deg, ${stops.join(",")})`, border: `1px solid ${GRID}` }} />
      <div style={{ position: "relative", height: 16, fontSize: 11, color: MUTED, fontVariantNumeric: "tabular-nums" }}>
        {ticks.map((t) => {
          const p = ((t - domain[0]) / (domain[1] - domain[0])) * 100;
          return <span key={t} style={{ position: "absolute", left: `${p}%`, transform: `translateX(${p === 0 ? 0 : p === 100 ? -100 : -50}%)`, top: 2, whiteSpace: "nowrap" }}>{fmt(t)}</span>;
        })}
      </div>
    </figure>
  );
}
