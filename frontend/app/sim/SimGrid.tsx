"use client";
// n×n live scenes around a dummy head wearing BOTH of the patient's ears. Each talker direction is
// one FDTD run in a worker (a far talker's plane wave; shared across scenes and cached) that
// records both eardrums. Per ear, a source's eardrum spectrum over the frontal one is its direction
// filter, which feeds that ear's SII deficit for the scene; the weighted deficits make each ear's
// target vector. "Design both earpieces" sends each ear's scenes to the backend
// (hornsim.scene_design, one patient record per ear): target triage, a sweep of the earpiece
// family, the best buildable design and its gain G(f), which comes back to score every scene aided.
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import Aggregate, { type SceneRow } from "./Aggregate";
import HeadPhoto from "./HeadPhoto";
import SceneCell, { type CellStatus, type EarSii } from "./SceneCell";
import { AVERAGE_IDS, designStatus, fetchHead, isAverage, startDesign, startWaveCheck, waveStatus, type DesignStatus, type HeadWithPatients, type WaveStatus } from "./lib/api";
import { bandGainDb } from "./lib/bands";
import { decodeSolid, SIDES, type Side } from "./lib/fdtd";
import { EXAMPLE_AUDIOGRAM, sceneDeficit, targetGain, toAudiogram } from "./lib/hearing";
import { SimPool, type EarSpectra } from "./lib/pool";
import { defaultScenes, dirKey, newSource, PRESETS, sceneFromPreset, type Scene } from "./lib/scenes";
import styles from "./sim.module.css";

const REF = dirKey(0, 0);
const ID_RE = /^[a-f0-9]{12}$/;
const LABEL: Record<Side, string> = { left: "Left", right: "Right" };
const perEar = <T,>(f: (s: Side) => T): Record<Side, T> => ({ left: f("left"), right: f("right") });

/** Pressure-slice frames per talker direction, kept so every scene can replay (and superpose) them. */
export class FrameStore {
  private frames = new Map<string, Float32Array[]>();
  add(key: string, slice: Float32Array) { (this.frames.get(key) ?? this.frames.set(key, []).get(key)!).push(slice); }
  reset(key: string) { this.frames.set(key, []); }
  get(key: string) { return this.frames.get(key); }
}

/** ?left=<id>&right=<id>&head=<shape id>: both ear scans and a front photo's head shape are required.
 * None given: the average ear on both sides and the average head (a demo, labelled as such). */
function idsFromUrl(): { ids: Record<Side, string> | null; head: string | null; error: string | null } {
  const q = new URLSearchParams(window.location.search);
  const l = q.get("left"), r = q.get("right"), h = q.get("head");
  const head = h && ID_RE.test(h) ? h : null;
  if (!l && !r) return { ids: { ...AVERAGE_IDS }, head, error: null };
  if (!l || !r || !ID_RE.test(l) || !ID_RE.test(r))
    return { ids: null, head, error: "Both ear scans are needed: open /sim?left=<left ear patient id>&right=<right ear patient id>." };
  return { ids: { left: l, right: r }, head, error: null };
}

const urlFor = (ids: Record<Side, string>, head: string | null) => {
  const q = new URLSearchParams();
  if (!isAverage(ids.left) || !isAverage(ids.right)) { q.set("left", ids.left); q.set("right", ids.right); }
  if (head) q.set("head", head);
  return `?${q.toString()}`;
};

export default function SimGrid() {
  const [ids, setIds] = useState<Record<Side, string> | null>(null);
  const [head, setHead] = useState<string | null>(null);         // head shape id from a front photo; null = average head
  const [photoOpen, setPhotoOpen] = useState(false);
  const [grid, setGrid] = useState<HeadWithPatients | null>(null);
  const [offline, setOffline] = useState<string | null>(null);   // backend unreachable: static average head, no design
  const [n, setN] = useState(3);
  const [scenes, setScenes] = useState<Scene[]>(() => defaultScenes(9));
  const [spectra, setSpectra] = useState<Record<string, EarSpectra>>({});
  const pending = useRef(new Set<string>());
  const [error, setError] = useState<string | null>(null);
  const store = useMemo(() => new FrameStore(), []);
  const solid = useMemo(() => (grid ? decodeSolid(grid) : null), [grid]);
  const [pool, setPool] = useState<SimPool | null>(null);
  const [design, setDesign] = useState<Record<Side, DesignStatus>>(perEar(() => ({ status: "none" })));
  const [designStale, setDesignStale] = useState(false);
  const [wave, setWave] = useState<Record<Side, WaveStatus>>(perEar(() => ({ status: "none" })));
  const [ear, setEar] = useState<Side>("right");     // which ear the side panel shows

  useEffect(() => {
    const { ids: v, head: h, error: e } = idsFromUrl();
    setHead(h);
    if (e) setError(e); else setIds(v);
  }, []);
  // a real patient's ears need their own head too: no simulation on the average head for them
  const needsHead = !!ids && !head && (!isAverage(ids.left) || !isAverage(ids.right));
  useEffect(() => {
    if (!ids || needsHead) return;
    setGrid(null); setSpectra({}); setDesign(perEar(() => ({ status: "none" }))); setWave(perEar(() => ({ status: "none" }))); setAgEdit(perEar(() => null));
    fetchHead(ids, head).then((g) => { setGrid(g); setOffline(null); }, (e) => {
      if (!isAverage(ids.left) || !isAverage(ids.right) || head) { setError(`ears ${ids.left} / ${ids.right}${head ? `, head ${head}` : ""}: ${e.message}`); return; }
      setOffline(String(e.message));
      fetch("/sim/head_grid.json").then((r) => (r.ok ? r.json() : Promise.reject(new Error(`head grid: HTTP ${r.status}`)))).then(setGrid, (e2) => setError(String(e2)));
    });
    // designs saved earlier came from whatever scenes were sent then: show them, flagged as possibly stale
    for (const s of SIDES) {
      designStatus(ids[s]).then((d) => { if (d.status === "done") { setDesign((x) => ({ ...x, [s]: d })); setDesignStale(true); } }, () => {});
      waveStatus(ids[s]).then((w) => { if (w.status === "done") setWave((x) => ({ ...x, [s]: w })); }, () => {});
    }
  }, [ids, head, needsHead]);
  const useHead = (id: string) => {
    if (ids) window.history.replaceState(null, "", urlFor(ids, id));
    setPhotoOpen(false);
    setHead(id);
  };
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

  // each ear's audiogram, editable here to explore (edits are local and go with that ear's design request)
  const [agEdit, setAgEdit] = useState<Record<Side, Record<string, number> | null>>(perEar(() => null));
  const agRaw = useMemo(() => perEar((s) => agEdit[s] ?? grid?.patients?.[s]?.audiogram_db_hl
    ?? Object.fromEntries(Object.entries(EXAMPLE_AUDIOGRAM).map(([k, v]) => [String(k), v]))), [agEdit, grid]);
  const audiogram = useMemo(() => perEar((s) => toAudiogram(agRaw[s])), [agRaw]);

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
  const G = useMemo(() => perEar((s) => (design[s].status === "done" ? design[s].result?.design.gain_mean_db : undefined)), [design]);
  // per ear, per scene: the scene through that ear (each ear hears every source through its own filter)
  const results = useMemo(() => perEar((side) => visible.map((s) => {
    if (!ref) return null;
    const srcs = s.sources.map((src) => {
      const sp = spectra[dirKey(src.az, src.el)];
      return sp ? { ...src, gainDb: bandGainDb(sp[side], ref[side]) } : null;
    });
    if (srcs.some((x) => !x)) return null;
    return sceneDeficit(srcs as NonNullable<(typeof srcs)[number]>[], audiogram[side], G[side]);
  })), [visible, spectra, ref, audiogram, G]);

  const status = (s: Scene): CellStatus => {
    const keys = [...new Set(s.sources.map((x) => dirKey(x.az, x.el)))];
    const done = keys.filter((k) => spectra[k]).length + (ref ? 1 : 0), total = keys.length + 1;
    if (done === total) return { state: "done", done, total };
    return { state: keys.some((k) => pending.current.has(k)) ? "running" : "queued", done, total };
  };

  const agg = useMemo(() => perEar((side) => {
    const r = results[side];
    const ok = visible.map((s, i) => ({ s, r: r[i] })).filter((x) => x.r && x.s.weight > 0);
    const t = targetGain(ok.map((x) => x.r!.deficit), ok.map((x) => x.s.weight), audiogram[side]);
    const W = ok.reduce((a, x) => a + x.s.weight, 0) || 1;
    const rows: SceneRow[] = visible.map((s, i) => ({
      id: s.id, name: s.name, weight: s.weight,
      contribution: r[i] ? r[i]!.deficit.map((d) => (s.weight / W) * d) : null,
      siiHealthy: r[i]?.siiHealthy, siiUnaided: r[i]?.siiUnaided, siiAided: r[i]?.siiAided,
    }));
    return { ...t, rows };
  }), [visible, results, audiogram]);

  const allKeys = new Set([REF, ...visible.flatMap((s) => s.sources.map((x) => dirKey(x.az, x.el)))]);
  const complete = [...allKeys].filter((k) => spectra[k]).length;
  const ready = complete === allKeys.size;

  // design: per ear, send each visible scene's deficit through that ear + weight; poll until both finish
  const polls = useRef<Record<Side, number | null>>({ left: null, right: null });
  useEffect(() => () => { for (const s of SIDES) if (polls.current[s]) window.clearInterval(polls.current[s]!); }, []);
  const pollUntilDone = <T extends { status: string }>(side: Side, get: () => Promise<T>, set: (v: T) => void, ms: number) => {
    if (polls.current[side]) window.clearInterval(polls.current[side]!);
    polls.current[side] = window.setInterval(async () => {
      try {
        const v = await get();
        set(v);
        if (v.status === "done" || v.status === "error") { window.clearInterval(polls.current[side]!); polls.current[side] = null; }
      } catch { /* transient: keep polling */ }
    }, ms);
  };
  const runDesign = async () => {
    if (!ids || !ready) return;
    setDesignStale(false);
    setWave(perEar(() => ({ status: "none" })));
    for (const side of SIDES) {
      const payload = visible.map((s, i) => ({ s, r: results[side][i] })).filter((x) => x.r && x.s.weight > 0)
        .map(({ s, r }) => ({ id: s.id, name: s.name, weight: s.weight, deficit_db: r!.deficit, deficit_weighted: r!.deficitWeighted }));
      setDesign((d) => ({ ...d, [side]: { status: "queued", log: [] } }));
      try {
        await startDesign(ids[side], agRaw[side], payload);
      } catch (e) { setDesign((d) => ({ ...d, [side]: { status: "error", error: (e as Error).message } })); continue; }
      pollUntilDone(side, () => designStatus(ids[side]), (v) => setDesign((d) => ({ ...d, [side]: v })), 1000);
    }
  };

  // 3D wave check of one ear's design: the earpiece voxelized into hornsim.wavesim, aided vs open
  const wavePolls = useRef<Record<Side, number | null>>({ left: null, right: null });
  useEffect(() => () => { for (const s of SIDES) if (wavePolls.current[s]) window.clearInterval(wavePolls.current[s]!); }, []);
  const runWave = async (side: Side) => {
    if (!ids) return;
    setWave((w) => ({ ...w, [side]: { status: "queued", log: [] } }));
    try { await startWaveCheck(ids[side]); } catch (e) { setWave((w) => ({ ...w, [side]: { status: "error", error: (e as Error).message } })); return; }
    if (wavePolls.current[side]) window.clearInterval(wavePolls.current[side]!);
    wavePolls.current[side] = window.setInterval(async () => {
      try {
        const v = await waveStatus(ids[side]);
        setWave((w) => ({ ...w, [side]: v }));
        if (v.status === "done" || v.status === "error") { window.clearInterval(wavePolls.current[side]!); wavePolls.current[side] = null; }
      } catch { /* transient */ }
    }, 2000);
  };

  const resize = (m: number) => {
    setN(m);
    setScenes((ss) => (ss.length >= m * m ? ss : [...ss, ...defaultScenes(m * m).slice(ss.length)]));
    setCommitTick((t) => t + 1);
    setDesignStale(true);
  };

  const sii = (i: number): EarSii => perEar((s) => {
    const r = results[s][i];
    return r ? { healthy: r.siiHealthy, unaided: r.siiUnaided, aided: r.siiAided } : null;
  });

  if (error) return <p className={styles.error}>{error}</p>;
  if (needsHead) return <div className={styles.gate}><HeadPhoto required onUse={useHead} /></div>;
  if (!grid || !solid || !ids) return <p className={styles.loading}>Loading the head and both ears…</p>;
  const [busy, size, queued] = poolState.split("/").map(Number);
  const pts = grid.patients;
  const designing = SIDES.some((s) => design[s].status === "queued" || design[s].status === "running");

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
          <form className={styles.patient} onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            const l = String(fd.get("left") ?? "").trim(), r = String(fd.get("right") ?? "").trim();
            if (!l && !r) { window.history.replaceState(null, "", urlFor(AVERAGE_IDS, head)); setIds({ ...AVERAGE_IDS }); return; }
            // other ears are another person: their head shape has to come from their own photo
            if (ID_RE.test(l) && ID_RE.test(r)) { window.history.replaceState(null, "", urlFor({ left: l, right: r }, null)); setHead(null); setIds({ left: l, right: r }); }
          }}>
            {SIDES.map((s) => (
              <label key={s}>{s} ear <input name={s} defaultValue={isAverage(ids[s]) ? "" : ids[s]} placeholder="average ear" size={13} required={!isAverage(ids[s === "left" ? "right" : "left"])} /></label>
            ))}
            <button className={styles.btn} type="submit">load</button>
          </form>
          <button className={styles.btn} onClick={() => setPhotoOpen(true)}>{head ? "retake front photo" : "front photo (head shape)"}</button>
          <span className={styles.num}>workers {busy}/{size} busy · {queued} queued</span>
        </header>
        {photoOpen && <HeadPhoto onUse={useHead} onCancel={() => setPhotoOpen(false)} />}
        <div className={styles.toolbar}>
          {SIDES.map((s) => (
            <fieldset key={s} className={styles.audiogram}>
              <legend>{s} ear dB HL</legend>
              {Object.keys(agRaw[s]).sort((a, b) => +a - +b).map((f) => (
                <label key={f}>{+f >= 1000 ? `${+f / 1000}k` : f}
                  <input type="number" min={-10} max={120} step={5} value={agRaw[s][f]}
                    onChange={(e) => { setAgEdit((x) => ({ ...x, [s]: { ...agRaw[s], [f]: Number(e.target.value) } })); setDesignStale(true); }} />
                </label>
              ))}
              {agEdit[s] && <button type="button" className={styles.btn} onClick={() => { setAgEdit((x) => ({ ...x, [s]: null })); setDesignStale(true); }}>reset</button>}
            </fieldset>
          ))}
          <span className={styles.note}>
            {grid.head.meta.measured ? `patient's head from a front photo (${Number(grid.head.meta.breadth_mm).toFixed(0)} mm wide)` : "average head"} ·{" "}
            {isAverage(ids.left) && isAverage(ids.right) ? "average ear on both sides (not anyone's ears)" : "patient's left and right ear scans"} ·{" "}
            {grid.dx_mm} mm grid · talkers far away (plane waves) ·{" "}
            {SIDES.map((s) => `${s}: ${agEdit[s] ? "edited" : pts?.[s] && !pts[s].audiogram_is_example ? "patient" : "example"} audiogram`).join(", ")}
            {offline && <> · backend offline ({offline}): designing is disabled</>}
          </span>
        </div>
        <div className={styles.cells} style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
          {visible.map((s, i) => (
            <SceneCell key={s.id} grid={grid} solid={solid} scene={s} status={status(s)} sii={sii(i)} store={store}
              onMove={(sid, az, el) => update(s.id, (x) => ({ ...x, sources: x.sources.map((q) => (q.id === sid ? { ...q, az, el } : q)) }))}
              onCommit={commit}
              onChange={(ns) => update(s.id, () => ns)}
              onRemoveSource={(sid) => update(s.id, (x) => ({ ...x, sources: x.sources.filter((q) => q.id !== sid) }))}
              onAddSource={(role) => { update(s.id, (x) => ({ ...x, sources: [...x.sources, newSource(role)] })); setCommitTick((t) => t + 1); }}
            />
          ))}
        </div>
      </section>
      <div className={styles.side}>
        <div className={styles.earTabs} role="tablist" aria-label="Ear">
          {SIDES.map((s) => (
            <button key={s} role="tab" aria-selected={ear === s} className={styles.earTab} onClick={() => setEar(s)}>
              {LABEL[s]} ear
              <span className={styles.tabState}>{design[s].status === "done" ? "designed" : design[s].status === "none" ? "" : design[s].status}</span>
            </button>
          ))}
        </div>
        <Aggregate key={ear} ear={LABEL[ear]} rows={agg[ear].rows} target={agg[ear].target} need={agg[ear].need} nal={agg[ear].nal}
          complete={complete} total={allKeys.size} pid={ids[ear]} design={design[ear]} designStale={designStale}
          canDesign={ready && !offline && !designing} designing={designing} onDesign={runDesign}
          wave={wave[ear]} onWaveCheck={() => runWave(ear)} />
      </div>
    </div>
  );
}
