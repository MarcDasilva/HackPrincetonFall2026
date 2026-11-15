"use client";

import { useEffect, useState } from "react";
import SimRuns from "@/app/sim/SimRuns";
import { fetchGrid, waveGain, type GridWithPatient, type WaveCheck } from "@/app/sim/lib/api";
import type { HeadGrid } from "@/app/sim/lib/headFdtd";
import { EXAMPLE_AUDIOGRAM } from "@/app/sim/lib/hearing";
import { useMounted } from "@/components/useMounted";
import localFont from "next/font/local";
import AurisLogo from "@/components/AurisLogo";
import type { LeadScene } from "@/lib/lead";

/**
 * PREVIEW ONLY: the lead's simulation view on three fixed scenes, for one patient (?pid=, ?ear=). The 3D and 2D wave
 * viewers come from that patient's backend files; when the backend has no sim grid for them, the repo's average ear
 * (public/sim/ear_grid.json) stands in so the pixel view still runs.
 *
 * ?aid=1 is the validation the dashboard opens after a pick: the scenes scored with an earpiece in the 3D wave sim — that
 * patient's last wave check, or public/sim/wave_check_example.json (a real hornsim.aided_wave run, patient 8e0c9758fead, design "flush").
 */
const gambarino = localFont({ src: "../../fonts/Gambarino-Regular.woff2" });

const SCENES: LeadScene[] = [
  { id: "s1", name: "Dinner table", sound: "family talking", why: "They eat with family daily.", weight: 3, sources: [{ role: "talker", az: 0, el: 0, level_db: 65 }] },
  { id: "s2", name: "Friend on the right", sound: "friend talking", why: "A friend walks on the aided side.", weight: 2, sources: [{ role: "talker", az: 90, el: 0, level_db: 60 }] },
  { id: "s3", name: "Busy cafe", sound: "cafe chatter", why: "Weekend coffee with background noise.", weight: 1, sources: [{ role: "talker", az: 45, el: 0, level_db: 65 }, { role: "babble", az: 150, el: 15, level_db: 60 }] },
];

export default function Page() {
  const mounted = useMounted();
  const [grid, setGrid] = useState<GridWithPatient | null>(null);
  // The dummy head wearing BOTH of this patient's ears: the backend's route, or a local export of it
  // (public/dev/head_grid_<pid>.json, gitignored: `python -m hornsim.head_grid` with the patient's two ear.ply files).
  const [head, setHead] = useState<HeadGrid | null | undefined>(undefined);
  const [wave, setWave] = useState<WaveCheck | null | undefined>(undefined);
  const q = mounted ? new URLSearchParams(location.search) : null;
  const pid = q?.get("pid") ?? "63dc5db647b1", ear = q?.get("ear") ?? "right";
  useEffect(() => {
    if (!mounted) return;
    fetchGrid(pid, ear).catch(() => fetch("/sim/ear_grid.json").then((r) => r.json()).then((g: GridWithPatient) => ({
      ...g, patient: { id: pid, average_ear: true, side: ear as "left" | "right", audiogram_db_hl: { ...EXAMPLE_AUDIOGRAM }, audiogram_is_example: true },
    }))).then(setGrid);
    const json = (u: string) => fetch(u).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));
    json(`/api/sim/patients/${pid}/head_grid`).catch(() => json(`/dev/head_grid_${pid}.json`)).then(setHead, () => setHead(null));
    if (!q?.get("aid")) return setWave(null);
    json(`/api/sim/patients/${pid}/design/wave_check?ear=${ear}`).then((st) => (st.result ? st.result : Promise.reject()))
      .catch(() => json("/sim/wave_check_example.json")).then(setWave, () => setWave(null));
  }, [mounted, pid, ear]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!mounted || !grid || head === undefined || wave === undefined) return null;
  return (
    // The SAME overlay the dashboard opens inside the orb (Dashboard.tsx, data-testid="sims", and its Exit button) — keep them in step.
    <main>
      {/* The dashboard's logo, at the SAME spot (app/zz-preview/page.tsx); it shows through the see-through sims overlay. */}
      <div style={{ position: "fixed", top: 24, right: 40, zIndex: 20 }}><AurisLogo fontFamily={gambarino.style.fontFamily} /></div>
      <div data-testid="sims" style={{ position: "fixed", inset: 0, zIndex: 25, overflow: "auto", paddingTop: 56 }}>
        <SimRuns pid={pid} ear={ear} scenes={SCENES} grid={grid} headGrid={head ?? undefined} gain={wave ? waveGain(wave) : undefined} onDone={() => {}} />
      </div>
      {/* Inert here: the preview has no orb to close back into. */}
      <button type="button" aria-label="Exit simulation" style={{ position: "fixed", top: 20, left: 20, zIndex: 30, display: "flex", alignItems: "center", justifyContent: "center", width: 40, height: 40, borderRadius: 999, cursor: "pointer", border: "1px solid rgba(255,255,255,0.18)", background: "rgba(0,0,0,0.55)", color: "#e6e8eb" }}>
        <svg viewBox="0 0 24 24" width={18} height={18} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </main>
  );
}
