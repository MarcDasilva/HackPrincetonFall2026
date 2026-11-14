"use client";

import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import s from "./demo.module.css";
import MeshView from "./MeshView";
import { Plot, ColorBar, path, at, viridis, rdbu, hz, FREQ_TICKS, INK, MUTED, SERIES } from "./charts";
import { asset, picked, CONDITIONS, type Manifest, type Scene, type Triplet } from "./manifest";

const f1 = (v: number) => v.toFixed(1);
const pct = (v: number) => `${Math.round(v * 100)}%`;
const FREQ = { domain: [112, 9000] as [number, number], log: true, ticks: FREQ_TICKS, fmt: hz, label: "Frequency (Hz)" };
// Audiology convention: right ear red, left ear blue.
const EAR_COLOR: Record<string, string> = { right: "#b2182b", left: "#2166ac" };

export function Plate({ title, sub, className = "span6", children }: { title: string; sub?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section className={`${s.plate} ${s[className]}`}>
      <h3>{title}</h3>
      {sub && <p className={s.sub}>{sub}</p>}
      {children}
    </section>
  );
}

const Missing = ({ title, what, className }: { title: string; what: string; className?: string }) => (
  <Plate title={title} className={className}>
    <div className={s.missing}>Not in this manifest yet: {what}.</div>
  </Plate>
);

const Head = ({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) => (
  <header className={s.beatHead}>
    <div>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
    {aside}
  </header>
);

const Legend = ({ items }: { items: [string, string, string?][] }) => (
  <div className={s.legend}>
    {items.map(([label, color, dash]) => (
      <span key={label}><i className={s.swatch} style={{ borderColor: color, borderTopStyle: dash ? "dashed" : "solid" }} />{label}</span>
    ))}
  </div>
);

const yTicks = (lo: number, hi: number, step: number) => Array.from({ length: Math.round((hi - lo) / step) + 1 }, (_, i) => lo + i * step);
const span = (vals: number[], step: number, pad = 0): [number, number] =>
  [Math.floor((Math.min(...vals) - pad) / step) * step, Math.ceil((Math.max(...vals) + pad) / step) * step];

// ---------- 1 · Ear and waves ----------

function WaveViewer({ url }: { url?: string }) {
  const [up, setUp] = useState<boolean | null>(null);
  useEffect(() => {
    if (!url) return;
    // no-cors resolves for any reachable server and rejects ONLY when the backend is down — the iframe would otherwise show the browser's error page.
    fetch(url, { mode: "no-cors" }).then(() => setUp(true), () => setUp(false));
  }, [url]);
  if (!url || up === false)
    return <div className={s.missing} style={{ minHeight: 420 }} data-testid="wave-placeholder">
      {url ? <>The wave viewer is served from {url}, which is not reachable right now.<br />Every other panel runs from the manifest alone.</> : "No wave viewer in this manifest."}
    </div>;
  if (up === null) return <div className={s.missing} style={{ minHeight: 420 }}>Connecting to the wave viewer…</div>;
  return <iframe className={s.iframe} src={url} title="Wave simulation viewer" data-testid="wave-iframe" />;
}

export function EarBeat({ m }: { m: Manifest }) {
  const p = m.patient, e = m.ear;
  const params = e?.params ?? {};
  const rows: [string, string, string][] = [
    ["concha_depth_mm", "Concha depth", "mm"], ["opening_area_mm2", "Concha opening", "mm²"], ["bowl_volume_cc", "Bowl volume", "cc"],
    ["max_coil_mm", "Longest coil that fits", "mm"], ["max_mouth_mm2", "Largest mouth", "mm²"],
  ];
  return (
    <>
      <Head title="Their ear">One photo becomes a 3D ear. A simulated speaker shows how sound wraps around this pinna and into the canal.</Head>
      <Plate title={p?.is_average_ear ? "Average ear (not this patient's)" : "Reconstructed ear"} className="span4"
        sub={p && <>{p.side} ear · scale from {p.scale_source === "coin" ? "the coin in the photo" : "the default ear height"}</>}>
        <MeshView url={asset(m, e?.mesh)} label="3D ear mesh" height={300} />
        <dl className={s.kv} style={{ marginTop: 10 }}>
          {rows.filter(([k]) => params[k] != null).map(([k, label, unit]) => (
            <Fragment key={k}><dt>{label}</dt><dd>{f1(params[k])} {unit}</dd></Fragment>
          ))}
          {e?.canal_band && <>
            <dt>Residual canal</dt>
            <dd>{e.canal_band.volume_cc.map((v) => v.toFixed(2)).join("–")} cc, {e.canal_band.samples} samples{e.canal_band.diameter_mm ? `, ${e.canal_band.diameter_mm} mm wide (assumed)` : ""}</dd>
          </>}
        </dl>
        <p className={s.note}>A photo cannot see the canal, so its size is sampled, not measured.</p>
      </Plate>
      <Plate title="Wave simulation" className="span8"
        sub={m.waves?.directions && <>Eardrum peak by speaker direction: {m.waves.directions.map((d) => `${d.az}° ${hz(d.eardrum_peak_hz)}Hz`).join(" · ")}</>}>
        <WaveViewer url={asset(m, m.waves?.viewer)} />
      </Plate>
    </>
  );
}

// ---------- 2 and 6 · the 96-tile grid ----------

function Grid({ scenes, fill, mark, selected, onSelect }: {
  scenes: Scene[]; fill: (sc: Scene) => string | null; mark?: (sc: Scene) => boolean; selected?: number; onSelect: (id: number) => void;
}) {
  const rows = useMemo(() => {
    const by = new Map<string, Scene[]>();
    for (const sc of scenes) by.set(sc.condition, [...(by.get(sc.condition) ?? []), sc]);
    return [...by.entries()].sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }));
  }, [scenes]);
  return (
    <div className={s.grid} role="grid" aria-label="Listening scenes">
      {rows.map(([cond, row]) => (
        <div key={cond} role="row" style={{ display: "contents" }}>
          <div className={s.rowLabel} title={CONDITIONS[cond]}>
            <span className={s.long}>{cond} {CONDITIONS[cond] ?? ""}<small>{row[0].level_db} dB</small></span>
            <span className={s.short}>{cond}</span>
          </div>
          {row.map((sc) => {
            const bg = fill(sc);
            return (
              <button key={sc.id} className={s.tile} data-testid="tile" data-done={bg !== null} aria-pressed={selected === sc.id}
                style={bg ? { background: bg } : undefined} onClick={() => onSelect(sc.id)}
                title={`Scene ${sc.id} · ${cond} · ${sc.clip} · canal ${sc.canal}`}>
                {sc.neurograms && <i className={s.dot} />}
                {mark?.(sc) && <span className={s.x}>×</span>}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

const gapOf = (sc: Scene) => (sc.deficit_db ? sc.deficit_db.reduce((a, b) => a + b, 0) : null);

function SceneFacts({ sc }: { sc: Scene }) {
  const noise = sc.noise ? `${sc.noise.type}${sc.noise.deg != null ? ` from ${sc.noise.deg}°` : ""}${sc.noise.snr_db != null ? `, ${sc.noise.snr_db > 0 ? "+" : ""}${sc.noise.snr_db} dB SNR` : ""}` : "none";
  const gap = gapOf(sc);
  return (
    <dl className={s.kv}>
      <dt>Scene</dt><dd>{sc.id} · {sc.condition} {CONDITIONS[sc.condition] ?? ""}</dd>
      <dt>Speech</dt><dd>{sc.clip}, {sc.level_db} dB SPL, talker at {sc.talker_deg}°</dd>
      <dt>Noise</dt><dd>{noise}</dd>
      <dt>Canal sample</dt><dd>#{sc.canal} · weight {pct(sc.weight)}</dd>
      {gap !== null && <><dt>Audibility gap</dt><dd>{f1(gap)} dB</dd></>}
      {sc.sii?.unaided != null && <><dt>SII</dt><dd>{sc.sii.unaided.toFixed(2)} without a device{sc.sii.pick != null && ` · ${sc.sii.pick.toFixed(2)} with the pick`}</dd></>}
    </dl>
  );
}

function Neurograms({ m, sc, keys }: { m: Manifest; sc: Scene; keys: [keyof Triplet, string][] }) {
  const ax = m.neurogram_axes;
  if (!sc.neurograms) return <p className={s.note}>Neurograms are drawn for one showcase scene per condition, marked with a dot.</p>;
  return (
    <div className={s.neuro}>
      {keys.filter(([k]) => sc.neurograms?.[k]).map(([k, label]) => (
        <figure key={k}>
          <figcaption>{label}</figcaption>
          <img src={asset(m, sc.neurograms![k])} alt={`${label} neurogram, scene ${sc.id}`} />
          <div className={s.axis}>{ax ? <><span>{ax.t_s[0]} s</span><span>time</span><span>{ax.t_s[1]} s</span></> : <span>time →</span>}</div>
        </figure>
      ))}
      <p className={s.note} style={{ gridColumn: "1 / -1", margin: 0 }}>
        Rows are auditory nerve fibres by characteristic frequency{ax ? `, ${hz(ax.cf_hz[0])}–${hz(ax.cf_hz[1])}Hz` : ""}, low at the bottom; brighter means more firing.
      </p>
    </div>
  );
}

export function LaunchBeat({ m }: { m: Manifest }) {
  const scenes = m.scenes;
  const tl = m.baseline_timeline;
  const [elapsed, setElapsed] = useState(0);
  const [run, setRun] = useState(0);
  const [sel, setSel] = useState<number>();
  const done = useMemo(() => new Map(tl?.map((t) => [t.scene, t.t_ms])), [tl]);
  const end = tl?.length ? tl[tl.length - 1].t_ms : 0;
  useEffect(() => {
    if (!end) return;
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      setElapsed(Math.min(end, now - t0));
      if (now - t0 < end) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [end, run]);
  if (!scenes) return <><Head title="Launch">96 listening scenes run through a healthy ear and theirs, with no device.</Head><Missing title="Scene grid" what="scenes (spec 05)" className="span12" /></>;
  const gaps = scenes.map(gapOf).filter((g): g is number => g !== null);
  const max = gaps.length ? Math.ceil(Math.max(...gaps) / 5) * 5 : 1;
  const finished = tl ? tl.filter((t) => t.t_ms <= elapsed).length : scenes.length;
  const cur = scenes.find((x) => x.id === sel);
  return (
    <>
      <Head title="Launch">{scenes.length} listening scenes from their life, each run through a healthy ear and through theirs with no device. Each tile is one scene; colour is how much speech they miss.</Head>
      <Plate title="Scene grid" className="span8" sub={<>Rows: the {new Set(scenes.map((x) => x.condition)).size} conditions. Tiles: 3 clips × 4 canal samples.</>}>
        <div className={s.toolbar}>
          {tl ? <>
            <span data-testid="launch-clock">{finished} / {scenes.length} finished · {(elapsed / 1000).toFixed(1)} s of {(end / 1000).toFixed(1)} s, replayed at recorded timing</span>
            <button className={s.btn} onClick={() => setRun((r) => r + 1)}>Replay</button>
          </> : <span>No launch timing in this manifest; showing final state.</span>}
        </div>
        <Grid scenes={scenes} selected={sel} onSelect={setSel}
          fill={(sc) => (tl && !(done.get(sc.id)! <= elapsed) ? null : gapOf(sc) === null ? "#c9ccd1" : viridis(gapOf(sc)! / max))} />
        <div style={{ marginTop: 12 }}>
          <ColorBar scale={viridis} domain={[0, max]} ticks={[0, max / 2, max]} label="Audibility gap, importance-weighted (dB)" />
        </div>
      </Plate>
      <Plate title={cur ? `Scene ${cur.id}` : "Pick a tile"} className="span4" sub={!cur && "Click any tile for its details and, on showcase scenes (dot), the nerve response of each ear."}>
        {cur && <>
          <SceneFacts sc={cur} />
          <Neurograms m={m} sc={cur} keys={[["healthy", "Healthy ear"], ["unaided", "Their ear, no device"]]} />
        </>}
      </Plate>
    </>
  );
}

// ---------- 3 · Target ----------

export function TargetBeat({ m }: { m: Manifest }) {
  const ag = m.ear?.audiogram, t = m.target, oe = m.waves?.open_ear;
  const side = m.patient?.side ?? "right";
  const yMax = ag ? Math.max(80, Math.ceil((Math.max(...ag.map((a) => a[1])) + 10) / 10) * 10) : 80;
  const verdict = t?.triage && <span className={s.badge} style={{ borderColor: "#9aa0a8", color: "#e6e8eb", background: "rgba(255,255,255,0.06)" }}>Triage: {t.triage}</span>;
  return (
    <>
      <Head title="Target" aside={verdict}>Where the gain has to go. The target comes from the gap in every scene, weighted by what matters to them, and capped by a standard prescription.</Head>
      {ag ? (
        <Plate title="Audiogram" className="span5" sub={<>{side} ear{m.patient?.audiogram_is_example ? " · example audiogram, not a measured one" : ""}</>}>
          <Plot x={FREQ} y={{ domain: [-10, yMax], ticks: yTicks(-10, yMax, 10), reverse: true, label: "Hearing threshold (dB HL)" }} height={300}
            readout={(x) => `${hz(Math.round(x))}Hz: ${f1(at(ag.map((a) => a[0]), ag.map((a) => a[1]), x))} dB HL`}>
            {({ sx, sy }) => <>
              <rect x={0} y={sy(-10)} width={sx(9000)} height={sy(25) - sy(-10)} fill="#eef3ec" />
              <text x={6} y={sy(25) - 4} fill={MUTED} fontSize={10}>normal range</text>
              <path d={path(ag.map((a) => a[0]), ag.map((a) => a[1]), sx, sy)} stroke={EAR_COLOR[side]} strokeWidth={2} fill="none" />
              {ag.map(([f, db]) => side === "left"
                ? <path key={f} d={`M${sx(f) - 4},${sy(db) - 4}l8,8m0,-8l-8,8`} stroke={EAR_COLOR[side]} strokeWidth={2} />
                : <circle key={f} cx={sx(f)} cy={sy(db)} r={4.5} fill="#fbfbfa" stroke={EAR_COLOR[side]} strokeWidth={2} />)}
            </>}
          </Plot>
          <p className={s.note}>{side === "left" ? "× marks the left ear" : "○ marks the right ear"}, following audiogram convention. Lower on the chart is worse hearing.</p>
        </Plate>
      ) : <Missing title="Audiogram" what="ear.audiogram" className="span5" />}
      {t ? (() => {
        const ys = [...t.gain_db, ...(t.reach_db ?? []), ...(oe?.gain_db.filter((_, i) => oe.freqs_hz[i] <= 8000) ?? []), 0];
        const [lo, hi] = span(ys, 5, 1);
        return (
          <Plate title="Gain needed against what fits" className="span7" sub="All curves in dB. The open-ear curve is the boost their own ear already gives; the target is extra gain over the open ear.">
            <Plot x={FREQ} y={{ domain: [lo, hi], ticks: yTicks(lo, hi, 5), label: "Gain (dB)" }} height={300}
              readout={(x) => [`${hz(Math.round(x))}Hz`, `target ${f1(at(t.freqs_hz, t.gain_db, x))}`, t.reach_db && `reach ${f1(at(t.freqs_hz, t.reach_db, x))}`, oe && `open ear ${f1(at(oe.freqs_hz, oe.gain_db, x))}`].filter(Boolean).join(" · ")}>
              {({ sx, sy }) => <>
                <line x1={0} x2={sx(9000)} y1={sy(0)} y2={sy(0)} stroke={MUTED} />
                {oe && <path d={path(oe.freqs_hz, oe.gain_db, sx, sy)} stroke={SERIES[0]} strokeWidth={1.5} fill="none" />}
                {t.reach_db && <path d={path(t.freqs_hz, t.reach_db, sx, sy)} stroke={INK} strokeWidth={1.5} strokeDasharray="5 4" fill="none" />}
                <path d={path(t.freqs_hz, t.gain_db, sx, sy)} stroke={INK} strokeWidth={2.5} fill="none" />
                {t.freqs_hz.map((f, i) => <circle key={f} cx={sx(f)} cy={sy(t.gain_db[i])} r={2.5} fill={INK} />)}
              </>}
            </Plot>
            <Legend items={[["Target insertion gain T(f)", INK], ...(t.reach_db ? [["Most a horn that fits can give", INK, "dash"] as [string, string, string]] : []), ...(oe ? [[`Open ear, natural gain at the eardrum (speaker at ${oe.az}°)`, SERIES[0]] as [string, string]] : [])]} />
          </Plate>
        );
      })() : <Missing title="Target" what="target (spec 06)" className="span7" />}
    </>
  );
}

// ---------- 4 · Search ----------

function AgentLog({ m, className = "span6" }: { m: Manifest; className?: string }) {
  if (!m.agent?.length) return null;
  return (
    <Plate title="Agent" className={className} sub="It explains results and adjusts the search inputs. Code computes every score and the pick.">
      <ol className={s.agent}>{m.agent.map((a) => <li key={a.round}><b>Round {a.round}</b><span>{a.line}</span></li>)}</ol>
    </Plate>
  );
}

export function SearchBeat({ m }: { m: Manifest }) {
  const tr = m.tradeoff, pick = picked(m), gc = pick?.gain_curves, t = m.target;
  return (
    <>
      <Head title="Search">Thousands of horn shapes on the fast acoustic model. More gain usually costs more boom on their own voice; the pick sits on the best tradeoff.</Head>
      {tr ? (() => {
        const xs = tr.cloud.map((p) => p[0]), ys = tr.cloud.map((p) => p[1]);
        const [x0, x1] = span(xs, 2), [y0, y1] = span(ys, 2);
        return (
          <Plate title="Candidate designs" className="span6" sub={`${tr.cloud.length.toLocaleString()} designs evaluated across the canal samples`}>
            <Plot x={{ domain: [x0, x1], ticks: yTicks(x0, x1, 2), label: "Own-voice boom at 250 Hz (dB)" }} y={{ domain: [y0, y1], ticks: yTicks(y0, y1, 2), label: "Net gain in target band (dB)" }} height={300}>
              {({ sx, sy, w }) => <>
                {tr.cloud.map(([b, g], i) => <circle key={i} cx={sx(b)} cy={sy(g)} r={2} fill="#9aa0a8" fillOpacity={0.45} />)}
                <path d={path(tr.front.map((p) => p[0]), tr.front.map((p) => p[1]), sx, sy)} stroke={INK} strokeWidth={2} fill="none" />
                {pick?.point && <g>
                  <circle cx={sx(pick.point[0])} cy={sy(pick.point[1])} r={7} fill="none" stroke={SERIES[1]} strokeWidth={2.5} />
                  <text x={sx(pick.point[0]) + (sx(pick.point[0]) > w - 110 ? -11 : 11)} y={sy(pick.point[1]) + 18} textAnchor={sx(pick.point[0]) > w - 110 ? "end" : "start"} fill={INK} stroke="#fbfbfa" strokeWidth={3} paintOrder="stroke">pick, design {pick.id}</text>
                </g>}
              </>}
            </Plot>
            <Legend items={[["Every design", "#9aa0a8"], ["Best tradeoff (non-dominated)", INK], ...(pick?.point ? [["The pick", SERIES[1]] as [string, string]] : [])]} />
          </Plate>
        );
      })() : <Missing title="Candidate designs" what="tradeoff (spec 08)" />}
      {gc ? (() => {
        const all = [...gc.mean, ...(gc.canals?.flat() ?? []), ...(t?.gain_db ?? [])];
        const [lo, hi] = span(all, 2, 0.5);
        return (
          <Plate title={`Design ${pick!.id} across ${gc.canals?.length ?? 0} canal samples`} className="span6" sub="Insertion gain over the open ear. One thin line per sampled canal the photo cannot see.">
            <Plot x={FREQ} y={{ domain: [lo, hi], ticks: yTicks(lo, hi, 2), label: "Insertion gain (dB)" }} height={300}
              readout={(x) => `${hz(Math.round(x))}Hz · mean ${f1(at(gc.freqs_hz, gc.mean, x))} dB${gc.canals ? ` · canals ${f1(Math.min(...gc.canals.map((c) => at(gc.freqs_hz, c, x))))} to ${f1(Math.max(...gc.canals.map((c) => at(gc.freqs_hz, c, x))))}` : ""}`}>
              {({ sx, sy }) => <>
                <line x1={0} x2={sx(9000)} y1={sy(0)} y2={sy(0)} stroke={MUTED} />
                {gc.canals?.map((c, i) => <path key={i} d={path(gc.freqs_hz, c, sx, sy)} stroke={SERIES[0]} strokeOpacity={0.28} strokeWidth={1} fill="none" />)}
                {t && <path d={path(t.freqs_hz, t.gain_db, sx, sy)} stroke={INK} strokeWidth={1.5} strokeDasharray="5 4" fill="none" />}
                <path d={path(gc.freqs_hz, gc.mean, sx, sy)} stroke={INK} strokeWidth={2.5} fill="none" />
              </>}
            </Plot>
            <Legend items={[["Mean", INK], ...(gc.canals ? [["Each canal sample", SERIES[0]] as [string, string]] : []), ...(t ? [["Target T(f)", INK, "dash"] as [string, string, string]] : [])]} />
          </Plate>
        );
      })() : <Missing title="Gain across canals" what="designs[pick].gain_curves (spec 08)" />}
      {m.designs && m.designs.length > 1 && (
        <Plate title="Top designs" className="span6" sub="Scored on all scenes by the hearing check. The pick is chosen by code.">
          <table className={s.card}>
            <thead><tr><th>Design</th><th>Gap closed</th><th>Scenes worse</th><th>Score</th></tr></thead>
            <tbody>{m.designs.map((d) => (
              <tr key={d.id} style={String(d.id) === String(m.pick) ? { fontWeight: 600 } : undefined}>
                <td>{d.id}{String(d.id) === String(m.pick) ? " (pick)" : ""}</td>
                <td>{d.gap_closed != null ? pct(d.gap_closed) : "–"}</td>
                <td>{d.harm_rate != null ? pct(d.harm_rate) : "–"}</td>
                <td>{d.score != null ? d.score.toFixed(2) : "–"}</td>
              </tr>
            ))}</tbody>
          </table>
        </Plate>
      )}
      <AgentLog m={m} />
    </>
  );
}

// ---------- 5 · Fit ----------

export function CardTable({ m }: { m: Manifest }) {
  const c = m.card;
  if (!c) return <div className={s.missing}>No prescription card in this manifest yet.</div>;
  const b = c.bore, v = c.vent;
  const rows: [string, ReactNode][] = [
    ["Triage", c.triage],
    ["Target band", c.target_band_hz && `${hz(c.target_band_hz[0])}–${hz(c.target_band_hz[1])}Hz`],
    ["Net gain over open ear", c.net_gain_db && `${f1(c.net_gain_db.peak)} dB at ${hz(c.net_gain_db.peak_hz)}Hz · worst canal ${f1(c.net_gain_db.canal_worst)} dB`],
    ["Bore", b && [b.throat_mm2 != null && `throat ${b.throat_mm2} mm²`, b.mouth_mm2 != null && `mouth ${b.mouth_mm2} mm²`, b.length_mm != null && `${b.length_mm} mm long`, b.turns != null && `${b.turns} turns`, b.flare].filter(Boolean).join(" · ")],
    ["Vent", v && [`${v.count} × ${v.diameter_mm} mm`, v.boom_250hz_db != null && `boom at 250 Hz ${f1(v.boom_250hz_db)} dB`, v.cost_500hz_db != null && `at 500 Hz ${f1(v.cost_500hz_db)} dB`].filter(Boolean).join(" · ")],
    ["Print tolerance", c.print_tolerance && `throat ±${c.print_tolerance.throat_mm} mm keeps gain within ±${c.print_tolerance.gain_db} dB`],
    ["Personalized", c.personalized?.join(", ")],
    ["Standard", c.standard?.join(", ")],
    ["Scenes made worse", c.harm && `${c.harm.scenes} of ${c.harm.of}`],
    ["Gap closed", c.gap_closed && `${pct(c.gap_closed.mean)} weighted mean · ${pct(c.gap_closed.worst)} worst scene`],
  ];
  return (
    <table className={s.card} data-testid="card">
      <tbody>{rows.filter(([, val]) => val).map(([k, val]) => <tr key={k}><th>{k}</th><td>{val}</td></tr>)}</tbody>
    </table>
  );
}

export function FitBeat({ m }: { m: Manifest }) {
  const pick = picked(m);
  return (
    <>
      <Head title="Fit">The picked horn seats in their concha. The coiled bore (orange) and vent (blue) show through the shell.</Head>
      <Plate title={pick ? `Design ${pick.id} in their ear` : "Horn in ear"} className="span7" sub="Drag to rotate. Ear and shell drawn see-through.">
        <MeshView url={asset(m, pick?.mesh)} snap label="Horn seated in the ear" height={420} />
      </Plate>
      <Plate title="Prescription card" className="span5" sub="Every value comes from the run. Predictions from simulation; fitting on a real ear still has to be checked.">
        <CardTable m={m} />
      </Plate>
    </>
  );
}

// ---------- 6 · Proof ----------

export function ProofBeat({ m }: { m: Manifest }) {
  const scenes = m.scenes;
  const firstAudio = scenes?.find((x) => x.audio)?.id;
  const [sel, setSel] = useState<number | undefined>(firstAudio);
  const scored = scenes?.filter((x) => x.sii?.pick != null && x.sii.unaided != null) ?? [];
  if (!scenes || !scored.length)
    return <><Head title="Proof">The same scenes again, with the horn.</Head><Missing title="Hearing check" what="scenes[].sii.pick (spec 10)" className="span12" /></>;
  const d = (x: Scene) => x.sii!.pick! - x.sii!.unaided!;
  const lim = Math.max(0.05, Math.ceil(Math.max(...scored.map((x) => Math.abs(d(x)))) / 0.05) * 0.05);
  const worse = scenes.filter((x) => x.harm).length;
  const cur = scenes.find((x) => x.id === sel);
  return (
    <>
      <Head title="Proof">The same {scenes.length} scenes with the picked horn. Blue got easier to follow, red got harder. Far-side talkers and noise on the aided side show where a passive horn cannot help.</Head>
      <Plate title="Change with the pick" className="span7" sub={`${worse} of ${scenes.length} scenes worse than with no device (×)`}>
        <Grid scenes={scenes} selected={sel} onSelect={setSel} mark={(x) => !!x.harm}
          fill={(x) => (x.sii?.pick != null && x.sii.unaided != null ? rdbu(d(x) / lim) : "#c9ccd1")} />
        <div style={{ marginTop: 12 }}>
          <ColorBar scale={rdbu} domain={[-lim, lim]} ticks={[-lim, 0, lim]} fmt={(v) => (v < 0 ? `${v.toFixed(2)} worse` : v > 0 ? `+${v.toFixed(2)} better` : "0")}
            label="SII change, aided minus unaided" />
        </div>
      </Plate>
      <Plate title={cur ? `Listen · scene ${cur.id}` : "Listen"} className="span5" sub={cur ? `${cur.condition} ${CONDITIONS[cur.condition] ?? ""}` : "Pick a showcase tile (dot) to hear it."}>
        {cur && <>
          {cur.audio ? (
            <div className={s.audio}>
              {([["healthy", "Healthy ear"], ["unaided", "Their ear, no device"], ["aided", "Their ear, with the horn"]] as const).filter(([k]) => cur.audio![k]).map(([k, label]) => (
                <label key={k}>{label}<audio controls preload="none" src={asset(m, cur.audio![k])} /></label>
              ))}
              <p className={s.note} style={{ margin: 0 }}>Played through a hearing-loss simulator, so a listener with normal hearing hears what they would.</p>
            </div>
          ) : <p className={s.note}>Audio is rendered for showcase scenes only (dot).</p>}
          <Neurograms m={m} sc={cur} keys={[["healthy", "Healthy"], ["unaided", "No device"], ["aided", "With the horn"]]} />
        </>}
      </Plate>
      <AgentLog m={m} className="span12" />
    </>
  );
}

// ---------- 7 · Second patient ----------

export function CompareBeat({ a, b }: { a: Manifest; b?: Manifest | null }) {
  if (!b) return <><Head title="Second patient">Same pipeline, a different ear and audiogram.</Head>
    <Plate title="No second manifest" className="span12"><div className={s.missing}>Add ?compare=&lt;manifest url&gt; to the address to show a second patient here.</div></Plate></>;
  const both = [a, b];
  const name = (m: Manifest, i: number) => `Patient ${"AB"[i]}${m.patient ? ` · ${m.patient.side} ear` : ""}`;
  const ags = both.map((m) => m.ear?.audiogram ?? []);
  const yMax = Math.max(80, Math.ceil((Math.max(...ags.flat().map((p) => p[1])) + 10) / 10) * 10);
  const gcs = both.map((m) => picked(m)?.gain_curves);
  const [glo, ghi] = span(gcs.flatMap((g) => g?.mean ?? [0]), 2, 0.5);
  return (
    <>
      <Head title="Second patient">Same pipeline, a different ear and audiogram, a different earpiece.</Head>
      {both.map((m, i) => (
        <Plate key={i} title={name(m, i)} className="span6" sub={picked(m) ? `Design ${picked(m)!.id}${m.patient?.is_average_ear ? " · average ear" : ""}` : undefined}>
          <MeshView url={asset(m, picked(m)?.mesh ?? m.ear?.mesh)} snap={!!picked(m)?.mesh} label={`${name(m, i)} ear and horn`} height={280} />
          <CardTable m={m} />
        </Plate>
      ))}
      <Plate title="Audiograms" className="span6">
        <Plot x={FREQ} y={{ domain: [-10, yMax], ticks: yTicks(-10, yMax, 10), reverse: true, label: "Hearing threshold (dB HL)" }} height={260}>
          {({ sx, sy }) => ags.map((ag, i) => <g key={i}>
            <path d={path(ag.map((p) => p[0]), ag.map((p) => p[1]), sx, sy)} stroke={SERIES[i]} strokeWidth={2} fill="none" />
            {ag.map(([f, db]) => <circle key={f} cx={sx(f)} cy={sy(db)} r={3.5} fill="#fbfbfa" stroke={SERIES[i]} strokeWidth={2} />)}
          </g>)}
        </Plot>
        <Legend items={both.map((m, i) => [name(m, i), SERIES[i]] as [string, string])} />
      </Plate>
      <Plate title="Picked horn, mean insertion gain" className="span6">
        <Plot x={FREQ} y={{ domain: [glo, ghi], ticks: yTicks(glo, ghi, 2), label: "Insertion gain (dB)" }} height={260}>
          {({ sx, sy }) => <>
            <line x1={0} x2={sx(9000)} y1={sy(0)} y2={sy(0)} stroke={MUTED} />
            {gcs.map((g, i) => g && <path key={i} d={path(g.freqs_hz, g.mean, sx, sy)} stroke={SERIES[i]} strokeWidth={2} fill="none" />)}
          </>}
        </Plot>
        <Legend items={both.map((m, i) => [name(m, i), SERIES[i]] as [string, string])} />
      </Plate>
    </>
  );
}
