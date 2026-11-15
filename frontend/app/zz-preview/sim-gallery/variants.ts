// PREVIEW ONLY: ten technical renderings of ONE simulation scene (head, aided ear, speakers), to pick a look for the sim tiles.
// Every variant builds its own three.js scene from the SAME Env; overlays (labels, scales, traces) draw on a 2D canvas on top.
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { headDir } from "@/app/sim/HeadSnap";

type V3 = THREE.Vector3;
const V = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const C_MM_PER_MS = 343;
export const R = 250;

export type Src = { role: "talker" | "babble"; az: number; el: number; level_db: number };
export type Head = { skull: THREE.BufferGeometry; ears: THREE.BufferGeometry; box: THREE.Box3 };
export type Env = { head: Head; left: boolean; s: number; ear: V3; srcs: Src[]; spk: V3[]; name: string };
type Project = (p: V3) => [number, number];
export type Built = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera | THREE.OrthographicCamera;
  /** false: the variant draws several fixed views (no orbit). */
  controls?: boolean;
  tick?(t: number): void;
  render?(r: THREE.WebGLRenderer, w: number, h: number): void;
  draw?(g: CanvasRenderingContext2D, P: Project, t: number, w: number, h: number): void;
};
export type Variant = { key: string; title: string; caption: string; bg: string; build(e: Env): Built };

const ROLE = { talker: 0xff6a2b, babble: 0x3d8bff } as const;
const roleCss = (r: Src["role"]) => `#${ROLE[r].toString(16).padStart(6, "0")}`;

/** The head GLB's meshes in head mm, split into skull and ears (ears sit beyond |x| 60 mm), position + normal only. */
export function prepHead(obj: THREE.Object3D): Head {
  obj.updateMatrixWorld(true);
  const skull: THREE.BufferGeometry[] = [], ears: THREE.BufferGeometry[] = [];
  obj.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    let g = m.geometry.clone().applyMatrix4(m.matrixWorld);
    if (!g.index) g = g.toNonIndexed();
    for (const k of Object.keys(g.attributes)) if (k !== "position" && k !== "normal") g.deleteAttribute(k);
    if (!g.attributes.normal) g.computeVertexNormals();
    g.computeBoundingBox();
    (Math.abs(g.boundingBox!.getCenter(V()).x) > 60 ? ears : skull).push(g);
  });
  const merge = (gs: THREE.BufferGeometry[]) => (gs.length ? mergeGeometries(gs)! : new THREE.BufferGeometry());
  const out = { skull: merge(skull), ears: merge(ears), box: new THREE.Box3() };
  out.box.setFromBufferAttribute(out.skull.attributes.position as THREE.BufferAttribute);
  return out;
}

export function makeEnv(head: Head, left: boolean, srcs: Src[], name: string): Env {
  const s = left ? 1 : -1;
  return { head, left, s, ear: V(s * 85, 0, 0), srcs, name, spk: srcs.map((x) => headDir(x.az, x.el, left).multiplyScalar(R)) };
}

// ---------------------------------------------------------------- helpers

const persp = (fov: number, pos: V3, target = V(0, -20, 0)) => {
  const c = new THREE.PerspectiveCamera(fov, 1, 1, 6000);
  c.position.copy(pos);
  c.userData.target = target;
  c.lookAt(target);
  return c;
};
/** half: half the view's height in mm; the card's resize sets left/right from its aspect. */
const ortho = (half: number, pos: V3, up = V(0, 1, 0), target = V()) => {
  const c = new THREE.OrthographicCamera(-half, half, half, -half, 1, 6000);
  c.userData.half = half;
  c.userData.target = target;
  c.up.copy(up);
  c.position.copy(pos);
  c.lookAt(target);
  return c;
};
const wire = (g: THREE.BufferGeometry, color: number, opacity: number) =>
  new THREE.LineSegments(new THREE.WireframeGeometry(g), new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false }));
const edges = (g: THREE.BufferGeometry, color: number, opacity: number, deg = 30) =>
  new THREE.LineSegments(new THREE.EdgesGeometry(g, deg), new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
const line = (pts: V3[], color: number, opacity = 1, dashed = false) => {
  const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), dashed
    ? new THREE.LineDashedMaterial({ color, dashSize: 8, gapSize: 6, transparent: true, opacity })
    : new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
  if (dashed) l.computeLineDistances();
  return l;
};
const ball = (p: V3, color: number, r = 9, basic = false) => {
  const m = new THREE.Mesh(new THREE.SphereGeometry(r, 20, 14), basic ? new THREE.MeshBasicMaterial({ color }) : new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.6 }));
  m.position.copy(p);
  return m;
};
const lights = (scene: THREE.Scene, k = 1) => {
  scene.add(new THREE.HemisphereLight(0xffffff, 0x30343c, 1.2 * k));
  const d = new THREE.DirectionalLight(0xffffff, 1.1 * k);
  d.position.set(300, 500, 400);
  scene.add(d);
};
const arc = (r: number, a0: number, a1: number, el: (a: number) => number, left: boolean, n = 48) =>
  Array.from({ length: n + 1 }, (_, i) => { const a = a0 + ((a1 - a0) * i) / n; return headDir(a, el(a), left).multiplyScalar(r); });

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
function txt(g: CanvasRenderingContext2D, s: string, x: number, y: number, color = "#9fb3c8", size = 11, align: CanvasTextAlign = "left") {
  g.font = `${size}px ${MONO}`;
  g.fillStyle = color;
  g.textAlign = align;
  g.fillText(s, x, y);
}
function hud(g: CanvasRenderingContext2D, rows: string[], x: number, y: number, color = "#6f8296") {
  rows.forEach((r, i) => txt(g, r, x, y + i * 14, color, 10.5));
}
function callout(g: CanvasRenderingContext2D, [x, y]: [number, number], label: string, color: string, dx = 14, dy = -14) {
  // Flip to the side with room: a label running off the card edge is worse than one on the "wrong" side.
  g.font = `10.5px ${MONO}`;
  const tw = g.measureText(label).width + 26, W = g.canvas.width / (g.getTransform().a || 1);
  if (dx >= 0 && x + dx + tw > W) dx = -Math.abs(dx);
  else if (dx < 0 && x + dx - tw < 0) dx = Math.abs(dx);
  g.strokeStyle = color;
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(x, y);
  g.lineTo(x + dx, y + dy);
  g.lineTo(x + dx + (dx >= 0 ? 8 : -8), y + dy);
  g.stroke();
  txt(g, label, x + dx + (dx >= 0 ? 11 : -11), y + dy + 3.5, color, 10.5, dx >= 0 ? "left" : "right");
}
const srcLabel = (s: Src, i: number) => `S${i + 1} ${s.role.toUpperCase()}  az ${s.az}°  el ${s.el}°  ${s.level_db} dB`;

const STOPS = [[0.05, 0.08, 0.35], [0.1, 0.4, 0.95], [0.1, 0.85, 0.85], [0.55, 0.95, 0.3], [0.98, 0.85, 0.2], [0.95, 0.25, 0.12]];
export function ramp(t: number) {
  const x = THREE.MathUtils.clamp(t, 0, 1) * (STOPS.length - 1), i = Math.min(STOPS.length - 2, Math.floor(x)), f = x - i;
  return new THREE.Color(...(STOPS[i].map((a, k) => a + (STOPS[i + 1][k] - a) * f) as [number, number, number]));
}
function colorbar(g: CanvasRenderingContext2D, x: number, y: number, h: number, lo: string, hi: string, title: string) {
  for (let i = 0; i < h; i++) { g.fillStyle = `#${ramp(1 - i / h).getHexString()}`; g.fillRect(x, y + i, 10, 1); }
  g.strokeStyle = "#3a4656";
  g.strokeRect(x - 0.5, y - 0.5, 11, h + 1);
  txt(g, hi, x + 16, y + 8, "#9fb3c8", 10);
  txt(g, lo, x + 16, y + h, "#9fb3c8", 10);
  txt(g, title, x + 10, y - 8, "#6f8296", 10, "center");
}
/** A dimension line between two screen points with end ticks and its value. */
function dim(g: CanvasRenderingContext2D, a: [number, number], b: [number, number], label: string, color: string) {
  g.strokeStyle = color;
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(...a); g.lineTo(...b);
  const nx = -(b[1] - a[1]), ny = b[0] - a[0], n = Math.hypot(nx, ny) || 1;
  for (const p of [a, b]) { g.moveTo(p[0] - (nx / n) * 4, p[1] - (ny / n) * 4); g.lineTo(p[0] + (nx / n) * 4, p[1] + (ny / n) * 4); }
  g.stroke();
  txt(g, label, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 5, color, 10.5, "center");
}
/** Section lines: where planes perpendicular to `axis` (every `step` mm) cut the mesh — the technical-drawing look a smooth mesh lacks. */
function contours(geo: THREE.BufferGeometry, axis: 0 | 1 | 2, step: number, color: number, opacity: number) {
  const p = geo.attributes.position as THREE.BufferAttribute, idx = geo.index!, out: number[] = [];
  const a = V(), b = V(), c = V();
  for (let f = 0; f < idx.count; f += 3) {
    a.fromBufferAttribute(p, idx.getX(f)); b.fromBufferAttribute(p, idx.getX(f + 1)); c.fromBufferAttribute(p, idx.getX(f + 2));
    const va = a.getComponent(axis), vb = b.getComponent(axis), vc = c.getComponent(axis);
    for (let k = Math.ceil(Math.min(va, vb, vc) / step) * step; k <= Math.max(va, vb, vc); k += step) {
      const hits: V3[] = [];
      for (const [u, w, du, dw] of [[a, b, va, vb], [b, c, vb, vc], [c, a, vc, va]] as const) if ((du - k) * (dw - k) < 0) hits.push(u.clone().lerp(w, (k - du) / (dw - du)));
      if (hits.length === 2) out.push(...hits[0].toArray(), ...hits[1].toArray());
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(out, 3));
  return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
}
const vertsOf = (g: THREE.BufferGeometry) => {
  const p = g.attributes.position as THREE.BufferAttribute, n = g.attributes.normal as THREE.BufferAttribute;
  return { p, n, count: p.count };
};

// ---------------------------------------------------------------- the ten

export const VARIANTS: Variant[] = [
  {
    key: "cad", title: "CAD wireframe", bg: "#07090d",
    caption: "Mesh topology, bounding box with measured dimensions, axis triad and labelled sources.",
    build(e) {
      const scene = new THREE.Scene();
      scene.add(wire(e.head.skull, 0x4fd1ff, 0.13), wire(e.head.ears, 0xffb347, 0.4), new THREE.Box3Helper(e.head.box, 0x2c3a48));
      for (const [ax, c] of [[V(90, 0, 0), 0xff4d4d], [V(0, 90, 0), 0x4dff88], [V(0, 0, 90), 0x4d9dff]] as const) scene.add(line([V(), ax], c));
      e.spk.forEach((p, i) => {
        const m = new THREE.Mesh(new THREE.OctahedronGeometry(11), new THREE.MeshBasicMaterial({ color: ROLE[e.srcs[i].role], wireframe: true }));
        m.position.copy(p);
        scene.add(m, line([p, e.ear], ROLE[e.srcs[i].role], 0.7, true));
      });
      scene.add(ball(e.ear, 0xffffff, 4, true));
      const camera = persp(32, V(e.s * 560, 300, 700));
      const b = e.head.box, size = b.getSize(V());
      return {
        scene, camera,
        draw(g, P, _t, w, h) {
          txt(g, "X", ...P(V(100, 0, 0)), "#ff4d4d", 11); txt(g, "Y", ...P(V(0, 100, 0)), "#4dff88", 11); txt(g, "Z", ...P(V(0, 0, 100)), "#4d9dff", 11);
          dim(g, P(V(b.min.x, b.max.y + 12, b.max.z)), P(V(b.max.x, b.max.y + 12, b.max.z)), `${size.x.toFixed(1)} mm`, "#7f93a8");
          dim(g, P(V(e.s * (b.max.x + 14), b.min.y, b.max.z)), P(V(e.s * (b.max.x + 14), b.max.y, b.max.z)), `${size.y.toFixed(1)}`, "#7f93a8");
          e.spk.forEach((p, i) => { const s = e.srcs[i]; callout(g, P(p), `S${i + 1} ${s.az}°/${s.el}° ${s.level_db} dB`, roleCss(s.role), P(p)[0] > w / 2 ? 14 : -14, -18); });
          callout(g, P(e.ear), "RX", "#e6e8eb", -14, 22);
          hud(g, e.srcs.map(srcLabel), w - 250, h - 38);
          hud(g, ["VIEW  persp 32°", "UNITS mm", "FRAME head, tragion midpoint", `VERTS ${e.head.skull.attributes.position.count + e.head.ears.attributes.position.count}`], 12, h - 52);
        },
      };
    },
  },
  {
    key: "blueprint", title: "Blueprint three-view", bg: "#0b3474",
    caption: "Orthographic front, side and plan elevations with a drawing title block.",
    build(e) {
      const scene = new THREE.Scene();
      const fill = new THREE.MeshBasicMaterial({ color: 0x0b3474, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
      scene.add(new THREE.Mesh(e.head.skull, fill), new THREE.Mesh(e.head.ears, fill),
        contours(e.head.skull, 1, 12, 0xffffff, 0.75), contours(e.head.skull, 2, 12, 0xffffff, 0.45), contours(e.head.ears, 1, 4, 0xffffff, 0.6));
      e.spk.forEach((p) => scene.add(ball(p, 0xffffff, 7, true), line([p, e.ear], 0xffffff, 0.6, true)));
      const views = [
        { name: "FRONT ELEVATION", cam: ortho(320, V(0, 0, 1500)) },
        { name: `SIDE ELEVATION (${e.left ? "L" : "R"})`, cam: ortho(320, V(e.s * 1500, 0, 0)) },
        { name: "PLAN", cam: ortho(320, V(0, 1500, 0), V(0, 0, -1)) },
      ];
      const quad = (i: number, w: number, h: number) => ({ x: (i % 2) * (w / 2), y: Math.floor(i / 2) * (h / 2), w: w / 2, h: h / 2 });
      return {
        scene, camera: views[0].cam, controls: false,
        render(r, w, h) {
          r.setScissorTest(true);
          r.setScissor(0, 0, w, h); r.setViewport(0, 0, w, h); r.clear();
          views.forEach((v, i) => {
            const q = quad(i, w, h), a = q.w / q.h, half = v.cam.userData.half as number;
            Object.assign(v.cam, { left: -half * a, right: half * a });
            v.cam.updateProjectionMatrix();
            r.setViewport(q.x, h - q.y - q.h, q.w, q.h); r.setScissor(q.x, h - q.y - q.h, q.w, q.h);
            r.render(scene, v.cam);
          });
          r.setScissorTest(false);
        },
        draw(g, _P, _t, w, h) {
          g.strokeStyle = "rgba(255,255,255,0.07)";
          g.lineWidth = 1;
          for (let x = 0; x < w; x += 16) { g.beginPath(); g.moveTo(x + 0.5, 0); g.lineTo(x + 0.5, h); g.stroke(); }
          for (let y = 0; y < h; y += 16) { g.beginPath(); g.moveTo(0, y + 0.5); g.lineTo(w, y + 0.5); g.stroke(); }
          g.strokeStyle = "rgba(255,255,255,0.6)";
          g.strokeRect(6.5, 6.5, w - 13, h - 13);
          g.beginPath(); g.moveTo(w / 2, 6); g.lineTo(w / 2, h - 6); g.moveTo(6, h / 2); g.lineTo(w - 6, h / 2); g.stroke();
          views.forEach((v, i) => {
            const q = quad(i, w, h);
            txt(g, v.name, q.x + 14, q.y + q.h - 12, "#ffffff", 10.5);
            const pr = (p: V3): [number, number] => { const s = p.clone().project(v.cam); return [q.x + ((s.x + 1) / 2) * q.w, q.y + ((1 - s.y) / 2) * q.h]; };
            if (i === 0) { const b = e.head.box; dim(g, pr(V(b.min.x, b.min.y - 18, 0)), pr(V(b.max.x, b.min.y - 18, 0)), `${(b.max.x - b.min.x).toFixed(0)}`, "#ffffff"); }
            if (i === 2) e.spk.forEach((p, k) => txt(g, `S${k + 1}`, pr(p)[0] + 10, pr(p)[1] - 8, "#ffffff", 10));
          });
          const q = quad(3, w, h), rows = [["AURIS ACOUSTIC LAB", ""], ["SCENE", e.name], ["SOURCES", `${e.srcs.length}`], ["RECEIVER", `${e.left ? "LEFT" : "RIGHT"} EAR CANAL`], ["SOURCE RADIUS", `${R} mm`], ["UNITS", "mm"], ["DWG", "SIM-001  REV A"]];
          const rx = q.x + 18, ry = q.y + 18, rw = q.w - 36, rh = 20;
          g.strokeStyle = "rgba(255,255,255,0.8)";
          rows.forEach(([k, v], j) => { g.strokeRect(rx + 0.5, ry + j * rh + 0.5, rw, rh); txt(g, k, rx + 6, ry + j * rh + 14, "#ffffff", j ? 10 : 11.5); if (v) txt(g, v, rx + rw - 6, ry + j * rh + 14, "#cfe0ff", 10, "right"); });
        },
      };
    },
  },
  {
    key: "polar", title: "Polar plan", bg: "#0a0d12",
    caption: "Top-down plan on an azimuth grid: rings every 100 mm, spokes every 15°, source levels as radial bars.",
    build(e) {
      const scene = new THREE.Scene();
      lights(scene, 0.8);
      scene.add(new THREE.Mesh(e.head.skull, new THREE.MeshStandardMaterial({ color: 0x2a3340, roughness: 0.9 })), new THREE.Mesh(e.head.ears, new THREE.MeshStandardMaterial({ color: 0xffb347, roughness: 0.7 })));
      e.spk.forEach((p, i) => scene.add(ball(p, ROLE[e.srcs[i].role], 10), line([p, e.ear], ROLE[e.srcs[i].role], 0.5, true)));
      const camera = ortho(330, V(0, 1500, 0), V(0, 0, 1));
      return {
        scene, camera,
        draw(g, P, _t, w, h) {
          const [cx, cy] = P(V()), px = Math.hypot(...(P(V(100, 0, 0)).map((v, i) => v - [cx, cy][i]) as [number, number]));
          g.lineWidth = 1;
          for (let r = 1; r <= 3; r++) { g.strokeStyle = r * 100 === 300 ? "#3a4656" : "#1f2833"; g.beginPath(); g.arc(cx, cy, r * px, 0, Math.PI * 2); g.stroke(); txt(g, `${r * 100}`, cx + 3, cy - r * px - 3, "#4a5a6c", 9.5); }
          for (let a = 0; a < 360; a += 15) {
            const [x, y] = P(headDir(a, 0, e.left).multiplyScalar(310));
            g.strokeStyle = a % 90 === 0 ? "#2f3b49" : "#161d26";
            g.beginPath(); g.moveTo(cx, cy); g.lineTo(x, y); g.stroke();
            if (a % 30 === 0) { const [lx, ly] = P(headDir(a, 0, e.left).multiplyScalar(325)); txt(g, `${a}°`, lx, ly + 4, a === 0 || a === 90 ? "#c9d4e0" : "#6f8296", 10, "center"); }
          }
          const [fx, fy] = P(V(0, 0, 360)); txt(g, "FRONT", fx, fy + 4, "#c9d4e0", 10, "center");
          e.spk.forEach((p, i) => {
            const [x, y] = P(p), d = Math.hypot(x - cx, y - cy), ux = (x - cx) / d, uy = (y - cy) / d, len = (e.srcs[i].level_db - 40) * 1.6;
            g.strokeStyle = roleCss(e.srcs[i].role); g.lineWidth = 4;
            g.beginPath(); g.moveTo(x + ux * 14, y + uy * 14); g.lineTo(x + ux * (14 + len), y + uy * (14 + len)); g.stroke(); g.lineWidth = 1;
            txt(g, `${e.srcs[i].level_db} dB`, x + ux * (24 + len), y + uy * (24 + len) + 4, roleCss(e.srcs[i].role), 10, "center");
          });
          hud(g, e.srcs.map(srcLabel), 12, h - 12 - 14 * (e.srcs.length - 1));
          hud(g, ["PLAN  orthographic", "az 0° = front, 90° = aided side"], w - 230, 20);
        },
      };
    },
  },
  {
    key: "points", title: "Point cloud scan", bg: "#05070a",
    caption: "Every mesh vertex as a height-coded point, with a sweeping scan plane like a structured-light capture.",
    build(e) {
      const scene = new THREE.Scene();
      const all = mergeGeometries([e.head.skull, e.head.ears])!;
      const pos = all.attributes.position as THREE.BufferAttribute, b = e.head.box, col = new Float32Array(pos.count * 3);
      for (let i = 0; i < pos.count; i++) ramp((pos.getY(i) - b.min.y) / (b.max.y - b.min.y)).toArray(col, i * 3);
      all.setAttribute("color", new THREE.BufferAttribute(col, 3));
      scene.add(new THREE.Points(all, new THREE.PointsMaterial({ size: 2, vertexColors: true, sizeAttenuation: false })));
      const plane = new THREE.Mesh(new THREE.PlaneGeometry(320, 320), new THREE.MeshBasicMaterial({ color: 0x3df5ff, transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false }));
      plane.rotation.x = -Math.PI / 2;
      const rim = edges(new THREE.PlaneGeometry(320, 320), 0x3df5ff, 0.6);
      rim.rotation.x = -Math.PI / 2;
      scene.add(plane, rim);
      e.spk.forEach((p, i) => scene.add(ball(p, ROLE[e.srcs[i].role], 6, true), line([p, e.ear], ROLE[e.srcs[i].role], 0.35)));
      const camera = persp(30, V(e.s * 600, 220, 640));
      let y = 0;
      return {
        scene, camera,
        tick(t) { y = b.min.y + ((Math.sin(t * 0.9) + 1) / 2) * (b.max.y - b.min.y); plane.position.y = y; rim.position.y = y; },
        draw(g, _P, _t, w, h) {
          hud(g, [`POINTS ${pos.count.toLocaleString()}`, `SCAN y = ${y.toFixed(1)} mm`, `EXTENT ${b.getSize(V()).toArray().map((v) => v.toFixed(0)).join(" × ")} mm`], 12, 20, "#3df5ff");
          colorbar(g, w - 70, 40, 120, `${b.min.y.toFixed(0)}`, `${b.max.y.toFixed(0)}`, "y mm");
          hud(g, e.srcs.map(srcLabel), 12, h - 12 - 14 * (e.srcs.length - 1));
        },
      };
    },
  },
  {
    key: "rays", title: "Acoustic ray fan", bg: "#080a0f",
    caption: "Direct-path rays from each source to the surface points it can see, brighter where they hit head-on.",
    build(e) {
      const scene = new THREE.Scene();
      lights(scene, 0.7);
      scene.add(new THREE.Mesh(e.head.skull, new THREE.MeshStandardMaterial({ color: 0x1d232b, roughness: 0.9 })), new THREE.Mesh(e.head.ears, new THREE.MeshStandardMaterial({ color: 0x3a3226 })));
      const { p, n, count } = vertsOf(e.head.skull), seg: number[] = [], col: number[] = [];
      let rays = 0;
      e.spk.forEach((sp, i) => {
        const c = new THREE.Color(ROLE[e.srcs[i].role]);
        for (let k = 0; k < count; k += 23) {
          const v = V(p.getX(k), p.getY(k), p.getZ(k)), d = sp.clone().sub(v).normalize(), inc = d.dot(V(n.getX(k), n.getY(k), n.getZ(k)));
          if (inc < 0.25) continue;
          seg.push(...sp.toArray(), ...v.toArray());
          const a = 0.15 + 0.85 * inc;
          col.push(c.r * 0.15, c.g * 0.15, c.b * 0.15, c.r * a, c.g * a, c.b * a);
          rays++;
        }
        scene.add(ball(sp, ROLE[e.srcs[i].role], 9));
      });
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
      geo.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
      scene.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false })));
      const camera = persp(32, V(e.s * 520, 380, 640));
      return {
        scene, camera,
        draw(g, P, _t, w, h) {
          e.spk.forEach((sp, i) => callout(g, P(sp), `S${i + 1} ${e.srcs[i].level_db} dB`, roleCss(e.srcs[i].role), P(sp)[0] > w / 2 ? 14 : -14));
          hud(g, [`RAYS ${rays}`, "direct path, visible surface only", "brightness = cos(incidence)"], 12, h - 38);
        },
      };
    },
  },
  {
    key: "waves", title: "Wavefront propagation", bg: "#06080c",
    caption: "Spherical wavefronts leaving each source at the speed of sound, slowed down, with arrival times at the ear.",
    build(e) {
      const scene = new THREE.Scene();
      lights(scene, 0.8);
      scene.add(new THREE.Mesh(e.head.skull, new THREE.MeshStandardMaterial({ color: 0x2b313a, roughness: 0.85 })), new THREE.Mesh(e.head.ears, new THREE.MeshStandardMaterial({ color: 0x5a4a3a })));
      const shells: { m: THREE.Mesh; k: number }[] = [];
      e.spk.forEach((sp, i) => {
        scene.add(ball(sp, ROLE[e.srcs[i].role], 8));
        for (let k = 0; k < 4; k++) {
          const m = new THREE.Mesh(new THREE.SphereGeometry(1, 36, 18), new THREE.MeshBasicMaterial({ color: ROLE[e.srcs[i].role], wireframe: true, transparent: true, opacity: 0.3, depthWrite: false }));
          m.position.copy(sp);
          scene.add(m);
          shells.push({ m, k });
        }
      });
      const camera = persp(34, V(e.s * 560, 420, 620));
      const MAX = 260, SPEED = 90;
      let lead = 0;
      return {
        scene, camera,
        tick(t) {
          lead = (t * SPEED) % MAX;
          for (const { m, k } of shells) { const r = (t * SPEED + k * (MAX / 4)) % MAX; m.scale.setScalar(Math.max(r, 0.01)); (m.material as THREE.MeshBasicMaterial).opacity = 0.22 * (1 - r / MAX); }
        },
        draw(g, P, _t, _w, h) {
          e.spk.forEach((sp, i) => {
            const d = sp.distanceTo(e.ear);
            callout(g, P(sp), `S${i + 1}  ${d.toFixed(0)} mm  →  ${(d / C_MM_PER_MS).toFixed(3)} ms`, roleCss(e.srcs[i].role), P(sp)[0] > P(V())[0] ? 14 : -14);
          });
          hud(g, [`t = ${(lead / C_MM_PER_MS).toFixed(3)} ms`, "c = 343 m/s", `shown ${Math.round(C_MM_PER_MS * 1000 / SPEED).toLocaleString()}× slower`], 12, h - 38, "#9fb3c8");
        },
      };
    },
  },
  {
    key: "surface", title: "Head-shadow surface map", bg: "#07090c",
    caption: "Level-weighted incidence from all sources painted onto the head: where sound lands, where the head shadows it.",
    build(e) {
      const scene = new THREE.Scene();
      lights(scene, 0.6);
      const amp = e.srcs.map((s) => 10 ** ((s.level_db - 65) / 20));
      const inc = (geo: THREE.BufferGeometry) => {
        const { p, n, count } = vertsOf(geo);
        return Float32Array.from({ length: count }, (_, i) => {
          const v = V(p.getX(i), p.getY(i), p.getZ(i)), nn = V(n.getX(i), n.getY(i), n.getZ(i));
          return e.spk.reduce((s, sp, k) => s + amp[k] * Math.max(0, sp.clone().sub(v).normalize().dot(nn)), 0);
        });
      };
      const vals = [inc(e.head.skull), inc(e.head.ears)];
      const top = Math.max(...vals.map((a) => a.reduce((m, x) => Math.max(m, x), 0)));
      let which = 0;
      const paint = (geo: THREE.BufferGeometry) => {
        const g = geo.clone(), x = vals[which++], col = new Float32Array(x.length * 3);
        x.forEach((v, i) => ramp(v / top).toArray(col, i * 3));
        g.setAttribute("color", new THREE.BufferAttribute(col, 3));
        return new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true }));
      };
      scene.add(paint(e.head.skull), paint(e.head.ears));
      e.spk.forEach((sp, i) => scene.add(ball(sp, ROLE[e.srcs[i].role], 8), line([sp, V()], ROLE[e.srcs[i].role], 0.35, true)));
      const camera = persp(30, V(e.s * 520, 260, 600));
      return {
        scene, camera,
        draw(g, P, _t, w, h) {
          colorbar(g, w - 90, 44, 140, "0 shadow", "1 direct", "incidence");
          e.spk.forEach((sp, i) => callout(g, P(sp), `S${i + 1} ${e.srcs[i].role} ${e.srcs[i].level_db} dB`, roleCss(e.srcs[i].role), P(sp)[0] > w / 2 ? -14 : 14));
          hud(g, ["Σ 10^(L/20) · max(0, n·d), scaled to the peak", "geometric estimate, not the FDTD field"], 12, h - 24);
        },
      };
    },
  },
  {
    key: "sphere", title: "Spherical coordinate rig", bg: "#080a10",
    caption: "Sources on the measurement sphere, with azimuth and elevation arcs and drop lines to the horizontal plane.",
    build(e) {
      const scene = new THREE.Scene();
      lights(scene, 0.8);
      scene.add(new THREE.Mesh(e.head.skull, new THREE.MeshStandardMaterial({ color: 0x8b93a0, roughness: 0.6, metalness: 0.1 })), new THREE.Mesh(e.head.ears, new THREE.MeshStandardMaterial({ color: 0xc9b39a })));
      for (let el = -60; el <= 75; el += 15) scene.add(line(arc(R, 0, 360, () => el, e.left, 96), el === 0 ? 0x4a5d73 : 0x1d2632, el === 0 ? 0.9 : 0.8));
      for (let az = 0; az < 360; az += 15) scene.add(line(Array.from({ length: 41 }, (_, i) => headDir(az, -90 + (180 * i) / 40, e.left).multiplyScalar(R)), 0x1d2632, 0.8));
      e.spk.forEach((sp, i) => {
        const s = e.srcs[i], c = ROLE[s.role], foot = headDir(s.az, 0, e.left).multiplyScalar(R * Math.cos(THREE.MathUtils.degToRad(s.el)));
        scene.add(ball(sp, c, 9), line([sp, foot], c, 0.8, true), line(arc(R * 0.45, 0, s.az, () => 0, e.left), c, 0.9), line(arc(R * 0.92, 0, s.el, () => 0, e.left).map((_, k, a) => headDir(s.az, (s.el * k) / (a.length - 1), e.left).multiplyScalar(R * 0.92)), c, 0.9), line([V(), headDir(s.az, 0, e.left).multiplyScalar(R * 0.5)], c, 0.4));
      });
      scene.add(line([V(), V(0, 0, R * 0.55)], 0xc9d4e0, 0.6));
      const camera = persp(34, V(e.s * 560, 520, 600), V(0, 0, 0));
      return {
        scene, camera,
        draw(g, P, _t, _w, h) {
          for (let a = 0; a < 360; a += 30) txt(g, `${a}°`, ...P(headDir(a, 0, e.left).multiplyScalar(R * 1.1)), a === 0 ? "#c9d4e0" : "#5a6b80", 10, "center");
          e.srcs.forEach((s, i) => {
            const [x, y] = P(headDir(s.az / 2, 0, e.left).multiplyScalar(R * 0.45));
            if (s.az) txt(g, `φ ${s.az}°`, x, y - 6, roleCss(s.role), 10, "center");
            if (s.el) { const [ex, ey] = P(headDir(s.az, s.el / 2, e.left).multiplyScalar(R * 0.92)); txt(g, `θ ${s.el}°`, ex + 8, ey, roleCss(s.role), 10); }
            callout(g, P(e.spk[i]), `S${i + 1}`, roleCss(s.role), 12, -12);
          });
          hud(g, [`r = ${R} mm`, "φ azimuth from front toward aided side", "θ elevation above ear plane", "grid 15°"], 12, h - 52);
        },
      };
    },
  },
  {
    key: "rig", title: "Measurement rig, isometric", bg: "#0c0e12",
    caption: "The scene as a physical lab setup: head on a stand, speakers on stands, floor grid, scale bar and dimensions.",
    build(e) {
      const scene = new THREE.Scene();
      lights(scene, 1);
      const FLOOR = -330;
      const grid = new THREE.GridHelper(900, 18, 0x3a4350, 0x1e242c);
      grid.position.y = FLOOR;
      scene.add(grid, new THREE.Mesh(e.head.skull, new THREE.MeshStandardMaterial({ color: 0xd8dade, roughness: 0.55 })), new THREE.Mesh(e.head.ears, new THREE.MeshStandardMaterial({ color: 0xe0c7ae, roughness: 0.6 })));
      const metal = new THREE.MeshStandardMaterial({ color: 0x6b7480, metalness: 0.6, roughness: 0.35 });
      const pole = (x: number, z: number, top: number, r = 6) => { const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, top - FLOOR, 16), metal); m.position.set(x, (top + FLOOR) / 2, z); return m; };
      scene.add(pole(0, 0, e.head.box.min.y + 10, 14));
      e.spk.forEach((sp, i) => {
        const cab = new THREE.Mesh(new THREE.BoxGeometry(34, 46, 30), new THREE.MeshStandardMaterial({ color: 0x23272e, roughness: 0.6 }));
        cab.position.copy(sp);
        cab.lookAt(e.ear);
        const cone = new THREE.Mesh(new THREE.CircleGeometry(11, 24), new THREE.MeshStandardMaterial({ color: ROLE[e.srcs[i].role], emissive: ROLE[e.srcs[i].role], emissiveIntensity: 0.4 }));
        cone.position.set(0, 4, 15.5);
        cab.add(cone);
        scene.add(cab, pole(sp.x, sp.z, sp.y - 23, 4), line([sp, e.ear], ROLE[e.srcs[i].role], 0.5, true));
      });
      scene.add(new THREE.Box3Helper(e.head.box, 0x5a6b80));
      const camera = ortho(340, V(e.s * 700, 560, 700), V(0, 1, 0), V(0, -60, 0));
      return {
        scene, camera,
        draw(g, P, _t, w, h) {
          const a = P(V(-350, FLOOR, 380)), b = P(V(-250, FLOOR, 380));
          g.strokeStyle = "#c9d4e0"; g.lineWidth = 2; g.beginPath(); g.moveTo(...a); g.lineTo(...b); g.stroke(); g.lineWidth = 1;
          txt(g, "100 mm", (a[0] + b[0]) / 2, a[1] + 16, "#c9d4e0", 10, "center");
          const bx = e.head.box, s = bx.getSize(V());
          callout(g, P(V(bx.max.x, bx.max.y, bx.max.z)), `HEAD ${s.x.toFixed(0)} × ${s.y.toFixed(0)} × ${s.z.toFixed(0)} mm`, "#9fb3c8", 16, -16);
          e.spk.forEach((sp, i) => callout(g, P(sp), `S${i + 1}  h ${(sp.y - FLOOR).toFixed(0)} mm`, roleCss(e.srcs[i].role), P(sp)[0] > w / 2 ? 14 : -14));
          hud(g, ["ISOMETRIC  orthographic", "floor grid 50 mm", `ear height ${(e.ear.y - FLOOR).toFixed(0)} mm`], 12, h - 38);
        },
      };
    },
  },
  {
    key: "scope", title: "Oscilloscope HUD", bg: "#020805",
    caption: "Phosphor wireframe with one channel per source: the click as it arrives at the ear, delayed and scaled by distance.",
    build(e) {
      const scene = new THREE.Scene();
      scene.add(wire(e.head.skull, 0x33ff88, 0.12), wire(e.head.ears, 0x33ff88, 0.4));
      e.spk.forEach((sp) => scene.add(ball(sp, 0x33ff88, 7, true), line([sp, e.ear], 0x33ff88, 0.45, true)));
      const camera = persp(36, V(e.s * 560, 300, 640), V(e.s * -160, -20, 120));
      const ch = e.spk.map((sp, i) => { const d = sp.distanceTo(e.ear); return { d, dt: d / C_MM_PER_MS, amp: 10 ** ((e.srcs[i].level_db - 65) / 20) * (R / d) }; });
      return {
        scene, camera,
        draw(g, P, t, w, h) {
          const x0 = w * 0.56, pw = w - x0 - 14, ph = (h - 28) / ch.length - 8, T = 1.4, SIG = 0.035;
          ch.forEach((c, i) => {
            const y0 = 14 + i * (ph + 8);
            g.strokeStyle = "rgba(51,255,136,0.35)"; g.strokeRect(x0 + 0.5, y0 + 0.5, pw, ph);
            g.strokeStyle = "rgba(51,255,136,0.08)";
            for (let k = 1; k < 10; k++) { g.beginPath(); g.moveTo(x0 + (pw * k) / 10, y0); g.lineTo(x0 + (pw * k) / 10, y0 + ph); g.stroke(); }
            for (let k = 1; k < 4; k++) { g.beginPath(); g.moveTo(x0, y0 + (ph * k) / 4); g.lineTo(x0 + pw, y0 + (ph * k) / 4); g.stroke(); }
            g.strokeStyle = "#33ff88"; g.lineWidth = 1.4; g.shadowColor = "#33ff88"; g.shadowBlur = 6;
            g.beginPath();
            for (let k = 0; k <= pw; k++) {
              const tt = (k / pw) * T - c.dt, v = (-tt / SIG) * Math.exp(-(tt * tt) / (2 * SIG * SIG)) * c.amp;
              const y = y0 + ph / 2 - v * ph * 0.42;
              if (k) g.lineTo(x0 + k, y); else g.moveTo(x0, y);
            }
            g.stroke(); g.shadowBlur = 0; g.lineWidth = 1;
            const s = e.srcs[i];
            txt(g, `CH${i + 1}  ${s.role.toUpperCase()} ${s.az}°/${s.el}°`, x0 + 6, y0 + 13, "#33ff88", 10);
            txt(g, `Δt ${c.dt.toFixed(3)} ms   ${(20 * Math.log10(c.amp)).toFixed(1)} dB`, x0 + pw - 6, y0 + 13, "#1fa85a", 10, "right");
          });
          const sx = x0 + ((t * 0.35) % 1) * pw;
          g.strokeStyle = "rgba(51,255,136,0.5)"; g.beginPath(); g.moveTo(sx, 14); g.lineTo(sx, h - 14); g.stroke();
          txt(g, `0 – ${T} ms`, x0 + pw, h - 4, "#1fa85a", 9.5, "right");
          e.spk.forEach((sp, i) => txt(g, `CH${i + 1}`, P(sp)[0] + 10, P(sp)[1] - 8, "#33ff88", 10));
          hud(g, ["RX ear canal entrance", "click σ 35 µs, free field, 1/r", `TRIG ${(t % 3).toFixed(2)} s`], 12, h - 38, "#1fa85a");
        },
      };
    },
  },
];
