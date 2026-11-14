"use client";

import { useEffect, useState } from "react";
import AurisLogo from "@/components/AurisLogo";
import s from "./demo.module.css";
import { loadManifest, FAKE, FAKE_COMPARE, type Manifest } from "./manifest";
import { EarBeat, LaunchBeat, TargetBeat, SearchBeat, FitBeat, ProofBeat, CompareBeat } from "./beats";

const BEATS = ["Ear", "Launch", "Target", "Search", "Fit", "Proof", "Second patient"];

/** The demo screen reads ONLY manifests: ?manifest=<url> (default: the fake) and ?compare=<url> for beat 7. The beat lives in the hash (#3) so a presenter can reload in place. */
export default function Demo({ fontFamily }: { fontFamily: string }) {
  const [m, setM] = useState<Manifest>();
  const [b, setB] = useState<Manifest | null>(null);
  const [err, setErr] = useState<string>();
  const [beat, setBeat] = useState(1);

  useEffect(() => {
    const q = new URLSearchParams(location.search);
    const main = q.get("manifest") ?? FAKE;
    const cmp = q.get("compare") ?? (main === FAKE ? FAKE_COMPARE : null);
    loadManifest(main).then(setM, (e) => setErr(String(e)));
    if (cmp) loadManifest(cmp).then(setB, () => setB(null));
    const fromHash = () => setBeat(Math.min(7, Math.max(1, parseInt(location.hash.slice(1)) || 1)));
    fromHash();
    addEventListener("hashchange", fromHash);
    return () => removeEventListener("hashchange", fromHash);
  }, []);

  const go = (n: number) => {
    const next = Math.min(7, Math.max(1, n));
    history.replaceState(null, "", `#${next}`);
    setBeat(next);
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, audio")) return;
      if (e.key === "ArrowRight") go(beat + 1);
      if (e.key === "ArrowLeft") go(beat - 1);
    };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, [beat]);

  const p = m?.patient;
  return (
    <main className={s.page} data-testid="demo">
      <div className={s.header}>
        <AurisLogo fontFamily={fontFamily} />
        <div className={s.headText}>
          <h1>Earpiece design run</h1>
          <p>
            {p ? `Patient ${p.id} · ${p.side} ear` : "Loading manifest…"}
            {p?.is_average_ear && " · average ear, not this patient's"}
            {m && ` · ${new URL(m.url).pathname}`}
          </p>
        </div>
        {m?.fake && <span className={s.badge} data-testid="fake-badge" title="Hand-written example manifest. No number on this screen comes from a run.">Fake data · not from a run</span>}
      </div>

      <nav className={s.steps} aria-label="Storyboard">
        {BEATS.map((name, i) => (
          <button key={name} className={s.step} aria-current={beat === i + 1 ? "step" : undefined} onClick={() => go(i + 1)}>
            <b>{i + 1}</b>{name}
          </button>
        ))}
      </nav>

      {err && <div className={s.plate}><h3>Could not load the manifest</h3><p className={s.sub}>{err}</p></div>}
      {m && (
        <div className={s.beat} data-testid={`beat-${beat}`} key={beat}>
          {beat === 1 && <EarBeat m={m} />}
          {beat === 2 && <LaunchBeat m={m} />}
          {beat === 3 && <TargetBeat m={m} />}
          {beat === 4 && <SearchBeat m={m} />}
          {beat === 5 && <FitBeat m={m} />}
          {beat === 6 && <ProofBeat m={m} />}
          {beat === 7 && <CompareBeat a={m} b={b} />}
        </div>
      )}

      <div className={s.nav}>
        <button className={s.navBtn} onClick={() => go(beat - 1)} disabled={beat === 1}>← {BEATS[beat - 2] ?? "Back"}</button>
        <span>{beat} / 7 · arrow keys step</span>
        <button className={s.navBtn} onClick={() => go(beat + 1)} disabled={beat === 7}>{BEATS[beat] ?? "Next"} →</button>
      </div>
    </main>
  );
}
