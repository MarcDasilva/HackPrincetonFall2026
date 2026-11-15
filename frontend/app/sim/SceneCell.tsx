"use client";
// One scene: the ear inside its wave-sim box, a live pressure slice through the canal opening, and
// speakers you drag around a sphere centred on the canal opening.
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { EarGrid } from "./lib/fdtd";
import { speakerMm } from "./lib/fdtd";
import { dirKey, type Scene, type Source } from "./lib/scenes";
import type { FrameStore } from "./SimGrid";
import styles from "./sim.module.css";

export const ROLE_COLOR = { talker: "#d95926", babble: "#3987e5" } as const;
const AZ_RANGE: [number, number] = [0, 180];
const EL_RANGE: [number, number] = [-60, 70];

export type CellStatus = { state: "idle" | "queued" | "running" | "done"; done: number; total: number };

type Props = {
  grid: EarGrid;
  solid: Uint8Array;
  scene: Scene;
  status: CellStatus;
  siiUnaided?: number;
  siiHealthy?: number;
  siiAided?: number;
  /** per-direction pressure frames; the cell replays the level-weighted sum of its own sources */
  store: FrameStore;
  onMove: (sourceId: string, az: number, el: number) => void;
  onCommit: () => void;
  onChange: (s: Scene) => void;
  onRemoveSource: (sourceId: string) => void;
  onAddSource: (role: Source["role"]) => void;
  /** Just the 3D view, NO editing: speakers stay put and the scene controls are not drawn (SimRuns' detail view). */
  bare?: boolean;
};

function local(grid: EarGrid, p: number[]) {
  const c = grid.canal_point_mm;
  return new THREE.Vector3(p[0] - c[0], p[1] - c[1], p[2] - c[2]);
}

export default function SceneCell(props: Props) {
  const { grid, solid, scene, status } = props;
  const mount = useRef<HTMLDivElement>(null);
  const api = useRef<{ setSources: (s: Source[]) => void } | null>(null);
  const cb = useRef(props);
  cb.current = props;

  useEffect(() => {
    const el = mount.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const scene3 = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 1, 2000);
    const f = grid.front;
    // camera out from the ear and a little forward and up
    camera.position.set(150, 70, 0).addScaledVector(new THREE.Vector3(f[0], f[1], f[2]), 90);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = false;
    scene3.add(new THREE.HemisphereLight(0xffffff, 0x50555c, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.0);
    key.position.set(150, 200, 80);
    scene3.add(key);

    const [nx, ny, nz] = grid.shape, dx = grid.dx_mm;
    const lo = local(grid, grid.origin_mm);
    const size = new THREE.Vector3((nx - 1) * dx, (ny - 1) * dx, (nz - 1) * dx);

    // box edges + a sparse lattice of air cells: the grid the wave lives on
    const box = new THREE.Box3(lo, lo.clone().add(size));
    scene3.add(new THREE.Box3Helper(box, new THREE.Color(0x5b6170)));
    const lat: number[] = [];
    for (let i = 0; i < nx; i += 4) for (let j = 0; j < ny; j += 4) for (let l = 0; l < nz; l += 4)
      if (!solid[i * ny * nz + j * nz + l]) lat.push(lo.x + i * dx, lo.y + j * dx, lo.z + l * dx);
    const latGeo = new THREE.BufferGeometry();
    latGeo.setAttribute("position", new THREE.Float32BufferAttribute(lat, 3));
    scene3.add(new THREE.Points(latGeo, new THREE.PointsMaterial({ color: 0x7c8494, size: 1.1, transparent: true, opacity: 0.35 })));

    // ear mesh
    const c = grid.canal_point_mm;
    const v = Float32Array.from(grid.mesh.verts, (x, i) => x - c[i % 3]);
    const earGeo = new THREE.BufferGeometry();
    earGeo.setAttribute("position", new THREE.BufferAttribute(v, 3));
    earGeo.setIndex(grid.mesh.faces);
    earGeo.computeVertexNormals();
    scene3.add(new THREE.Mesh(earGeo, new THREE.MeshStandardMaterial({ color: 0xd9ab97, roughness: 0.8, side: THREE.DoubleSide })));

    // head plane (rigid) and canal marker
    const hx = grid.x_head_mm - c[0];
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(size.z, size.y), new THREE.MeshBasicMaterial({ color: 0x8a8f99, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false }));
    plane.rotation.y = Math.PI / 2;
    plane.position.set(hx, lo.y + size.y / 2, lo.z + size.z / 2);
    scene3.add(plane);
    const ax = new THREE.Vector3(...grid.canal_axis);
    const canal = new THREE.Mesh(new THREE.CylinderGeometry(grid.canal_diameter_mm / 2, grid.canal_diameter_mm / 2, grid.canal_len_mm, 20, 1, true),
      new THREE.MeshBasicMaterial({ color: 0x8fb7ff, transparent: true, opacity: 0.45, side: THREE.DoubleSide }));
    canal.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), ax);
    canal.position.copy(ax.clone().multiplyScalar(grid.canal_len_mm / 2));
    scene3.add(canal);

    // live pressure slice (horizontal, through the receiver row)
    const sliceY = lo.y + grid.receiver[1] * dx;
    const data = new Uint8Array(nx * nz * 4);
    const tex = new THREE.DataTexture(data, nx, nz);
    tex.magFilter = THREE.LinearFilter;
    tex.needsUpdate = true;
    const q = new THREE.BufferGeometry();
    const x0 = lo.x, x1 = lo.x + size.x, z0 = lo.z, z1 = lo.z + size.z;
    q.setAttribute("position", new THREE.Float32BufferAttribute([x0, sliceY, z0, x1, sliceY, z0, x1, sliceY, z1, x0, sliceY, z1], 3));
    q.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
    q.setIndex([0, 1, 2, 0, 2, 3]);
    scene3.add(new THREE.Mesh(q, new THREE.MeshBasicMaterial({ map: tex, transparent: true, side: THREE.DoubleSide, depthWrite: false })));
    let peak = 1e-6;
    const solidRow = (i: number, l: number) => solid[i * ny * nz + grid.receiver[1] * nz + l];
    const paint = (slice: Float32Array) => {
      let m = 0;
      for (let k = 0; k < slice.length; k++) m = Math.max(m, Math.abs(slice[k]));
      peak = Math.max(peak * 0.9, m, 1e-6);
      for (let i = 0; i < nx; i++) for (let l = 0; l < nz; l++) {
        const s = slice[i * nz + l] / peak, o = (l * nx + i) * 4;
        if (solidRow(i, l)) { data.set([60, 62, 68, 70], o); continue; }
        const a = Math.min(1, Math.abs(s) * 1.6);
        if (s >= 0) data.set([235, 104, 52, Math.round(a * 230)], o);
        else data.set([57, 135, 229, Math.round(a * 230)], o);
      }
      tex.needsUpdate = true;
    };
    // linear acoustics: the scene's field is the sum of each source's field, scaled by its level
    const sum = new Float32Array(nx * nz);
    let frame = 0, lastPaint = 0;
    const compose = (now: number) => {
      if (now - lastPaint < 40) return;
      lastPaint = now;
      const srcs = cb.current.scene.sources;
      const runs = srcs.map((s) => ({ f: props.store.get(dirKey(s.az, s.el)), a: 10 ** ((s.levelDb - 65) / 20) })).filter((r) => r.f && r.f.length);
      if (!runs.length) return;
      const len = Math.max(...runs.map((r) => r.f!.length));
      frame = (frame + 1) % (len + 20);            // short pause between loops
      sum.fill(0);
      if (frame < len) for (const r of runs) { const sl = r.f![Math.min(frame, r.f!.length - 1)]; for (let k = 0; k < sum.length; k++) sum[k] += r.a * sl[k]; }
      paint(sum);
    };

    // speaker sphere (aided half) and speakers
    const sph = new THREE.Mesh(new THREE.SphereGeometry(grid.radius_mm, 24, 12, 0, Math.PI * 2, 0, Math.PI),
      new THREE.MeshBasicMaterial({ color: 0x9aa3b5, wireframe: true, transparent: true, opacity: 0.07 }));
    scene3.add(sph);
    const group = new THREE.Group();
    scene3.add(group);
    const markers = new Map<string, THREE.Mesh>();
    const setSources = (srcs: Source[]) => {
      for (const [id, m] of markers) if (!srcs.find((s) => s.id === id)) { group.remove(m); markers.delete(id); }
      for (const s of srcs) {
        let m = markers.get(s.id);
        if (!m) {
          m = new THREE.Mesh(new THREE.SphereGeometry(4.2, 20, 14), new THREE.MeshStandardMaterial({ color: ROLE_COLOR[s.role], emissive: ROLE_COLOR[s.role], emissiveIntensity: 0.35 }));
          m.userData.id = s.id;
          const line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: ROLE_COLOR[s.role], transparent: true, opacity: 0.5 }));
          m.userData.line = line;
          group.add(m, line);
          markers.set(s.id, m);
        }
        m.position.copy(local(grid, speakerMm(grid, s.az, s.el)));
        (m.userData.line as THREE.Line).geometry.setFromPoints([new THREE.Vector3(), m.position.clone()]);
      }
    };
    api.current = { setSources };
    setSources(cb.current.scene.sources);

    // drag a speaker over the sphere
    const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
    const front = new THREE.Vector3(...grid.front), lateral = new THREE.Vector3(1, 0, 0);
    let dragging: string | null = null;
    const toNdc = (e: PointerEvent) => {
      const r = renderer.domElement.getBoundingClientRect();
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
    };
    const sphere = new THREE.Sphere(new THREE.Vector3(), grid.radius_mm);
    const down = (e: PointerEvent) => {
      if (cb.current.bare) return;
      toNdc(e);
      const hit = ray.intersectObjects([...markers.values()])[0];
      if (!hit) return;
      dragging = hit.object.userData.id;
      controls.enabled = false;
      renderer.domElement.setPointerCapture(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      if (!dragging) return;
      toNdc(e);
      const p = ray.ray.intersectSphere(sphere, new THREE.Vector3());
      if (!p) return;
      const d = p.normalize();
      const elv = THREE.MathUtils.clamp(THREE.MathUtils.radToDeg(Math.asin(THREE.MathUtils.clamp(d.y, -1, 1))), ...EL_RANGE);
      const az = THREE.MathUtils.clamp(THREE.MathUtils.radToDeg(Math.atan2(d.dot(lateral), d.dot(front))), ...AZ_RANGE);
      cb.current.onMove(dragging, az, elv);
    };
    const up = () => {
      if (!dragging) return;
      dragging = null;
      controls.enabled = true;
      cb.current.onCommit();
    };
    renderer.domElement.addEventListener("pointerdown", down);
    renderer.domElement.addEventListener("pointermove", move);
    renderer.domElement.addEventListener("pointerup", up);

    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();
    let raf = 0;
    const tick = (now = 0) => { compose(now); controls.update(); renderer.render(scene3, camera); raf = requestAnimationFrame(tick); };
    tick();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      el.removeChild(renderer.domElement);
      api.current = null;
    };
    // the 3D scene is built once per grid; sources update through api.current
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid, solid]);

  useEffect(() => { api.current?.setSources(scene.sources); }, [scene.sources]);

  if (props.bare) return <div ref={mount} className={styles.view} style={{ aspectRatio: "1", borderRadius: 12, overflow: "hidden", background: "#0b0b0d" }} />;
  const pct = status.total ? Math.round((status.done / status.total) * 100) : 0;
  return (
    <div className={styles.cell}>
      <div className={styles.cellHead}>
        <input className={styles.cellName} value={scene.name} aria-label="Scene name"
          onChange={(e) => props.onChange({ ...scene, name: e.target.value })} />
        {scene.condition && <span className={styles.tag}>{scene.condition}</span>}
        <span className={styles.status} data-state={status.state}>
          {status.state === "done" ? "done" : status.state === "idle" ? "—" : `${status.state} ${pct}%`}
        </span>
      </div>
      <div ref={mount} className={styles.view} />
      <div className={styles.cellFoot}>
        {scene.sources.map((s) => (
          <div key={s.id} className={styles.srcRow}>
            <span className={styles.dot} style={{ background: ROLE_COLOR[s.role] }} />
            <span className={styles.srcLabel}>{s.role}</span>
            <span className={styles.num}>{Math.round(s.az)}°/{Math.round(s.el)}°</span>
            <input type="range" min={40} max={85} step={1} value={s.levelDb} aria-label={`${s.role} level`}
              onChange={(e) => props.onChange({ ...scene, sources: scene.sources.map((x) => (x.id === s.id ? { ...x, levelDb: +e.target.value } : x)) })} />
            <span className={styles.num}>{s.levelDb} dB</span>
            <button className={styles.x} aria-label="Remove source" onClick={() => props.onRemoveSource(s.id)}>×</button>
          </div>
        ))}
        <div className={styles.srcRow}>
          <button className={styles.btn} onClick={() => props.onAddSource("talker")}>+ talker</button>
          <button className={styles.btn} onClick={() => props.onAddSource("babble")}>+ babble</button>
          <label className={styles.weight}>weight
            <input type="number" min={0} max={10} step={0.5} value={scene.weight}
              onChange={(e) => props.onChange({ ...scene, weight: Math.max(0, +e.target.value) })} />
          </label>
          <span className={styles.num} title="SII: healthy ear / this ear unaided → this ear with the earpiece">
            SII {props.siiHealthy?.toFixed(2) ?? "–"} / {props.siiUnaided?.toFixed(2) ?? "–"}
            {props.siiAided !== undefined && <> → {props.siiAided.toFixed(2)}</>}
          </span>
        </div>
      </div>
    </div>
  );
}
