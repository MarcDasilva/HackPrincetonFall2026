"use client";
// The result vector: target insertion gain T(f) per SII band (what the earpiece should deliver),
// the NAL-R cap on it, how much each scene pushes each band, and — once designed — the chosen
// earpiece's gain G(f) mapped onto T(f): how much of each band's target it delivers, and every scene aided.
import { useState } from "react";
import EarpieceView from "./EarpieceView";
import { designFile, type DesignStatus, type WaveStatus } from "./lib/api";
import { SII_FREQS } from "./lib/hearing";
import styles from "./sim.module.css";

export type SceneRow = {
  id: string; name: string; weight: number; contribution: number[] | null;
  siiHealthy?: number; siiUnaided?: number; siiAided?: number;
};

const fmtHz = (f: number) => (f >= 1000 ? `${+(f / 1000).toFixed(2)}k` : `${f}`);
const sgn = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}`;
// sequential blue, stepped for the dark surface: near zero is the darkest step
const SEQ = ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"];

type Props = {
  /** "Left" / "Right": which ear this panel shows */
  ear: string;
  rows: SceneRow[]; target: number[]; need: number[]; nal: number[]; complete: number; total: number;
  pid: string; design: DesignStatus; designStale: boolean; canDesign: boolean;
  /** a design is running for either ear (the button designs both) */
  designing: boolean; onDesign: () => void;
  wave: WaveStatus; onWaveCheck: () => void;
};
// 3D-measured gain, one line per talker direction (categorical slots 3 and 4, fixed order)
const WAVE_COLORS = ["var(--series-3)", "var(--series-4)"];

export default function Aggregate({ ear, rows, target, need, nal, complete, total, pid, design, designStale, canDesign, designing, onDesign, wave, onWaveCheck }: Props) {
  const [hover, setHover] = useState<{ band: number; row?: number; x: number; y: number } | null>(null);
  const res = design.status === "done" ? design.result ?? null : null;
  const G = res?.design.gain_mean_db, Gw = res?.design.gain_worst_db, reach = res?.reach_db;
  const key = new Set(res?.key_bands_hz ?? []);
  const wv = wave.status === "done" && wave.result && wave.result.design_id === res?.design.id ? wave.result : null;
  const waveBusy = wave.status === "queued" || wave.status === "running";

  const W = 420, H = 210, padL = 34, padB = 30, padT = 20, padR = 8;
  const nb = SII_FREQS.length, bw = (W - padL - padR) / nb;
  const hi = Math.max(10, ...nal, ...need, ...(G ?? []), ...(reach ?? []), ...(wv ? wv.wave.flatMap((w) => w.gain_db) : []));
  const lo = Math.min(0, ...(G ?? []), ...(Gw ?? []), ...(wv ? wv.wave.flatMap((w) => w.gain_db) : []));
  const yMax = Math.ceil(hi / 5) * 5, yMin = Math.floor(lo / 5) * 5;
  const y = (v: number) => padT + (H - padT - padB) * (1 - (v - yMin) / (yMax - yMin));
  const step = yMax - yMin > 30 ? 10 : 5;
  const ticks = Array.from({ length: Math.floor((yMax - yMin) / step) + 1 }, (_, i) => yMin + i * step);
  const peak = target.indexOf(Math.max(...target));
  const cx = (i: number) => padL + i * bw + bw / 2;
  const line = (v: number[]) => v.map((g, i) => `${i ? "L" : "M"}${cx(i)},${y(g)}`).join("");

  const live = rows.filter((r) => r.contribution);
  const cMax = Math.max(1e-6, ...live.flatMap((r) => r.contribution!));
  const rowH = 16, hmTop = 4, hmH = hmTop + live.length * rowH + 22, labelW = 118;
  const cw = (W - labelW - padR) / nb;
  const busy = design.status === "queued" || design.status === "running";
  const met = res?.design.met;

  return (
    <aside className={styles.panel}>
      <div className={styles.panelHead}>
        <h2>{ear} ear: target gain for its earpiece</h2>
        <span className={styles.num}>{complete}/{total} runs</span>
      </div>
      <p className={styles.caption}>
        T(f) = scene-weighted mean audibility gap, floored at 0 and capped at NAL-R (hornsim/target.py).
        {target.some((t) => t > 0) && <> Largest need: <b>{target[peak].toFixed(1)} dB at {fmtHz(SII_FREQS[peak])} Hz</b>.</>}
      </p>
      <div className={styles.legend}>
        {G ? <>
          <span><i className={styles.outlineKey} /> target T(f)</span>
          <span><i style={{ background: "var(--series-1)" }} /> delivered by earpiece</span>
        </> : <span><i style={{ background: "var(--series-1)" }} /> target T(f)</span>}
        <span><i className={styles.dash} /> NAL-R cap</span>
        {G && <span><i className={styles.lineKey} /> earpiece G(f){wv ? ", 1D model" : ""}</span>}
        {wv && wv.wave.map((w, k) => <span key={w.az}><i className={styles.lineKey} style={{ borderTopColor: WAVE_COLORS[k] }} /> 3D wave, talker {w.az}°</span>)}
        {reach && <span><i className={styles.dotKey} /> best any design reaches</span>}
      </div>
      <div className={styles.chartWrap}>
        <svg viewBox={`0 0 ${W} ${H}`} className={styles.chart} role="img" aria-label="Target and earpiece insertion gain per band"
          onMouseLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} className={t === 0 ? styles.base : styles.grid} />
              <text x={padL - 6} y={y(t) + 3} className={styles.axis} textAnchor="end">{t}</text>
            </g>
          ))}
          <text x={padL - 6} y={9} className={styles.axis} textAnchor="end">dB</text>
          {SII_FREQS.map((f, i) => {
            const x = padL + i * bw, h = Math.max(0, y(0) - y(target[i]));
            return (
              <g key={f}>
                {h > 0 && !G && <path d={roundTop(x + 2, y(target[i]), bw - 4, h, Math.min(4, h))} fill="var(--series-1)" />}
                {h > 0 && G && <path d={roundTop(x + 2.5, y(target[i]), bw - 5, h, Math.min(4, h))} className={styles.targetOutline} />}
                {G && G[i] > 0 && target[i] > 0 && (() => {
                  const d = Math.min(G[i], target[i]), hh = y(0) - y(d);
                  return <path d={roundTop(x + 2, y(d), bw - 4, hh, Math.min(4, hh))} fill="var(--series-1)" />;
                })()}
                <line x1={x + 1} x2={x + bw - 1} y1={y(nal[i])} y2={y(nal[i])} className={styles.cap} />
                {key.has(f) && <path d={`M${cx(i) - 4},${H - padB + 4}l4,5l4,-5z`} className={met?.[i] ? styles.keyMet : styles.keyMark} />}
                {i % 3 === 0 && <text x={cx(i)} y={H - 6} className={styles.axis} textAnchor="middle">{fmtHz(f)}</text>}
              </g>
            );
          })}
          {reach && <path d={line(reach)} className={styles.reach} />}
          {G && <path d={line(G)} className={styles.gain} />}
          {G && G.map((g, i) => <circle key={i} cx={cx(i)} cy={y(g)} r={2.6} className={styles.gainDot} />)}
          {wv && wv.wave.map((w, k) => (
            <g key={w.az}>
              <path d={line(w.gain_db)} fill="none" stroke={WAVE_COLORS[k]} strokeWidth={2} strokeLinejoin="round" />
              {w.gain_db.map((g, i) => <circle key={i} cx={cx(i)} cy={y(g)} r={2.4} fill={WAVE_COLORS[k]} stroke="var(--surface-1)" strokeWidth={1.5} />)}
            </g>
          ))}
          {SII_FREQS.map((f, i) => (
            <rect key={f} x={padL + i * bw} y={padT} width={bw} height={H - padT - padB} fill="transparent"
              onMouseMove={(e) => setHover({ band: i, x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })} />
          ))}
        </svg>
        {hover && hover.row === undefined && (
          <div className={styles.tip} style={{ left: Math.min(hover.x + 12, 250), top: hover.y }}>
            <b>{fmtHz(SII_FREQS[hover.band])} Hz{key.has(SII_FREQS[hover.band]) ? " · key band" : ""}</b>
            <div>target {target[hover.band].toFixed(1)} dB (need {need[hover.band].toFixed(1)}, cap {nal[hover.band].toFixed(1)})</div>
            {G && Gw && <div>earpiece {sgn(G[hover.band])} dB (worst canal {sgn(Gw[hover.band])})</div>}
            {reach && <div>best any design {sgn(reach[hover.band])} dB</div>}
            {wv && wv.wave.map((w) => <div key={w.az}>3D wave, {w.az}°: {sgn(w.gain_db[hover.band])} dB</div>)}
            {live.map((r) => ({ r, v: r.contribution![hover.band] })).sort((a, b) => b.v - a.v).slice(0, 3).map(({ r, v: c }) => (
              <div key={r.id} className={styles.tipRow}>{r.name}: {c.toFixed(1)} dB</div>
            ))}
          </div>
        )}
      </div>
      {key.size > 0 && <p className={styles.caption}>▾ key bands (filled when the earpiece meets them)</p>}

      <div className={styles.designBar}>
        <button className={styles.primary} disabled={!canDesign || designing} onClick={onDesign}>
          {designing ? "Designing both…" : res ? "Redesign both earpieces" : "Design both earpieces"}
        </button>
        {res && !busy && (
          <button className={styles.btn} disabled={waveBusy} onClick={onWaveCheck}>
            {waveBusy ? "3D wave sim running…" : wv ? `Re-check ${ear.toLowerCase()} in 3D` : `Check ${ear.toLowerCase()} with 3D wave sim`}
          </button>
        )}
        {busy && <span className={styles.caption}>{design.log?.at(-1)?.slice(9) ?? "queued"}</span>}
        {waveBusy && <span className={styles.caption}>{wave.log?.at(-1)?.slice(9) ?? "queued"}</span>}
        {!busy && res && designStale && <span className={styles.caption}>scenes changed</span>}
      </div>
      {design.status === "error" && <p className={styles.errorBox}>{ear} earpiece design failed: {design.error}</p>}
      {wave.status === "error" && <p className={styles.errorBox}>3D wave check failed: {wave.error}</p>}
      {res?.design.files["earpiece_in_ear.glb"] && (
        <>
          <EarpieceView url={designFile(pid, res.design.id, "earpiece_in_ear.glb")} />
          <div className={styles.links}>
            {res.design.files["earpiece_print.stl"] && <a href={designFile(pid, res.design.id, "earpiece_print.stl")}>Download {ear.toLowerCase()} print STL</a>}
            {res.design.files["earpiece.glb"] && <a href={designFile(pid, res.design.id, "earpiece.glb")}>earpiece.glb</a>}
          </div>
        </>
      )}

      <h3 className={styles.sub}>What each scene adds (weight × deficit, dB)</h3>
      <div className={styles.chartWrap}>
        <svg viewBox={`0 0 ${W} ${hmH}`} className={styles.chart} role="img" aria-label="Per-scene contribution heatmap"
          onMouseLeave={() => setHover(null)}>
          {live.map((r, k) => (
            <g key={r.id}>
              <text x={0} y={hmTop + k * rowH + 11} className={styles.rowLabel}>{r.name.length > 18 ? r.name.slice(0, 17) + "…" : r.name}</text>
              {r.contribution!.map((c, i) => (
                <rect key={i} x={labelW + i * cw + 1} y={hmTop + k * rowH + 1} width={cw - 2} height={rowH - 2} rx={2}
                  fill={SEQ[Math.min(SEQ.length - 1, Math.round((Math.max(0, c) / cMax) * (SEQ.length - 1)))]}
                  onMouseMove={(e) => setHover({ band: i, row: k, x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })} />
              ))}
            </g>
          ))}
          {SII_FREQS.map((f, i) => i % 3 === 0 && (
            <text key={f} x={labelW + i * cw + cw / 2} y={hmTop + live.length * rowH + 14} className={styles.axis} textAnchor="middle">{fmtHz(f)}</text>
          ))}
        </svg>
        {hover && hover.row !== undefined && live[hover.row] && (
          <div className={styles.tip} style={{ left: Math.min(hover.x + 12, 250), top: hover.y }}>
            <b>{live[hover.row].name}</b>
            <div>{fmtHz(SII_FREQS[hover.band])} Hz: {live[hover.row].contribution![hover.band].toFixed(2)} dB</div>
          </div>
        )}
      </div>

      <table className={styles.table}>
        <thead><tr><th>Scene</th><th>weight</th><th>SII healthy</th><th>this ear</th>{G && <th>aided</th>}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td><td>{r.weight}</td><td>{r.siiHealthy?.toFixed(2) ?? "…"}</td><td>{r.siiUnaided?.toFixed(2) ?? "…"}</td>
              {G && <td>{r.siiAided !== undefined && r.siiUnaided !== undefined ? <>{r.siiAided.toFixed(2)} <span className={styles.delta}>({sgn((r.siiAided - r.siiUnaided) * 100).replace(".0", "")} pts)</span></> : "…"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      <details className={styles.vector}>
        <summary>Target vector (18 bands, dB)</summary>
        <code>{JSON.stringify(Object.fromEntries(SII_FREQS.map((f, i) => [f, +target[i].toFixed(2)])))}</code>
      </details>
    </aside>
  );
}

/** bar with rounded top corners, square at the baseline */
function roundTop(x: number, y: number, w: number, h: number, r: number) {
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}
