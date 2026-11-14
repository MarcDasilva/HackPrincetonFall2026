"use client";
// n×n live scenes over one patient's ear. Each speaker direction is one FDTD run in a worker
// (shared across scenes and cached); its eardrum spectrum over the frontal reference is that
// source's direction filter, which feeds the SII deficit of its scene; the weighted deficits make
// the target vector. "Design earpiece" sends the scenes to the backend (hornsim.scene_design):
// target triage, a sweep of the earpiece family, the best buildable design, and its gain G(f),
// which comes back to score every scene aided.
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import Aggregate, { type SceneRow } from "./Aggregate";
import SceneCell, { type CellStatus } from "./SceneCell";
import { AVERAGE_ID, designStatus, fetchGrid, startDesign, startWaveCheck, waveStatus, type DesignStatus, type GridWithPatient, type WaveStatus } from "./lib/api";
import { bandGainDb } from "./lib/bands";
import { decodeSolid } from "./lib/fdtd";
import { EXAMPLE_AUDIOGRAM, sceneDeficit, targetGain, toAudiogram } from "./lib/hearing";
import { SimPool } from "./lib/pool";
import { defaultScenes, dirKey, newSource, PRESETS, sceneFromPreset, type Scene } from "./lib/scenes";
import styles from "./sim.module.css";

const REF = dirKey(0, 0);

/** Pressure-slice frames per speaker direction, kept so every scene can replay (and superpose) them. */
export class FrameStore {
  private frames = new Map<string, Float32Array[]>();
  add(key: string, slice: Float32Array) { (this.frames.get(key) ?? this.frames.set(key, []).get(key)!).push(slice); }
  reset(key: string) { this.frames.set(key, []); }
  get(key: string) { return this.frames.get(key); }
}

export default function SimGrid() {
  const [pid, setPid] = useState<string | null>(null);
  const [grid, setGrid] = useState<GridWithPatient | null>(null);
  const [offline, setOffline] = useState<string | null>(null);   // backend unreachable: static average ear, no design
  const [n, setN] = useState(3);
  const [scenes, setScenes] = useState<Scene[]>(() => defaultScenes(9));
  const [spectra, setSpectra] = useState<Record<string, number[]>>({});
  const pending = useRef(new Set<string>());
  const [error, setError] = useState<string | null>(null);
  const store = useMemo(() => new FrameStore(), []);
  const solid = useMemo(() => (grid ? decodeSolid(grid) : null), [grid]);
  const [pool, setPool] = useState<SimPool | null>(null);
  const [design, setDesign] = useState<DesignStatus>({ status: "none" });
  const [designStale, setDesignStale] = useState(false);
  const [wave, setWave] = useState<WaveStatus>({ status: "none" });

  // ?patient=<12-hex id>; default: the average ear
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("patient");
    setPid(q && /^[a-f0-9]{12}$/.test(q) ? q : AVERAGE_ID);
  }, []);
  useEffect(() => {
    if (!pid) return;
    setGrid(null); setSpectra({}); setDesign({ status: "none" }); setAgEdit(null);
    fetchGrid(pid).then((g) => { setGrid(g); setOffline(null); }, (e) => {
      if (pid !== AVERAGE_ID) { setError(`patient ${pid}: ${e.message}`); return; }
      setOffline(String(e.message));
      fetch("/sim/ear_grid.json").then((r) => (r.ok ? r.json() : Promise.reject(new Error(`ear grid: HTTP ${r.status}`)))).then(setGrid, (e2) => setError(String(e2)));
    });
    // a design saved earlier came from whatever scenes were sent then: show it, flagged as possibly stale
    designStatus(pid).then((s) => { if (s.status === "done") { setDesign(s); setDesignStale(true); } }, () => {});
    waveStatus(pid).then((w) => { if (w.status === "done") setWave(w); }, () => {});
  }, [pid]);
  useEffect(() => {
    if (!grid) return;
    const p = new SimPool(grid, Math.max(1, Math.min(8, (navigator.hardwareConcurrency || 4) - 1)));
    pending.current = new Set(); // in-flight keys belong to one pool (dev StrictMode builds two)
    setPool(p);
    return () => p.dispose();
  }, [grid]);
  const poolState = useSyncExternalStore(
    useCallback((fn: () => void) => pool?.subscribe(fn) ?? (() => {}), [pool]),
    () => (pool ? `${pool.busy}/${pool.size}/${pool.queued}` : "0/0/0"),
    () => "0/0/0",
  );

  // the patient's audiogram, editable here to explore (edits are local and go with the design request)
  const [agEdit, setAgEdit] = useState<Record<string, number> | null>(null);
  const agBase = useMemo(() => grid?.patient?.audiogram_db_hl ?? Object.fromEntries(Object.entries(EXAMPLE_AUDIOGRAM).map(([k, v]) => [String(k), v])), [grid]);
  const audiogramRaw = agEdit ?? agBase;
  const audiogram = useMemo(() => toAudiogram(audiogramRaw), [audiogramRaw]);

  const request = useCallback((owner: string, az: number, el: number) => {
    const key = dirKey(az, el);
    const inflight = pending.current;
    if (!pool || inflight.has(key)) return;
    inflight.add(key);
    const [a, e] = key.split(",").map(Number);
    store.reset(key);
    pool.run(owner, a, e, (_, slice) => store.add(key, slice)).then(
      (spec) => setSpectra((s) => ({ ...s, [key]: spec })),
      () => {},
    ).finally(() => inflight.delete(key));
  }, [pool, store]);

  // run every direction a visible scene needs that is neither cached nor in flight
  const visible = scenes.slice(0, n * n);
  const [commitTick, setCommitTick] = useState(0);
  useEffect(() => {
    if (!pool) return;
    request("ref", 0, 0);
    for (const s of visible) for (const src of s.sources) if (!spectra[dirKey(src.az, src.el)]) request(s.id, src.az, src.el);
    // spectra only adds keys; re-running on it would only re-check the same cache
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pool, commitTick, n, request]);

  const update = (id: string, f: (s: Scene) => Scene) => { setScenes((ss) => ss.map((s) => (s.id === id ? f(s) : s))); setDesignStale(true); };
  const commit = () => setCommitTick((t) => t + 1);

  const ref = spectra[REF];
  const G = design.status === "done" ? design.result?.design.gain_mean_db : undefined;
  const results = useMemo(() => visible.map((s) => {
    if (!ref) return null;
    const srcs = s.sources.map((src) => {
      const sp = spectra[dirKey(src.az, src.el)];
      return sp ? { ...src, gainDb: bandGainDb(sp, ref) } : null;
    });
    if (srcs.some((x) => !x)) return null;
    return sceneDeficit(srcs as NonNullable<(typeof srcs)[number]>[], audiogram, G);
  }), [visible, spectra, ref, audiogram, G]);

  const status = (s: Scene): CellStatus => {
    const keys = [...new Set(s.sources.map((x) => dirKey(x.az, x.el)))];
    const done = keys.filter((k) => spectra[k]).length + (ref ? 1 : 0), total = keys.length + 1;
    if (done === total) return { state: "done", done, total };
    return { state: keys.some((k) => pending.current.has(k)) ? "running" : "queued", done, total };
  };

  const agg = useMemo(() => {
    const ok = visible.map((s, i) => ({ s, r: results[i] })).filter((x) => x.r && x.s.weight > 0);
    const t = targetGain(ok.map((x) => x.r!.deficit), ok.map((x) => x.s.weight), audiogram);
    const W = ok.reduce((a, x) => a + x.s.weight, 0) || 1;
    const rows: SceneRow[] = visible.map((s, i) => ({
      id: s.id, name: s.name, weight: s.weight,
      contribution: results[i] ? results[i]!.deficit.map((d) => (s.weight / W) * d) : null,
      siiHealthy: results[i]?.siiHealthy, siiUnaided: results[i]?.siiUnaided, siiAided: results[i]?.siiAided,
    }));
    return { ...t, rows };
  }, [visible, results, audiogram]);

  const allKeys = new Set([REF, ...visible.flatMap((s) => s.sources.map((x) => dirKey(x.az, x.el)))]);
  const complete = [...allKeys].filter((k) => spectra[k]).length;
  const ready = complete === allKeys.size;

  // design: send each visible scene's deficit + weight; poll until the backend finishes
  const poll = useRef<number | null>(null);
  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current); }, []);
  const runDesign = async () => {
    if (!pid || !ready) return;
    const payload = visible.map((s, i) => ({ s, r: results[i] })).filter((x) => x.r && x.s.weight > 0)
      .map(({ s, r }) => ({ id: s.id, name: s.name, weight: s.weight, deficit_db: r!.deficit, deficit_weighted: r!.deficitWeighted }));
    setDesign({ status: "queued", log: [] });
    setDesignStale(false);
    setWave({ status: "none" });
    try {
      await startDesign(pid, audiogramRaw, payload);
    } catch (e) { setDesign({ status: "error", error: (e as Error).message }); return; }
    if (poll.current) window.clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      try {
        const s = await designStatus(pid);
        setDesign(s);
        if (s.status === "done" || s.status === "error") { window.clearInterval(poll.current!); poll.current = null; }
      } catch { /* transient: keep polling */ }
    }, 1000);
  };

  // 3D wave check of the current design: the earpiece voxelized into hornsim.wavesim, aided vs open
  const wavePoll = useRef<number | null>(null);
  useEffect(() => () => { if (wavePoll.current) window.clearInterval(wavePoll.current); }, []);
  const runWave = async () => {
    if (!pid) return;
    setWave({ status: "queued", log: [] });
    try { await startWaveCheck(pid); } catch (e) { setWave({ status: "error", error: (e as Error).message }); return; }
    if (wavePoll.current) window.clearInterval(wavePoll.current);
    wavePoll.current = window.setInterval(async () => {
      try {
        const w = await waveStatus(pid);
        setWave(w);
        if (w.status === "done" || w.status === "error") { window.clearInterval(wavePoll.current!); wavePoll.current = null; }
      } catch { /* transient */ }
    }, 2000);
  };

  const resize = (m: number) => {
    setN(m);
    setScenes((ss) => (ss.length >= m * m ? ss : [...ss, ...defaultScenes(m * m).slice(ss.length)]));
    setCommitTick((t) => t + 1);
    setDesignStale(true);
  };

  if (error) return <p className={styles.error}>{error}</p>;
  if (!grid || !solid || !pid) return <p className={styles.loading}>Loading ear grid…</p>;
  const [busy, size, queued] = poolState.split("/").map(Number);
  const pt = grid.patient;

  return (
    <div className={styles.layout}>
      <section className={styles.main}>
        <header className={styles.toolbar}>
          <h1>Scene grid</h1>
          <label>grid
            <select value={n} onChange={(e) => resize(+e.target.value)}>
              {[1, 2, 3, 4].map((m) => <option key={m} value={m}>{m}×{m}</option>)}
            </select>
          </label>
          <label>add preset
            <select value="" onChange={(e) => { const c = e.target.value; if (!c) return; setScenes((ss) => { const out = [...ss]; out.splice(Math.max(0, n * n - 1), 0, sceneFromPreset(c)); return out; }); setCommitTick((t) => t + 1); setDesignStale(true); }}>
              <option value="">—</option>
              {PRESETS.map((p) => <option key={p.condition} value={p.condition} disabled={!p.make}>{p.condition} {p.name}{p.why ? ` (${p.why})` : ""}</option>)}
            </select>
          </label>
          <form className={styles.patient} onSubmit={(e) => { e.preventDefault(); const v = String(new FormData(e.currentTarget).get("pid") ?? "").trim(); if (/^[a-f0-9]{12}$/.test(v)) { window.history.replaceState(null, "", `?patient=${v}`); setPid(v); } }}>
            <label>patient <input name="pid" defaultValue={pid === AVERAGE_ID ? "" : pid} placeholder="average ear" size={13} /></label>
          </form>
          <fieldset className={styles.audiogram}>
            <legend>audiogram dB HL</legend>
            {Object.keys(audiogramRaw).sort((a, b) => +a - +b).map((f) => (
              <label key={f}>{+f >= 1000 ? `${+f / 1000}k` : f}
                <input type="number" min={-10} max={120} step={5} value={audiogramRaw[f]}
                  onChange={(e) => { setAgEdit({ ...audiogramRaw, [f]: Number(e.target.value) }); setDesignStale(true); }} />
              </label>
            ))}
            {agEdit && <button type="button" className={styles.btn} onClick={() => { setAgEdit(null); setDesignStale(true); }}>reset</button>}
          </fieldset>
          <span className={styles.num}>workers {busy}/{size} busy · {queued} queued</span>
          <span className={styles.note}>
            {grid.ear} · {pt?.side ?? "right"} · {grid.dx_mm} mm grid · speakers at {grid.radius_mm} mm ·{" "}
            {agEdit ? "edited audiogram" : pt && !pt.audiogram_is_example ? "patient audiogram" : "example audiogram (placeholder)"}
            {offline && <> · backend offline ({offline}): designing is disabled</>}
          </span>
        </header>
        <div className={styles.cells} style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
          {visible.map((s, i) => (
            <SceneCell key={s.id} grid={grid} solid={solid} scene={s} status={status(s)}
              siiHealthy={results[i]?.siiHealthy} siiUnaided={results[i]?.siiUnaided} siiAided={results[i]?.siiAided}
              store={store}
              onMove={(sid, az, el) => update(s.id, (x) => ({ ...x, sources: x.sources.map((q) => (q.id === sid ? { ...q, az, el } : q)) }))}
              onCommit={commit}
              onChange={(ns) => update(s.id, () => ns)}
              onRemoveSource={(sid) => update(s.id, (x) => ({ ...x, sources: x.sources.filter((q) => q.id !== sid) }))}
              onAddSource={(role) => { update(s.id, (x) => ({ ...x, sources: [...x.sources, newSource(role)] })); setCommitTick((t) => t + 1); }}
            />
          ))}
        </div>
      </section>
      <Aggregate rows={agg.rows} target={agg.target} need={agg.need} nal={agg.nal} complete={complete} total={allKeys.size}
        pid={pid} design={design} designStale={designStale} canDesign={ready && !offline} onDesign={runDesign}
        wave={wave} onWaveCheck={runWave} />
    </div>
  );
}
