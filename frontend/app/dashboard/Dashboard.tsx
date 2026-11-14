"use client";

import { useEffect, useRef, useState } from "react";
import Dock from "@/components/Dock";

// Mirrors the results manifest in handoff.md. Paths are relative to /data/. The agent overwrites results.json; nothing here may call a backend.
type Experiment = {
  id: number;
  mesh: string;
  params: Record<string, number>;
  gain_curve: [number, number][];
  neurogram: string;
  audio: string;
  score: number;
};
type Manifest = {
  ear: {
    mesh: string;
    audiogram: [number, number][];
    canal_band: { volume_cc: [number, number]; samples: number };
    cohc: number;
    cihc: number;
  };
  reference_neurogram: string;
  unaided: { neurogram: string; audio: string };
  experiments: Experiment[];
  pick: number;
};

const D = "/data/";
const panel: React.CSSProperties = {
  scrollMarginTop: 110,
  background: "rgba(8,8,12,0.72)",
  border: "1px solid rgba(255,255,255,0.12)",
  padding: 20,
  backdropFilter: "blur(6px)",
};
const h2: React.CSSProperties = { margin: "0 0 12px", fontSize: 13, letterSpacing: "0.14em", textTransform: "uppercase", color: "#9aa0a8", fontWeight: 500 };
const btn = (on: boolean): React.CSSProperties => ({
  padding: "10px 18px",
  background: on ? "#fff" : "rgba(255,255,255,0.08)",
  color: on ? "#000" : "#e6e8eb",
  border: "1px solid rgba(255,255,255,0.3)",
  font: "inherit",
  cursor: "pointer",
});

const svg = (d: string[]) => (
  <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    {d.map((p) => <path key={p} d={p} />)}
  </svg>
);
// One icon per panel in handoff.md: ear, audiogram, cochlea spiral, experiment grid, speaker.
const icons = {
  ear: svg(["M6 8.5a6.5 6.5 0 1 1 13 0c0 6-6 6-6 10a3.5 3.5 0 1 1-7 0", "M15 8.5a2.5 2.5 0 0 0-5 0v1a2 2 0 1 1 0 4"]),
  profile: svg(["M3 3v18h18", "M7 8l4 3 3-2 5 7"]),
  cochlea: svg(["M12 12a1 1 0 0 1 1-1 2 2 0 0 1 2 2 4 4 0 0 1-4 4 6 6 0 0 1-6-6 8 8 0 0 1 8-8 9 9 0 0 1 9 9"]),
  experiments: svg(["M4 4h6v6H4z", "M14 4h6v6h-6z", "M4 14h6v6H4z", "M14 14h6v6h-6z"]),
  listen: svg(["M11 5 6 9H2v6h4l5 4z", "M15.5 8.5a5 5 0 0 1 0 7", "M18.5 5.5a9 9 0 0 1 0 13"]),
};
const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

function Audiogram({ points }: { points: [number, number][] }) {
  // dB HL grows downward: worse hearing plots lower, as on a clinical audiogram.
  const xs = (i: number) => 30 + (i * 260) / (points.length - 1);
  const y = (db: number) => 10 + (db / 80) * 140;
  return (
    <svg viewBox="0 0 300 175" style={{ width: "100%" }} role="img" aria-label="Audiogram">
      {[0, 20, 40, 60, 80].map((db) => (
        <g key={db}>
          <line x1="30" x2="290" y1={y(db)} y2={y(db)} stroke="#2a2734" />
          <text x="24" y={y(db) + 3} textAnchor="end" fontSize="8" fill="#9aa0a8">{db}</text>
        </g>
      ))}
      <polyline fill="none" stroke="#ff5fa2" strokeWidth="2" points={points.map(([, db], i) => `${xs(i)},${y(db)}`).join(" ")} />
      {points.map(([hz], i) => (
        <text key={hz} x={xs(i)} y="168" textAnchor="middle" fontSize="8" fill="#9aa0a8">{hz}</text>
      ))}
    </svg>
  );
}

export default function Dashboard() {
  const [m, setM] = useState<Manifest | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    fetch(D + "results.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`results.json ${r.status}`))))
      .then((j: Manifest) => {
        setM(j);
        setSel(j.pick);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <p style={{ position: "relative", padding: 40 }}>Could not load results: {err}</p>;
  if (!m) return <p style={{ position: "relative", padding: 40 }}>Loading…</p>;

  const ranked = [...m.experiments].sort((a, b) => b.score - a.score);
  const cur = m.experiments.find((e) => e.id === sel) ?? ranked[0];
  const pick = m.experiments.find((e) => e.id === m.pick) ?? ranked[0];

  const play = (key: string, file: string) => {
    audio.current?.pause();
    const a = new Audio(D + file);
    a.onended = () => setPlaying(null);
    audio.current = a;
    setPlaying(key);
    a.play().catch(() => setPlaying(null));
  };

  const items = [
    { icon: icons.ear, label: "Ear and horn", onClick: () => jump("ear") },
    { icon: icons.profile, label: "Ear profile", onClick: () => jump("profile") },
    { icon: icons.cochlea, label: "Cochlea", onClick: () => jump("cochlea") },
    { icon: icons.experiments, label: "Experiments", badge: m.experiments.length, onClick: () => jump("experiments") },
    { separator: true },
    { icon: icons.listen, label: "Listen", onClick: () => jump("listen") },
  ];

  return (
    <>
      {/* The dock positions itself against its nearest positioned parent, so this fixed strip is the "top of the screen". It is click-through; the dock opts back in. */}
      <div style={{ position: "fixed", top: 0, left: 0, right: 0, height: 100, zIndex: 20, pointerEvents: "none" }}>
        <Dock
          items={items}
          position="top"
          showIndicators={false}
          style={{
            pointerEvents: "auto",
            // Tray is see-through: only the icon tiles draw. Both backdrop-filter spellings or Safari keeps the blur.
            "--dock-panel": "transparent",
            "--dock-panel-edge": "transparent",
            "--dock-panel-highlight": "transparent",
            "--dock-panel-shadow": "0 0 0 0 transparent",
            backdropFilter: "none",
            WebkitBackdropFilter: "none",
          }}
        />
      </div>
    <div style={{ position: "relative", maxWidth: 1200, margin: "0 auto", padding: "120px 24px 80px", display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
      <section id="ear" style={{ ...panel, gridColumn: "span 2", minHeight: 320 }}>
        <h2 style={h2}>Ear and horn</h2>
        {/* ponytail: placeholder — three.js + GLTFLoader once ear.glb / horn_*.glb exist (npm i three). */}
        <div style={{ height: 260, display: "grid", placeItems: "center", border: "1px dashed rgba(255,255,255,0.25)", color: "#9aa0a8", textAlign: "center" }}>
          3D viewer pending<br />
          {m.ear.mesh} + {cur.mesh}
        </div>
      </section>

      <section id="profile" style={panel}>
        <h2 style={h2}>Ear profile</h2>
        <Audiogram points={m.ear.audiogram} />
        <p style={{ margin: "12px 0 0", fontSize: 14, lineHeight: 1.6 }}>
          Canal volume {m.ear.canal_band.volume_cc[0]}–{m.ear.canal_band.volume_cc[1]} cc ({m.ear.canal_band.samples} samples)
          <br />
          Outer hair cells {m.ear.cohc} · inner hair cells {m.ear.cihc}
        </p>
      </section>

      <section id="cochlea" style={{ ...panel, gridColumn: "1 / -1" }}>
        <h2 style={h2}>Cochlea — reference vs. design {cur.id}</h2>
        <div style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
          {[
            ["Healthy reference", m.reference_neurogram],
            [`Design ${cur.id} (score ${cur.score.toFixed(2)})`, cur.neurogram],
          ].map(([label, src]) => (
            <figure key={label} style={{ margin: 0 }}>
              {/* eslint-disable-next-line @next/next/no-img-element -- manifest PNGs are static, sizes unknown */}
              <img src={D + src} alt={label} style={{ width: "100%", height: 160, objectFit: "fill", imageRendering: "pixelated" }} />
              <figcaption style={{ fontSize: 13, color: "#9aa0a8", marginTop: 6 }}>{label}</figcaption>
            </figure>
          ))}
        </div>
      </section>

      <section id="experiments" style={{ ...panel, gridColumn: "1 / -1" }}>
        <h2 style={h2}>{m.experiments.length} experiments — click one to select it</h2>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {ranked.map((e) => (
            <button key={e.id} onClick={() => setSel(e.id)} aria-pressed={e.id === sel} style={btn(e.id === sel)}>
              #{e.id} · {e.score.toFixed(2)}
              {e.id === m.pick ? " ★" : ""}
            </button>
          ))}
        </div>
      </section>

      <section id="listen" style={{ ...panel, gridColumn: "1 / -1", display: "flex", flexWrap: "wrap", gap: 12 }}>
        <button onClick={() => play("unaided", m.unaided.audio)} style={btn(playing === "unaided")}>▶ Unaided</button>
        <button onClick={() => play("sel", cur.audio)} style={btn(playing === "sel")}>▶ This design (#{cur.id})</button>
        <button onClick={() => play("pick", pick.audio)} style={btn(playing === "pick")}>▶ Agent&apos;s pick (#{pick.id})</button>
      </section>
    </div>
    </>
  );
}
