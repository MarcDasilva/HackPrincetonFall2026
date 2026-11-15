"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { loadHead } from "@/app/sim/HeadSnap";
import { useMounted } from "@/components/useMounted";
import { makeEnv, prepHead, VARIANTS, type Head, type Src, type Variant } from "./variants";

/** PREVIEW ONLY: ten ways to show one simulation scene. ?pid=<patient> uses that patient's reconstructed head; without one, the average head. */
const SCENE_NAME = "Busy cafe";
const SOURCES: Src[] = [
  { role: "talker", az: 0, el: 0, level_db: 65 },
  { role: "talker", az: 90, el: 0, level_db: 60 },
  { role: "babble", az: 150, el: 20, level_db: 58 },
];

function Card({ v, head, n }: { v: Variant; head: Head; n: number }) {
  const box = useRef<HTMLDivElement>(null), ov = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = box.current!, oc = ov.current!, g = oc.getContext("2d")!;
    // A FRESH canvas per mount: cleanup kills the context, and a canvas whose context was lost NEVER hands out another (dev StrictMode mounts twice).
    const r = new THREE.WebGLRenderer({ antialias: true });
    const cv = r.domElement;
    Object.assign(cv.style, { position: "absolute", inset: "0", width: "100%", height: "100%", display: "block" });
    el.prepend(cv);
    const dpr = Math.min(devicePixelRatio, 2);
    r.setPixelRatio(dpr);
    r.setClearColor(v.bg);
    const b = v.build(makeEnv(head, false, SOURCES, SCENE_NAME));
    const cam = b.camera;
    const ctrl = b.controls === false ? null : new OrbitControls(cam, cv);
    if (ctrl) { ctrl.target.copy(cam.userData.target ?? new THREE.Vector3()); ctrl.enableDamping = true; ctrl.update(); }
    let w = 1, h = 1;
    const resize = () => {
      w = el.clientWidth; h = el.clientHeight;
      r.setSize(w, h, false);
      oc.width = w * dpr; oc.height = h * dpr;
      if (cam instanceof THREE.PerspectiveCamera) cam.aspect = w / h;
      else { const half = cam.userData.half as number; Object.assign(cam, { left: -half * (w / h), right: half * (w / h), top: half, bottom: -half }); }
      cam.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();
    const P = (p: THREE.Vector3): [number, number] => { const s = p.clone().project(cam); return [((s.x + 1) / 2) * w, ((1 - s.y) / 2) * h]; };
    const t0 = performance.now();
    let raf = 0;
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const t = (now - t0) / 1000;
      b.tick?.(t);
      ctrl?.update();
      if (b.render) b.render(r, w, h); else r.render(b.scene, cam);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      b.draw?.(g, P, t, w, h);
    };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); ctrl?.dispose(); r.dispose(); r.forceContextLoss(); cv.remove(); };
  }, [v, head]);
  return (
    <figure data-testid="gallery-card" style={{ margin: 0, border: "1px solid #20252d", borderRadius: 14, overflow: "hidden", background: "#0b0d11" }}>
      <div ref={box} style={{ position: "relative", aspectRatio: "16 / 10", background: v.bg }}>
        <canvas ref={ov} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />
      </div>
      <figcaption style={{ padding: "10px 14px 12px", borderTop: "1px solid #20252d" }}>
        <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
          <span style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11, color: "#5a6b80" }}>{String(n).padStart(2, "0")}</span>
          <span style={{ color: "#e6e8eb", fontSize: 15 }}>{v.title}</span>
        </div>
        <div style={{ color: "#8b95a3", fontSize: 12.5, marginTop: 4, lineHeight: 1.45 }}>{v.caption}</div>
      </figcaption>
    </figure>
  );
}

export default function Page() {
  const mounted = useMounted();
  const [head, setHead] = useState<Head | null>(null);
  useEffect(() => {
    if (!mounted) return;
    void loadHead(new URLSearchParams(location.search).get("pid") ?? "none").then((h) => setHead(prepHead(h)));
  }, [mounted]);
  if (!mounted) return null;
  return (
    <main style={{ position: "relative", zIndex: 1, minHeight: "100vh", background: "#05060a", color: "#e6e8eb", padding: "28px 24px 40px" }}>
      <header style={{ maxWidth: 1400, margin: "0 auto 20px" }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 500 }}>Simulation views</h1>
        <p style={{ margin: "6px 0 0", color: "#8b95a3", fontSize: 13 }}>One scene ({SCENE_NAME}: talker in front, talker on the aided side, babble behind and above), ten ways to show it. Drag any view to turn it.</p>
      </header>
      {head && (
        <div data-testid="gallery" style={{ maxWidth: 1400, margin: "0 auto", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 560px), 1fr))", gap: 16 }}>
          {VARIANTS.map((v, i) => <Card key={v.key} v={v} head={head} n={i + 1} />)}
        </div>
      )}
    </main>
  );
}
