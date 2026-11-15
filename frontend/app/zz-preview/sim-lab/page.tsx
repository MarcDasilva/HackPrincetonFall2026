"use client";

import { useEffect, useState } from "react";
import SimRuns from "@/app/sim/SimRuns";
import { fetchGrid, type GridWithPatient } from "@/app/sim/lib/api";
import { EXAMPLE_AUDIOGRAM } from "@/app/sim/lib/hearing";
import { useMounted } from "@/components/useMounted";
import type { LeadScene } from "@/lib/lead";

/**
 * PREVIEW ONLY: the lead's simulation view on three fixed scenes, for one patient (?pid=, ?ear=). The 3D and 2D wave
 * viewers come from that patient's backend files; when the backend has no sim grid for them, the repo's average ear
 * (public/sim/ear_grid.json) stands in so the pixel view still runs.
 */
const SCENES: LeadScene[] = [
  { id: "s1", name: "Dinner table", sound: "family talking", why: "They eat with family daily.", weight: 3, sources: [{ role: "talker", az: 0, el: 0, level_db: 65 }] },
  { id: "s2", name: "Friend on the right", sound: "friend talking", why: "A friend walks on the aided side.", weight: 2, sources: [{ role: "talker", az: 90, el: 0, level_db: 60 }] },
  { id: "s3", name: "Busy cafe", sound: "cafe chatter", why: "Weekend coffee with background noise.", weight: 1, sources: [{ role: "talker", az: 45, el: 0, level_db: 65 }, { role: "babble", az: 150, el: 15, level_db: 60 }] },
];

export default function Page() {
  const mounted = useMounted();
  const [grid, setGrid] = useState<GridWithPatient | null>(null);
  const q = mounted ? new URLSearchParams(location.search) : null;
  const pid = q?.get("pid") ?? "63dc5db647b1", ear = q?.get("ear") ?? "right";
  useEffect(() => {
    if (!mounted) return;
    fetchGrid(pid, ear).catch(() => fetch("/sim/ear_grid.json").then((r) => r.json()).then((g: GridWithPatient) => ({
      ...g, patient: { id: pid, average_ear: true, side: ear as "left" | "right", audiogram_db_hl: { ...EXAMPLE_AUDIOGRAM }, audiogram_is_example: true },
    }))).then(setGrid);
  }, [mounted, pid, ear]);
  if (!mounted || !grid) return null;
  return (
    <main style={{ position: "relative", zIndex: 1, minHeight: "100vh", background: "#fff", paddingTop: 24 }}>
      <SimRuns pid={pid} ear={ear} scenes={SCENES} grid={grid} onDone={() => {}} />
    </main>
  );
}
