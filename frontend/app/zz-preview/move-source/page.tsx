"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { HeadGrid, Side } from "@/app/sim/lib/headFdtd";
import { useTwoEar } from "@/app/sim/lib/twoEar";
import { CLIPS, loadClip, renderMix, SR, type ClipAnalysis } from "@/app/sim/lib/clip";
import { headDir, loadHead } from "@/app/sim/HeadSnap";
import type { LeadScene } from "@/lib/lead";

/**
 * TRIAL ONLY: drag one talker anywhere round the patient's head in 3D and hear it move in headphones. The head runs ONCE
 * per grid direction (lib/twoEar.ts, both eardrums per run); every direction's stereo render loops in sync and the
 * source's position crossfades the FOUR nearest — a position between grid points is a blend, not a run of its own.
 */
const PID = "63dc5db647b1", AZ_STEP = 30, NAZ = 360 / AZ_STEP;
const ELS = [-30, 0, 30, 60]; // the head grid's el_range; outside it the source is clamped
const R = 250;                // mm, where the source is drawn (a far talker: the runs are plane waves, distance is not simulated)
const DIRS = ELS.flatMap((el) => Array.from({ length: NAZ }, (_, i) => ({ az: i * AZ_STEP, el })));
const SCENES: LeadScene[] = DIRS.map((d, i) => ({
  id: `d${i}`, name: `${d.az},${d.el}`, sound: "speech", why: "", weight: 1, sources: [{ role: "talker", az: d.az, el: d.el, level_db: 65 }],
}));
const SOUNDS = [...CLIPS, "bank:siren", "bank:bark", "bank:doorbell", "bank:music"]; // bank: the backend's sound bank (lib/clip.ts loadClip)
const clampEl = (el: number) => Math.min(ELS[ELS.length - 1], Math.max(ELS[0], el));

/** Equal-power weights of the four grid runs around (az, el): their squares sum to 1. */
function weights(az: number, el: number) {
  const u = (((az % 360) + 360) % 360) / AZ_STEP, i = Math.floor(u) % NAZ, fa = u - Math.floor(u);
  const v = (clampEl(el) - ELS[0]) / (ELS[1] - ELS[0]), j = Math.min(ELS.length - 2, Math.floor(v)), fe = v - j;
  const c = (f: number) => Math.cos((f * Math.PI) / 2), s = (f: number) => Math.sin((f * Math.PI) / 2);
  const w = new Float32Array(DIRS.length), at = (a: number, e: number) => e * NAZ + (a % NAZ);
  w[at(i, j)] = c(fa) * c(fe); w[at(i + 1, j)] = s(fa) * c(fe); w[at(i, j + 1)] = c(fa) * s(fe); w[at(i + 1, j + 1)] = s(fa) * s(fe);
  return w;
}

export default function Page() {
  const [grid, setGrid] = useState<HeadGrid | null>(null);
  const [clip, setClip] = useState<string>(SOUNDS[0]);
  const [pos, setPos] = useState({ az: 0, el: 0 });
  const [orbit, setOrbit] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audio = useRef<{ ctx: AudioContext; gains: GainNode[]; meters: AnalyserNode[] } | null>(null);
  const [level, setLevel] = useState<[number, number]>([0, 0]);
  const mount = useRef<HTMLDivElement>(null);
  const setSrc = useRef<(az: number, el: number) => void>(() => {});
  useEffect(() => { fetch(`/dev/head_grid_${PID}.json`).then((r) => r.json()).then(setGrid); }, []);
  // the runs' per-ear gains and delays, kept in this browser: a reload skips the ~3 min of head runs. Bump the key when
  // the grid (DIRS) or the head sim changes — a stale cache would play the OLD directions.
  const CACHE = `move-source:v1:${PID}`;
  const [cached, setCached] = useState<ReturnType<typeof useTwoEar>["perScene"] | null | undefined>(undefined);
  useEffect(() => { try { setCached(JSON.parse(localStorage.getItem(CACHE) ?? "null")); } catch { setCached(null); } }, [CACHE]);
  // aided "right" keeps scene az == head az (0 front, 90 right ear)
  const two = useTwoEar(cached === null ? grid : null, SCENES, "right");
  const per = cached ?? two.perScene;
  const ready = per.length === DIRS.length && per.every((p) => p.left.gains[0] && p.right.gains[0]);
  useEffect(() => { if (ready && !cached) try { localStorage.setItem(CACHE, JSON.stringify(per)); } catch {} }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps

  // the 3D scene: drag the source on its shell, drag anywhere else to orbit the camera
  useEffect(() => {
    const el = mount.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(devicePixelRatio);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0d10);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x333333, 1.8));
    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.set(300, 500, 600);
    scene.add(key);
    const camera = new THREE.PerspectiveCamera(40, 1, 10, 10000);
    camera.position.set(-520, 300, 620);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    let live = true;
    loadHead(PID).then((h) => {
      if (!live) return;
      h.traverse((o) => { const m = o as THREE.Mesh; if (m.isMesh) m.material = new THREE.MeshStandardMaterial({ color: 0xc9ccd1, roughness: 0.75 }); });
      scene.add(h);
    });
    // the reachable shell: el −30…60 (three.js theta runs down from +y)
    const shell = new THREE.Mesh(
      new THREE.SphereGeometry(R, 24, 9, 0, Math.PI * 2, THREE.MathUtils.degToRad(90 - ELS[ELS.length - 1]), THREE.MathUtils.degToRad(ELS[ELS.length - 1] - ELS[0])),
      new THREE.MeshBasicMaterial({ color: 0x3a4250, wireframe: true, transparent: true, opacity: 0.35 }));
    scene.add(shell);
    const src = new THREE.Mesh(new THREE.SphereGeometry(16, 24, 16), new THREE.MeshStandardMaterial({ color: 0x5ab0ff, emissive: 0x1a4a80 }));
    const ray = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), new THREE.LineBasicMaterial({ color: 0x5ab0ff, transparent: true, opacity: 0.5 }));
    scene.add(src, ray);
    setSrc.current = (az, elv) => {
      src.position.copy(headDir(az, elv, false).multiplyScalar(R));
      ray.geometry.setFromPoints([new THREE.Vector3(), src.position]);
    };
    setSrc.current(0, 0);

    const rc = new THREE.Raycaster(), ndc = new THREE.Vector2(), ball = new THREE.Sphere(new THREE.Vector3(), R);
    const pick = (e: PointerEvent) => {
      const b = renderer.domElement.getBoundingClientRect();
      ndc.set(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1);
      rc.setFromCamera(ndc, camera);
    };
    let dragging = false;
    const down = (e: PointerEvent) => {
      pick(e);
      if (!rc.intersectObject(src).length) return;
      dragging = true; controls.enabled = false; setOrbit(false);
      renderer.domElement.setPointerCapture(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      if (!dragging) return;
      pick(e);
      // the shell point under the pointer; off the shell, the point on the ray nearest the head
      const p = rc.ray.intersectSphere(ball, new THREE.Vector3()) ?? rc.ray.closestPointToPoint(new THREE.Vector3(), new THREE.Vector3());
      const d = p.normalize();
      // head frame +x is the person's LEFT, +z forward (HeadSnap.ts headDir)
      setPos({ az: ((THREE.MathUtils.radToDeg(Math.atan2(-d.x, d.z)) % 360) + 360) % 360, el: clampEl(THREE.MathUtils.radToDeg(Math.asin(d.y))) });
    };
    const up = () => { dragging = false; controls.enabled = true; };
    renderer.domElement.addEventListener("pointerdown", down, { capture: true });
    renderer.domElement.addEventListener("pointermove", move);
    renderer.domElement.addEventListener("pointerup", up);

    let raf = 0;
    const frame = () => {
      const w = el.clientWidth, h = el.clientHeight;
      if (renderer.domElement.width !== Math.round(w * devicePixelRatio)) { renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }
      controls.update();
      renderer.render(scene, camera);
      // the source's screen position, for e2e/move-source.spec.ts to grab it
      const s = src.position.clone().project(camera);
      el.dataset.sx = String(((s.x + 1) / 2) * w); el.dataset.sy = String(((1 - s.y) / 2) * h);
      raf = requestAnimationFrame(frame);
    };
    frame();
    return () => { live = false; cancelAnimationFrame(raf); controls.dispose(); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, []);

  useEffect(() => setSrc.current(pos.az, pos.el), [pos]);

  const stop = () => { audio.current?.ctx.close(); audio.current = null; setPlaying(false); };
  useEffect(() => stop, []);

  const play = async () => {
    stop();
    const x = await loadClip(clip);
    const ctx = new AudioContext();
    await ctx.resume();
    // every direction feeds ONE bus; the bus feeds the speakers and a per-ear meter
    const bus = ctx.createGain(), split = ctx.createChannelSplitter(2), meters = [ctx.createAnalyser(), ctx.createAnalyser()];
    bus.connect(ctx.destination); bus.connect(split); split.connect(meters[0], 0); split.connect(meters[1], 1);
    const ear = (i: number, e: Side) => {
      const p = per[i][e];
      return renderMix({ srcs: [{ role: "talker", levelDb: 65, gainDb: p.gains[0]!, clip, x }], n: x.length } as ClipAnalysis, p.gains[0]!.map(() => 0), p.delays);
    };
    const chans = DIRS.map((_, i) => [ear(i, "left"), ear(i, "right")]);
    // ONE scale for every direction — normalising each alone would erase the head's shadow
    const peak = Math.max(...chans.flat().map((c) => c.reduce((m, v) => Math.max(m, Math.abs(v)), 0)));
    const t0 = ctx.currentTime + 0.1;
    const gains = chans.map(([l, r]) => {
      const buf = ctx.createBuffer(2, l.length, SR);
      buf.copyToChannel(l.map((v) => (0.9 * v) / peak), 0);
      buf.copyToChannel(r.map((v) => (0.9 * v) / peak), 1);
      const s = ctx.createBufferSource(), g = ctx.createGain();
      s.buffer = buf; s.loop = true; g.gain.value = 0;
      s.connect(g).connect(bus);
      s.start(t0);
      return g;
    });
    audio.current = { ctx, gains, meters };
    setPlaying(true);
  };

  useEffect(() => {
    const a = audio.current;
    if (!a) return;
    const w = weights(pos.az, pos.el);
    a.gains.forEach((g, k) => g.gain.setTargetAtTime(w[k], a.ctx.currentTime, 0.02));
  }, [pos, playing]);

  useEffect(() => {
    if (!playing) return setLevel([0, 0]);
    let raf = 0;
    const buf = new Float32Array(2048);
    const tick = () => {
      const m = audio.current?.meters;
      if (m) setLevel(m.map((a) => { a.getFloatTimeDomainData(buf); return Math.sqrt(buf.reduce((t, v) => t + v * v, 0) / buf.length); }) as [number, number]);
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  useEffect(() => {
    if (!orbit) return;
    let raf = 0, last = performance.now();
    const tick = (t: number) => { setPos((p) => ({ ...p, az: (p.az + ((t - last) / 1000) * 45) % 360 })); last = t; raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [orbit]);

  return (
    <main style={{ position: "fixed", inset: 0, zIndex: 25, background: "#0b0d10", color: "#e6e8eb", fontFamily: "system-ui" }}>
      <div ref={mount} data-testid="move-3d" style={{ position: "absolute", inset: 0 }} />
      <div style={{ position: "absolute", top: 16, left: 0, right: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 8, pointerEvents: "none" }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>Move the sound source</h1>
        <p data-testid="move-progress" data-ready={ready || undefined} style={{ margin: 0, opacity: 0.7 }}>
          {ready ? "Headphones on, press play. Drag the blue source; drag elsewhere to turn the view." : `Simulating the head: ${two.done} of ${two.need} runs`}
        </p>
      </div>
      <div style={{ position: "absolute", bottom: 24, left: 0, right: 0, display: "flex", gap: 12, alignItems: "center", justifyContent: "center" }}>
        <button type="button" disabled={!ready} onClick={playing ? stop : play}>{playing ? "Stop" : "Play"}</button>
        <label><input type="checkbox" checked={orbit} onChange={(e) => setOrbit(e.target.checked)} /> Orbit</label>
        <select value={clip} onChange={(e) => { setClip(e.target.value); stop(); }}>{SOUNDS.map((c) => <option key={c} value={c}>{c.replace("bank:", "")}</option>)}</select>
        {(["L", "R"] as const).map((e, i) => (
          <span key={e} style={{ display: "flex", alignItems: "center", gap: 4 }}>{e}
            <span data-testid={`meter-${e}`} data-level={level[i].toFixed(4)} style={{ width: 80, height: 8, background: "#1c2128", borderRadius: 4, overflow: "hidden" }}>
              <span style={{ display: "block", height: "100%", width: `${Math.min(100, level[i] * 300)}%`, background: "#5ab0ff" }} />
            </span>
          </span>
        ))}
        <span data-testid="move-pos" style={{ fontVariantNumeric: "tabular-nums" }}>az {Math.round(pos.az)}° · el {Math.round(pos.el)}°</span>
      </div>
    </main>
  );
}
