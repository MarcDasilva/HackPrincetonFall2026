"use client";

import { useRef } from "react";
import Orb, { type OrbNode } from "@/components/Orb";
import ResearchBoxes, { RESEARCH_LINE } from "@/components/ResearchBoxes";
import { useMounted } from "@/components/useMounted";

/** PREVIEW ONLY: the research boxes alone, around a stand-in lead orb. The boxes read the agents server's study events, as in the dashboard. */
export default function Page() {
  const mounted = useMounted();
  const lead = useRef<HTMLDivElement>(null);
  const nodes = useRef<OrbNode[]>([]);
  // MetalFx and the orbs are browser-only; render nothing until hydration (see useMounted).
  if (!mounted) return null;
  return (
    <main style={{ position: "relative", minHeight: "100vh", color: "#e6e8eb" }}>
      {/* ?run=<id> picks the session whose study to show; the dev patient otherwise. */}
      <ResearchBoxes runId={new URLSearchParams(location.search).get("run") ?? "d60d88e7550d"} origin={() => lead.current?.getBoundingClientRect() ?? null} nodes={nodes} />
      <div data-testid="lead" style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)", display: "flex", flexDirection: "column", alignItems: "center", zIndex: 4 }}>
        <div ref={lead}><Orb px={300} nodes={nodes} /></div>
        <div role="status" style={{ marginTop: -10, fontSize: 16, color: "#757575", textAlign: "center", maxWidth: 300 }}>{RESEARCH_LINE}</div>
      </div>
    </main>
  );
}
