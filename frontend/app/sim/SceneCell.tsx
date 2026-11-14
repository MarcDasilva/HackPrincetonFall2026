"use client";
// One scene: a head-and-torso dummy wearing both of the patient's ears, the live pressure field on a
// horizontal slice at ear height, and talkers you drag around it. Only a talker's direction is
// simulated (a far plane wave); the markers sit on a sphere outside the wave box to show where.
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { HeadGrid, Side } from "./lib/fdtd";
import { SIDES, speakerMm } from "./lib/fdtd";
import { dirKey, type Scene, type Source } from "./lib/scenes";
import type { FrameStore } from "./SimGrid";
import styles from "./sim.module.css";

export const ROLE_COLOR = { talker: "#d95926", babble: "#3987e5" } as const;
const DUMMY = 0x76797c;      // matte grey, like a measurement head
const DUMMY_EAR = 0x8a8d90;

export type CellStatus = { state: "idle" | "queued" | "running" | "done"; done: number; total: number };
export type EarSii = Record<Side, { healthy: number; unaided: number; aided?: number } | null>;

type Props = {
  grid: HeadGrid;
  solid: Uint8Array;
  scene: Scene;
  status: CellStatus;
  sii: EarSii;
  /** per-direction pressure frames; the cell replays the level-weighted sum of its own sources */
  store: FrameStore;
  onMove: (sourceId: string, az: number, el: number) => void;
  onCommit: () => void;
  onChange: (s: Scene) => void;
  onRemoveSource: (sourceId: string) => void;
  onAddSource: (role: Source["role"]) => void;
};

/** Head, neck and shoulders from the SAME shape the wave grid voxelized (hornsim.head_grid.HEAD). */
function buildDummy(grid: HeadGrid) {
  const g = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({ color: DUMMY, roughness: 0.88, metalness: 0.04 });
  const ell = (e: { center: number[]; axes: number[] }, geo: THREE.BufferGeometry) => {
    const m = new THREE.Mesh(geo, mat);
    m.scale.set(e.axes[0], e.axes[1], e.axes[2]);
    m.position.set(e.center[0], e.center[1], e.center[2]);
    return m;
  };
  const H = grid.head;
  g.add(new THREE.Mesh(carvedHead(grid), mat));
  const neck = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 48, 1, true), mat);
  neck.scale.set(H.neck.axes_xz[0], H.neck.y[1] - H.neck.y[0], H.neck.axes_xz[1]);
  neck.position.set(H.neck.center_xz[0], (H.neck.y[0] + H.neck.y[1]) / 2, H.neck.center_xz[1]);
  g.add(neck);
  // shoulders: the upper part of the torso ellipsoid, closed by a flat cap (a bust on a stand)
  const cut = 0.62 * Math.PI;
  g.add(ell(H.torso, new THREE.SphereGeometry(1, 64, 32, 0, Math.PI * 2, 0, cut)));
  const capR = Math.sin(cut), capY = Math.cos(cut);
  const cap = new THREE.Mesh(new THREE.CircleGeometry(1, 64), mat);
  cap.rotation.x = Math.PI / 2;
  cap.scale.set(H.torso.axes[0] * capR, H.torso.axes[2] * capR, 1);
  cap.position.set(H.torso.center[0], H.torso.center[1] + H.torso.axes[1] * capY, H.torso.center[2]);
  g.add(cap);
  const stand = new THREE.Mesh(new THREE.CylinderGeometry(9, 9, 120, 24), new THREE.MeshStandardMaterial({ color: 0x55585c, roughness: 0.5, metalness: 0.6 }));
  stand.position.set(H.torso.center[0], cap.position.y - 60, H.torso.center[2]);
  g.add(stand);
  // a mouth slit and the reference crosses on the temples, as on a measurement head
  const dark = new THREE.MeshBasicMaterial({ color: 0x2b2d30 });
  const P = H.profile;
  const yChin = P.y[0], yTop = P.y[P.y.length - 1];
  /** point and outward normal on the head surface at height y, angle t (0 = right, -π/2 = front) */
  const onHead = (y: number, t: number) => {
    const w = interp(y, P.y, P.w), d = interp(y, P.y, P.d), c = interp(y, P.y, P.c);
    const pt = new THREE.Vector3(w * Math.cos(t), y, c + d * Math.sin(t));
    const n = new THREE.Vector3(Math.cos(t) / w, 0, Math.sin(t) / d).normalize();
    return { pt, n };
  };
  const place = (o: THREE.Object3D, y: number, t: number, lift: number) => {
    const { pt, n } = onHead(y, t);
    o.position.copy(pt).addScaledVector(n, lift);
    o.lookAt(o.position.clone().add(n));
  };
  {
    const mouth = new THREE.Mesh(new THREE.CapsuleGeometry(1.6, 12, 4, 8), dark);
    place(mouth, yChin + 0.3 * (0 - yChin), -Math.PI / 2, 0.6);   // a third of the way up from chin to the canal line
    mouth.rotateZ(Math.PI / 2);
    g.add(mouth);
  }
  for (const t of [-Math.PI / 2 + 0.75, -Math.PI / 2 - 0.75]) {
    for (const rot of [0, Math.PI / 2]) {
      const bar = new THREE.Mesh(new THREE.PlaneGeometry(14, 0.9), dark);
      place(bar, 0.3 * yTop, t, 0.4);
      bar.rotateZ(rot);
      g.add(bar);
    }
  }
  // both of the patient's ears, slid onto the head by the grid export; the canal opening (where the
  // grid's canal tube starts, on the concha floor) is marked by a dark disc facing out of the canal
  const earMat = new THREE.MeshStandardMaterial({ color: DUMMY_EAR, roughness: 0.82, metalness: 0.03, side: THREE.DoubleSide });
  const hole = new THREE.MeshBasicMaterial({ color: 0x141517, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2 });
  for (const s of SIDES) {
    const e = grid.ears[s];
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(e.mesh.verts, 3));
    geo.setIndex(e.mesh.faces);
    geo.computeVertexNormals();
    g.add(new THREE.Mesh(geo, earMat));
    const ax = new THREE.Vector3(...e.canal_axis);
    const disc = new THREE.Mesh(new THREE.CircleGeometry(e.canal_diameter_mm / 2, 32), hole);
    disc.position.set(...e.canal_point_mm).addScaledVector(ax, -0.6);
    disc.lookAt(disc.position.clone().sub(ax));
    g.add(disc);
  }
  return g;
}

const CARVE_MM = 1.5;   // the carved head sits this far under the pinna, so its coarser triangles never poke through

/** Pinna surface x at (y, z): bilinear where all four lattice points are inside the outline, else nearest. */
function surfaceAt(S: HeadGrid["ears"]["left"]["surface"], y: number, z: number): number | null {
  const u = (y - S.y0) / S.d, w = (z - S.z0) / S.d;
  if (u < 0 || w < 0 || u > S.ny - 1 || w > S.nz - 1) return null;
  const i = Math.min(S.ny - 2, Math.floor(u)), k = Math.min(S.nz - 2, Math.floor(w)), fu = u - i, fw = w - k;
  const q = [S.x[i * S.nz + k], S.x[(i + 1) * S.nz + k], S.x[i * S.nz + k + 1], S.x[(i + 1) * S.nz + k + 1]];
  if (q.every((v) => v !== null)) {
    const [a, b, c, d] = q as number[];
    return a * (1 - fu) * (1 - fw) + b * fu * (1 - fw) + c * (1 - fu) * fw + d * fu * fw;
  }
  return S.x[Math.round(u) * S.nz + Math.round(w)];
}

function interp(x: number, xs: number[], ys: number[]) {
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  let i = 1;
  while (xs[i] < x) i++;
  const t = (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
  return ys[i - 1] + t * (ys[i] - ys[i - 1]);
}

/** The head from its profile (hornsim/head_shape.py: stacked horizontal ellipses), fine enough to carve:
 * wherever it rises above a pinna's surface (the concha floor sits below the head's curve) it is pushed
 * just under it. That is the shape hornsim.head_grid voxelizes: under the pinna, the pinna rules. */
function carvedHead(grid: HeadGrid) {
  const P = grid.head.profile;
  const SEG = 320, DY = 1.2;
  const y0 = P.y[0], y1 = P.y[P.y.length - 1];
  const rings = Math.max(2, Math.ceil((y1 - y0) / DY) + 1);
  const pos: number[] = [], idx: number[] = [];
  for (let r = 0; r < rings; r++) {
    const y = y0 + ((y1 - y0) * r) / (rings - 1);
    const w = interp(y, P.y, P.w), d = interp(y, P.y, P.d), c = interp(y, P.y, P.c);
    for (let k = 0; k < SEG; k++) {
      const t = (2 * Math.PI * k) / SEG;
      pos.push(w * Math.cos(t), y, c + d * Math.sin(t));
    }
  }
  for (let r = 0; r < rings - 1; r++) for (let k = 0; k < SEG; k++) {
    const a = r * SEG + k, b = r * SEG + ((k + 1) % SEG), a2 = a + SEG, b2 = b + SEG;
    idx.push(a, a2, b, b, a2, b2);
  }
  // caps: chin and crown
  for (const [r, y, flip] of [[0, y0, true], [rings - 1, y1, false]] as const) {
    const c = interp(y, P.y, P.c), centre = pos.length / 3;
    pos.push(0, y + (flip ? -0.5 : 0.5), c);
    for (let k = 0; k < SEG; k++) {
      const a = r * SEG + k, b = r * SEG + ((k + 1) % SEG);
      if (flip) idx.push(centre, a, b); else idx.push(centre, b, a);
    }
  }
  const ears = SIDES.map((s) => ({ s: s === "right" ? 1 : -1, e: grid.ears[s] }));
  for (let k = 0; k < pos.length; k += 3) {
    for (const { s, e } of ears) {
      const x = pos[k];
      if (s * x <= 0) continue;
      const sx = surfaceAt(e.surface, pos[k + 1], pos[k + 2]);
      if (sx === null) continue;
      if (s * (x - sx) > -CARVE_MM) pos[k] = sx - s * CARVE_MM;   // carve the head out from under the pinna
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  return geo;
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
    const camera = new THREE.PerspectiveCamera(32, 1, 5, 5000);
    const front = new THREE.Vector3(...grid.front), right = new THREE.Vector3(...grid.right);
    // three-quarter view from the front right, a little above
    camera.position.copy(front.clone().multiplyScalar(560).addScaledVector(right, 380).add(new THREE.Vector3(0, 200, 0)));
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, -45, 0);
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.minDistance = 300;
    controls.maxDistance = 1400;
    scene3.add(new THREE.HemisphereLight(0xffffff, 0x3c4046, 1.35));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(260, 380, -320);
    scene3.add(key);
    const rim = new THREE.DirectionalLight(0xbfd4ff, 0.7);
    rim.position.set(-300, 120, 300);
    scene3.add(rim);

    scene3.add(buildDummy(grid));

    const [nx, ny, nz] = grid.shape, dx = grid.dx_mm;
    const lo = new THREE.Vector3(...grid.origin_mm);
    const size = new THREE.Vector3((nx - 1) * dx, (ny - 1) * dx, (nz - 1) * dx);
    // the wave box, faint: the field lives inside it
    scene3.add(new THREE.Box3Helper(new THREE.Box3(lo, lo.clone().add(size)), new THREE.Color(0x4a505c)));

    // live pressure slice: horizontal, through the receivers' row (ear height)
    const row = Math.round((grid.ears.left.receiver[1] + grid.ears.right.receiver[1]) / 2);
    const sliceY = lo.y + row * dx;
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
    const solidRow = (i: number, l: number) => solid[i * ny * nz + row * nz + l];
    const paint = (slice: Float32Array) => {
      let m = 0;
      for (let k = 0; k < slice.length; k++) m = Math.max(m, Math.abs(slice[k]));
      peak = Math.max(peak * 0.9, m, 1e-6);
      for (let i = 0; i < nx; i++) for (let l = 0; l < nz; l++) {
        const s = slice[i * nz + l] / peak, o = (l * nx + i) * 4;
        if (solidRow(i, l)) { data.set([0, 0, 0, 0], o); continue; }   // the head itself is drawn as a mesh
        const a = Math.min(1, Math.abs(s) * 1.6);
        if (s >= 0) data.set([235, 104, 52, Math.round(a * 225)], o);
        else data.set([57, 135, 229, Math.round(a * 225)], o);
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
      const runs = srcs.map((s) => ({ f: cb.current.store.get(dirKey(s.az, s.el)), a: 10 ** ((s.levelDb - 65) / 20) })).filter((r) => r.f && r.f.length);
      if (!runs.length) return;
      const len = Math.max(...runs.map((r) => r.f!.length));
      frame = (frame + 1) % (len + 20);            // short pause between loops
      sum.fill(0);
      if (frame < len) for (const r of runs) { const sl = r.f![Math.min(frame, r.f!.length - 1)]; for (let k = 0; k < sum.length; k++) sum[k] += r.a * sl[k]; }
      paint(sum);
    };

    // talker sphere (directions) and talkers
    const R = grid.radius_mm;
    const sph = new THREE.Mesh(new THREE.SphereGeometry(R, 32, 16),
      new THREE.MeshBasicMaterial({ color: 0x9aa3b5, wireframe: true, transparent: true, opacity: 0.05 }));
    scene3.add(sph);
    const group = new THREE.Group();
    scene3.add(group);
    const markers = new Map<string, THREE.Mesh>();
    const setSources = (srcs: Source[]) => {
      for (const [id, m] of markers) if (!srcs.find((s) => s.id === id)) { group.remove(m, m.userData.line); markers.delete(id); }
      for (const s of srcs) {
        let m = markers.get(s.id);
        if (!m) {
          m = new THREE.Mesh(new THREE.SphereGeometry(9, 20, 14), new THREE.MeshStandardMaterial({ color: ROLE_COLOR[s.role], emissive: ROLE_COLOR[s.role], emissiveIntensity: 0.35 }));
          m.userData.id = s.id;
          const line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: ROLE_COLOR[s.role], transparent: true, opacity: 0.55, dashSize: 8, gapSize: 6 }));
          m.userData.line = line;
          group.add(m, line);
          markers.set(s.id, m);
        }
        m.position.set(...speakerMm(grid, s.az, s.el));
        const line = m.userData.line as THREE.Line;
        line.geometry.setFromPoints([m.position.clone().multiplyScalar(0.62), m.position.clone()]);
        line.computeLineDistances();
      }
    };
    api.current = { setSources };
    setSources(cb.current.scene.sources);

    // drag a talker over the sphere
    const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
    const [elMin, elMax] = grid.el_range;
    let dragging: string | null = null;
    const toNdc = (e: PointerEvent) => {
      const r = renderer.domElement.getBoundingClientRect();
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
    };
    const sphere = new THREE.Sphere(new THREE.Vector3(), R);
    const down = (e: PointerEvent) => {
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
      const elv = THREE.MathUtils.clamp(THREE.MathUtils.radToDeg(Math.asin(THREE.MathUtils.clamp(d.y, -1, 1))), elMin, elMax);
      const az = (THREE.MathUtils.radToDeg(Math.atan2(d.dot(right), d.dot(front))) + 360) % 360;
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

  const pct = status.total ? Math.round((status.done / status.total) * 100) : 0;
  const fmt = (v?: number) => (v === undefined ? "–" : v.toFixed(2));
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
        </div>
        <div className={styles.siiRow} title="SII per ear: healthy ear / this ear unaided → with its earpiece">
          {SIDES.map((s) => {
            const v = props.sii[s];
            return (
              <span key={s} className={styles.num}>
                <b>{s === "left" ? "L" : "R"}</b> SII {fmt(v?.healthy)} / {fmt(v?.unaided)}{v?.aided !== undefined && <> → {fmt(v.aided)}</>}
              </span>
            );
          })}
        </div>
      </div>
    </div>
  );
}
