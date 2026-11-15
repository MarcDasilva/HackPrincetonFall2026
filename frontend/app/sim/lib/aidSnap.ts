// The patient's own ear with an earpiece seated in it: the option cards' pictures (components/AidOptions) and the picked
// piece on the head in the validation's tiles (HeadSnap). The ear skin (ear_skin.glb), the earpiece (hornsim.earpiece
// earpiece.glb) and the ear mesh share ONE frame, which head.json's mesh_to_head maps onto the head.
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const glbs = new Map<string, Promise<THREE.Object3D>>();
/** A GLB, cached. Vertex-coloured meshes (the photo-coloured ear, the orange piece) carry NO glTF material, and
 * GLTFLoader's default is fully metallic — black without an environment map — so they get a matte one. */
export function loadGlb(url: string): Promise<THREE.Object3D> {
  if (!glbs.has(url)) {
    const p = new GLTFLoader().loadAsync(url).then((g) => {
      g.scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (!m.isMesh) return;
        if (!m.geometry.attributes.normal) m.geometry.computeVertexNormals();
        m.material = new THREE.MeshStandardMaterial({ vertexColors: !!m.geometry.attributes.color, color: m.geometry.attributes.color ? 0xffffff : 0xf38c28, roughness: 0.65, metalness: 0, side: THREE.DoubleSide });
      });
      return g.scene;
    });
    p.catch(() => glbs.delete(url));   // a file not written yet must NOT stay failed for the session
    glbs.set(url, p);
  }
  return glbs.get(url)!;
}

const heads = new Map<string, Promise<Record<string, THREE.Matrix4> | null>>();
/** Each ear's mesh_to_head (head.json, row-major), or null for a patient without a head stage. */
export function meshToHead(pid: string) {
  if (!heads.has(pid)) {
    heads.set(pid, fetch(`/api/patients/${pid}/files/head/head.json`).then((r) => (r.ok ? r.json() : null)).then((h) => {
      if (!h?.ears) return null;
      const out: Record<string, THREE.Matrix4> = {};
      for (const [side, e] of Object.entries(h.ears as Record<string, { mesh_to_head?: number[] }>)) if (e.mesh_to_head) out[side] = new THREE.Matrix4().set(...(e.mesh_to_head as Parameters<THREE.Matrix4["set"]>));
      return out;
    }, () => null));
  }
  return heads.get(pid)!;
}

/** A copy of `obj` posed on the head (copies share geometry: one Object3D has ONE parent, and snaps interleave). */
export const posed = (obj: THREE.Object3D, m: THREE.Matrix4) => { const c = obj.clone(); c.applyMatrix4(m); return c; };

let renderer: THREE.WebGLRenderer | null = null;
/**
 * Two views side by side on one 2D canvas, through ONE shared WebGL renderer (Chrome drops the oldest past ~16
 * contexts): left, the piece seated in the patient's ear seen from outside the head; right, the piece on its own.
 * Rejects when a file or the head pose is missing — the card then keeps the backend's preview.png.
 */
export async function snapAid(canvas: HTMLCanvasElement, pid: string, side: "left" | "right", earUrl: string, pieceUrl: string) {
  const [ear, piece, poses] = await Promise.all([loadGlb(earUrl), loadGlb(pieceUrl), meshToHead(pid)]);
  const m = poses?.[side];
  if (!m) throw new Error("no head pose for this ear");
  renderer ??= new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  const w = canvas.width / 2, h = canvas.height, s = side === "left" ? 1 : -1;
  renderer.setSize(w, h, false);
  renderer.setClearColor(0x000000, 0);
  const g = canvas.getContext("2d")!;
  g.clearRect(0, 0, canvas.width, canvas.height);
  const shot = (objs: THREE.Object3D[], dir: THREE.Vector3, x: number) => {
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x50555c, 1.8));
    const key = new THREE.DirectionalLight(0xffffff, 1.2);
    key.position.copy(dir).multiplyScalar(200).add(new THREE.Vector3(0, 150, 0));
    scene.add(key, ...objs);
    // framed on the PIECE: the ear around it is context, cropped by the view
    const box = new THREE.Box3().setFromObject(objs[objs.length - 1]), c = box.getCenter(new THREE.Vector3());
    const r = box.getSize(new THREE.Vector3()).length() / 2 * (objs.length > 1 ? 2.1 : 1.15);
    const cam = new THREE.OrthographicCamera(-r * (w / h), r * (w / h), r, -r, 1, 2000);
    cam.position.copy(c).addScaledVector(dir.normalize(), 600);
    cam.lookAt(c);
    renderer!.render(scene, cam);
    g.drawImage(renderer!.domElement, x, 0);
  };
  // outward from the head on this ear's side, a little from the front and above, so the bowl reads
  shot([posed(ear, m), posed(piece, m)], new THREE.Vector3(s, 0.25, 0.35), 0);
  shot([posed(piece, m)], new THREE.Vector3(s * 0.7, 0.6, 0.9), w);
}
