// The overview tiles' picture: the scene as a lab measurement rig, drawn like a report figure (white, black ink).
// ONE shared WebGL renderer draws every tile and copies the frame onto the tile's 2D canvas — Chrome keeps ~16 WebGL
// contexts per page, so 100 live 3D tiles would kill the dashboard's metal rings (see SimRuns).
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

/** Head frame (backend head.json): mm, origin midway between the tragions, +x the person's LEFT, +y up, +z forward. */
const EAR_X = 85;
const SPEAKER_MM = 250;
const FLOOR = -330;
const INK = "#111111";
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

const heads = new Map<string, Promise<THREE.Object3D>>();

/** head_ears.glb from the head stage, in the head frame; a patient without one gets an average head. */
export function loadHead(pid: string): Promise<THREE.Object3D> {
  if (!heads.has(pid)) {
    heads.set(pid, new GLTFLoader().loadAsync(`/api/patients/${pid}/files/head/head_ears.glb`).then((g) => g.scene, averageHead));
  }
  return heads.get(pid)!;
}

// ponytail: an ellipsoid with ear stubs at mean adult head size (head.json dims_mm); swap for a shipped average-head GLB if it reads too crude.
function averageHead() {
  const g = new THREE.Group(), mat = new THREE.MeshStandardMaterial({ color: 0xe8e8e8, roughness: 0.8 });
  const skull = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 32), mat);
  skull.scale.set(80, 115, 102);
  skull.position.y = -20;
  g.add(skull);
  for (const s of [1, -1]) {
    const ear = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat);
    ear.scale.set(8, 30, 16);
    ear.position.set(s * (EAR_X + 4), 5, 0);
    g.add(ear);
  }
  return g;
}

/** Simulation azimuth (0 front, 90 the aided side, 180 behind) as a unit vector in the head frame. */
export function headDir(az: number, el: number, left: boolean) {
  const a = THREE.MathUtils.degToRad(az), e = THREE.MathUtils.degToRad(el);
  return new THREE.Vector3((left ? 1 : -1) * Math.cos(e) * Math.sin(a), Math.sin(e), Math.cos(e) * Math.cos(a));
}

let renderer: THREE.WebGLRenderer | null = null;
// ONE grey for every surface: the figure is monochrome, and the head's own GLB colours (skin, photo-tinted ears) would break it.
const GREY = new THREE.MeshStandardMaterial({ color: 0xdedede, roughness: 0.7 });

/** The tile's camera: yaw and pitch in degrees ON TOP of the default three-quarter view, zoom as a factor. */
export type View = { yaw: number; pitch: number; zoom: number };
export const DEFAULT_VIEW: View = { yaw: 0, pitch: 0, zoom: 1 };
const TARGET = new THREE.Vector3(0, -60, 0);

export async function snapHead(pid: string, left: boolean, sources: { role: "talker" | "babble"; az: number; el: number; level_db: number }[], canvas: HTMLCanvasElement, view: View = DEFAULT_VIEW) {
  const head = await loadHead(pid);
  renderer ??= new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(canvas.width, canvas.height, false);
  renderer.setClearColor(0xffffff, 1);

  const s = left ? 1 : -1, temp: { dispose(): void }[] = [];
  const keep = <T extends { dispose(): void }>(x: T) => (temp.push(x), x);
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x9a9a9a, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 1.0);
  key.position.set(s * 300, 500, 400);
  scene.add(key);

  // The shared head, greyed for this frame only: its own materials go back after the render.
  const saved = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
  head.traverse((o) => { const m = o as THREE.Mesh; if (m.isMesh) { saved.set(m, m.material); m.material = GREY; } });
  scene.add(head); // one parent at a time: the next snap re-parents it, and snaps run one after another
  const bbox = new THREE.Box3().setFromObject(head);
  const outline = new THREE.Box3Helper(bbox, 0x9a9a9a);
  scene.add(outline);
  temp.push(outline.geometry, outline.material as THREE.Material);

  const grid = new THREE.GridHelper(900, 18, 0xbdbdbd, 0xe6e6e6);
  grid.position.y = FLOOR;
  scene.add(grid);
  temp.push(grid.geometry, grid.material as THREE.Material);
  const metal = keep(new THREE.MeshStandardMaterial({ color: 0x8a8a8a, roughness: 0.5 }));
  const pole = (x: number, z: number, top: number, r: number) => {
    const m = new THREE.Mesh(keep(new THREE.CylinderGeometry(r, r, top - FLOOR, 16)), metal);
    m.position.set(x, (top + FLOOR) / 2, z);
    return m;
  };
  scene.add(pole(0, 0, bbox.min.y + 10, 14));

  const ear = new THREE.Vector3(s * EAR_X, 0, 0);
  const dark = keep(new THREE.MeshStandardMaterial({ color: 0x2a2a2a, roughness: 0.6 }));
  const black = keep(new THREE.MeshBasicMaterial({ color: 0x111111 }));
  const pale = keep(new THREE.MeshStandardMaterial({ color: 0xb4b4b4, roughness: 0.6 }));
  const ringMat = keep(new THREE.LineBasicMaterial({ color: 0x9a9a9a }));
  const circle = keep(new THREE.BufferGeometry().setFromPoints(Array.from({ length: 64 }, (_, i) => new THREE.Vector3(Math.cos((i / 64) * Math.PI * 2), 0, Math.sin((i / 64) * Math.PI * 2)))));
  const spk = sources.map((src) => {
    const p = headDir(src.az, src.el, left).multiplyScalar(SPEAKER_MM);
    // A dodecahedron: the lab's omnidirectional source, as the simulation's point source radiates equally every way.
    // Talker solid, babble pale — role by SHADE, so the figure needs no colour. The rings mark sound leaving in ALL directions.
    const src3 = new THREE.Mesh(keep(new THREE.DodecahedronGeometry(16)), src.role === "talker" ? dark : pale);
    src3.position.copy(p);
    const edge = new THREE.LineSegments(keep(new THREE.EdgesGeometry(src3.geometry)), ringMat);
    edge.position.copy(p);
    scene.add(src3, edge);
    for (const r of [34, 58, 82]) {
      const ring = new THREE.LineLoop(circle, ringMat);
      ring.position.copy(p);
      ring.scale.setScalar(r);
      scene.add(ring);
    }
    const ray = new THREE.Line(keep(new THREE.BufferGeometry().setFromPoints([p, ear])), keep(new THREE.LineDashedMaterial({ color: 0x111111, dashSize: 8, gapSize: 6 })));
    ray.computeLineDistances();
    scene.add(pole(p.x, p.z, p.y - 16, 4), ray);
    return p;
  });
  const rx = new THREE.Mesh(keep(new THREE.SphereGeometry(4, 16, 12)), black);
  rx.position.copy(ear);
  scene.add(rx);

  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 6000);
  const half = 340 / view.zoom, aspect = canvas.width / canvas.height;
  Object.assign(camera, { left: -half * aspect, right: half * aspect, top: half, bottom: -half });
  // Orbit the default view about the rig's centre; pitch stays between just above the floor and straight down.
  const orbit = new THREE.Spherical().setFromVector3(new THREE.Vector3(s * 700, 560, 700).sub(TARGET));
  orbit.theta += THREE.MathUtils.degToRad(view.yaw);
  orbit.phi = THREE.MathUtils.clamp(orbit.phi - THREE.MathUtils.degToRad(view.pitch), 0.05, Math.PI / 2 - 0.02);
  camera.position.setFromSpherical(orbit).add(TARGET);
  camera.lookAt(TARGET);
  camera.updateProjectionMatrix();
  renderer.render(scene, camera);

  const g = canvas.getContext("2d")!;
  g.clearRect(0, 0, canvas.width, canvas.height);
  g.drawImage(renderer.domElement, 0, 0);
  const P = (p: THREE.Vector3): [number, number] => { const v = p.clone().project(camera); return [((v.x + 1) / 2) * canvas.width, ((1 - v.y) / 2) * canvas.height]; };
  const text = (t: string, x: number, y: number, align: CanvasTextAlign = "left", size = 12) => { g.font = `${size}px ${MONO}`; g.fillStyle = INK; g.textAlign = align; g.fillText(t, x, y); };
  g.strokeStyle = INK;
  g.lineWidth = 1;
  spk.forEach((p, i) => {
    const [x, y] = P(p), right = x > canvas.width / 2, dx = right ? 16 : -16;
    g.beginPath(); g.moveTo(x, y - 18); g.lineTo(x + dx, y - 32); g.lineTo(x + dx * 1.6, y - 32); g.stroke();
    text(`S${i + 1} ${sources[i].level_db} dB`, x + dx * 1.6 + (right ? 4 : -4), y - 28, right ? "left" : "right");
  });
  const [ex, ey] = P(ear);
  text("RX", ex + (s > 0 ? 8 : -8), ey + 16, s > 0 ? "left" : "right", 11);
  // Scale bar on the floor: 100 mm, measured through the SAME projection as the rig.
  const a = P(new THREE.Vector3(-380, FLOOR, 380)), b = P(new THREE.Vector3(-280, FLOOR, 380));
  g.lineWidth = 2;
  g.beginPath(); g.moveTo(...a); g.lineTo(...b); g.stroke();
  g.lineWidth = 1;
  text("100 mm", (a[0] + b[0]) / 2, a[1] + 16, "center", 11);

  scene.remove(head);
  for (const [m, mat] of saved) m.material = mat;
  temp.forEach((t) => t.dispose());
}
