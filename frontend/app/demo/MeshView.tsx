"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/** Node names written by backend/hornsim/aid.py: the ear and shell draw see-through so the bore and vent show inside — rename there and the horn hides behind the skin here. */
const SEE_THROUGH: Record<string, number> = { ear: 0.32, shell: 0.28 };

/** The skin has ~22k triangles: at card size its lines sit ~1 px apart and grey the photo colours out, so they fade with the view. */
const lineOpacity = (h: number) => Math.min(0.45, Math.max(0.1, h / 1000));

/** Rotatable GLB in millimetres. `snap` slides every non-ear node in from beside the ear, so the horn seats on screen. `skin` is the ear look from backend ear_world.skin: photo colours plus the mesh lines drawn on the surface. */
export default function MeshView({ url, snap = false, height = 320, label, skin = false }: { url?: string; snap?: boolean; height?: number; label: string; skin?: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ok" | "error">(url ? "loading" : "error");

  useEffect(() => {
    const el = host.current;
    if (!el || !url) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(2, devicePixelRatio));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f98, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    scene.add(sun);
    const camera = new THREE.PerspectiveCamera(32, 1, 1, 2000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.8;
    controls.enableZoom = false; // page scroll on phones must not zoom the model
    const moving: { obj: THREE.Object3D; to: number; off: number }[] = [];
    let t0 = 0, raf = 0, dead = false;

    const resize = () => {
      const w = el.clientWidth;
      renderer.setSize(w, height);
      camera.aspect = w / height;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    new GLTFLoader().load(url, (gltf) => {
      if (dead) return;
      const root = gltf.scene;
      root.traverse((o) => {
        if (!(o instanceof THREE.Mesh)) return;
        const op = SEE_THROUGH[o.name] ?? SEE_THROUGH[o.parent?.name ?? ""];
        const m = new THREE.MeshStandardMaterial({ vertexColors: !!o.geometry.attributes.color, roughness: 0.65, metalness: 0, side: THREE.DoubleSide });
        if (!o.geometry.attributes.color) m.color.set(0xd6a08c);
        if (skin) {
          // The GLB stores photo colours as sRGB bytes, but glTF vertex colours are read as linear — convert, or the skin renders washed out.
          const c = o.geometry.attributes.color, k = new THREE.Color();
          if (c) for (let i = 0; i < c.count; i++) { k.setRGB(c.getX(i), c.getY(i), c.getZ(i), THREE.SRGBColorSpace); c.setXYZ(i, k.r, k.g, k.b); }
          o.geometry.computeVertexNormals();
          // offset pushes the surface back so the mesh lines on it win the depth test
          Object.assign(m, { roughness: 0.6, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
          o.add(new THREE.LineSegments(new THREE.WireframeGeometry(o.geometry), new THREE.LineBasicMaterial({ color: 0x4a3a30, transparent: true, opacity: lineOpacity(height) })));
        }
        if (snap && op !== undefined) Object.assign(m, { transparent: true, opacity: op, depthWrite: false });
        o.material = m;
      });
      const box = new THREE.Box3().setFromObject(root);
      const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() / 2;
      root.position.sub(c);
      // Canonical frame (specs/00): +x lateral, so the camera looks at the ear from outside the head.
      camera.position.set(r * 3.2, r * 0.6, r * 1.2);
      sun.position.set(r * 4, r * 3, r * 2);
      controls.target.set(0, 0, 0);
      if (snap) root.children.forEach((o) => {
        if (o.name === "ear") return;
        moving.push({ obj: o, to: o.position.x, off: r * 1.4 });
      });
      scene.add(root);
      setState("ok");
      t0 = performance.now();
    }, undefined, () => !dead && setState("error"));

    const tick = (now: number) => {
      const k = Math.min(1, (now - t0 - 500) / 900);
      const e = k <= 0 ? 0 : 1 - Math.pow(1 - k, 3);
      for (const { obj, to, off } of moving) obj.position.x = to + (1 - e) * off;
      controls.update();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      dead = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [url, snap, height, skin]);

  return (
    <div style={{ position: "relative", height }} aria-label={label} role="img" data-testid="mesh" data-state={state}>
      <div ref={host} style={{ position: "absolute", inset: 0, cursor: "grab" }} />
      {state !== "ok" && (
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", color: "#5d636c", fontSize: 13, textAlign: "center", padding: 16 }}>
          {state === "loading" ? "Loading mesh…" : `Mesh not available${url ? `: ${url}` : " in this manifest"}`}
        </div>
      )}
    </div>
  );
}
