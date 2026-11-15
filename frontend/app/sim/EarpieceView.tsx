"use client";
// The chosen earpiece seated in the ear (earpiece_in_ear.glb from hornsim.earpiece).
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import styles from "./sim.module.css";

/** `className` replaces the /sim panel's fixed 210px box — the dashboard's option viewer fills its own. */
export default function EarpieceView({ url, className = styles.earpiece }: { url: string; className?: string }) {
  const mount = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const el = mount.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.5, 2000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x50555c, 1.8));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(120, 160, 80);
    scene.add(key);
    let alive = true;
    new GLTFLoader().load(url, (g) => {
      if (!alive) return;
      const box = new THREE.Box3().setFromObject(g.scene);
      const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() / 2;
      g.scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.isMesh) (Array.isArray(m.material) ? m.material : [m.material]).forEach((mat) => { mat.side = THREE.DoubleSide; });
      });
      scene.add(g.scene);
      controls.target.copy(c);
      // Back far enough that the bounding sphere fits the 30° view, from the same angle as before.
      const dist = (r / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))) * 1.1;
      camera.position.copy(c).add(new THREE.Vector3(1.9, 0.6, 0.9).normalize().multiplyScalar(dist));
    }, undefined, (e) => setErr(String((e as Error).message ?? e)));

    const resize = () => {
      renderer.setSize(el.clientWidth, el.clientHeight, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      camera.aspect = el.clientWidth / Math.max(1, el.clientHeight);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();
    let raf = 0;
    const tick = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(tick); };
    tick();
    return () => { alive = false; cancelAnimationFrame(raf); ro.disconnect(); controls.dispose(); renderer.dispose(); renderer.forceContextLoss(); el.removeChild(renderer.domElement); };
  }, [url]);

  return (
    <div className={className} ref={mount}>
      {err && <p className={styles.caption}>Could not load the earpiece mesh: {err}</p>}
    </div>
  );
}
