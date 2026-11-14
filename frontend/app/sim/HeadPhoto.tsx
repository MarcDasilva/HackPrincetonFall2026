"use client";
// Front photo -> head shape. Face landmarks are found in the browser (lib/faceShape.ts); only those
// points go to the backend, which fits the head (hornsim/head_shape.py) and returns its outline so
// the person can check it against the photo before the simulation uses it.
import { useEffect, useRef, useState } from "react";
import { measureHead, type HeadShapeFit } from "./lib/api";
import styles from "./sim.module.css";

type Props = { onUse: (id: string) => void; onCancel?: () => void; required?: boolean };

export default function HeadPhoto({ onUse, onCancel, required }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "finding" | "fitting" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [fit, setFit] = useState<HeadShapeFit | null>(null);
  const img = useRef<HTMLImageElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  const pick = (f: File | undefined) => {
    if (!f) return;
    setFit(null); setError(null); setState("finding");
    setUrl(URL.createObjectURL(f));
  };

  const onLoad = async () => {
    const el = img.current!;
    try {
      setState("fitting");
      setFit(await measureHead(el));
      setState("done");
    } catch (e) {
      setError((e as Error).message);
      setState("error");
    }
  };

  // outline over the photo: the fitted head (solid where measured, dashed where assumed) and the face oval
  useEffect(() => {
    const c = canvas.current, el = img.current;
    if (!c || !el || !el.naturalWidth) return;
    c.width = el.naturalWidth; c.height = el.naturalHeight;
    const g = c.getContext("2d")!;
    g.clearRect(0, 0, c.width, c.height);
    if (!fit) return;
    const lw = Math.max(2, c.width / 300);
    const path = (pts: number[][], close: boolean) => { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); if (close) g.closePath(); };
    g.lineWidth = lw;
    if (fit.overlay.hair_outline_px) {           // what the segmenter saw: hair + face skin
      g.strokeStyle = "rgba(230,232,235,0.55)";
      path(fit.overlay.hair_outline_px, true);
      g.stroke();
    }
    g.strokeStyle = "#3987e5";
    g.setLineDash([lw * 3, lw * 2]);
    path(fit.overlay.silhouette_px, true);
    g.stroke();
    g.setLineDash([]);
    g.fillStyle = "#d95926";
    for (const [x, y] of fit.overlay.face_oval_px) { g.beginPath(); g.arc(x, y, lw * 1.4, 0, Math.PI * 2); g.fill(); }
    g.strokeStyle = "#199e70";
    path(fit.overlay.canal_line_px, false);
    g.stroke();
  }, [fit, url]);

  const m = fit?.meta;
  return (
    <div className={styles.headPhoto}>
      <div className={styles.panelHead}>
        <h2>Front photo: head shape</h2>
        {onCancel && <button className={styles.x} aria-label="Close" onClick={onCancel}>×</button>}
      </div>
      <p className={styles.caption}>
        {required && <b>Needed before simulating this patient. </b>}
        Face the camera straight on, eyes open, at arm&apos;s length. Hair is ignored. The photo stays on this device:
        only the positions of face landmarks are sent, and only the fitted head shape is kept.
      </p>
      <label className={styles.primary} style={{ display: "inline-block" }}>
        {url ? "Choose another photo" : "Take or choose a photo"}
        <input type="file" accept="image/*" capture="user" hidden onChange={(e) => pick(e.target.files?.[0])} />
      </label>
      {url && (
        <div className={styles.photoWrap}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img ref={img} src={url} alt="Front photo" onLoad={onLoad} />
          <canvas ref={canvas} />
        </div>
      )}
      {state === "finding" && <p className={styles.caption}>Finding the face… (the first time loads the face model)</p>}
      {state === "fitting" && <p className={styles.caption}>Fitting the head…</p>}
      {error && <p className={styles.errorBox}>{error}</p>}
      {m && (
        <>
          <div className={styles.legend}>
            <span><i style={{ background: "#d95926", borderRadius: "50%" }} /> face outline (measured)</span>
            <span><i className={styles.dash} style={{ borderTopColor: "#3987e5" }} /> head used in the simulation</span>
            <span><i className={styles.lineKey} style={{ borderTopColor: "#199e70" }} /> ear-canal height</span>
            {fit!.overlay.hair_outline_px && <span><i className={styles.lineKey} style={{ borderTopColor: "rgba(230,232,235,0.55)" }} /> hair + face outline</span>}
          </div>
          <table className={styles.table}>
            <tbody>
              <tr><td>Head breadth</td><td>{m.breadth_mm.toFixed(0)} mm</td><td className={styles.note}>{m.sources?.breadth ?? `cheekbones ${m.bizygomatic_mm.toFixed(0)} mm × 1.09`}</td></tr>
              <tr><td>Head length</td><td>{m.length_mm.toFixed(0)} mm</td><td className={styles.note}>assumed: adult length/breadth ratio</td></tr>
              <tr><td>Chin to crown</td><td>{(m.crown_mm - m.chin_mm).toFixed(0)} mm</td><td className={styles.note}>{m.sources?.crown ?? "crown assumed (hidden by hair)"}</td></tr>
              {m.vault_exponent !== undefined && <tr><td>Top of head</td><td>n = {m.vault_exponent.toFixed(2)}</td><td className={styles.note}>{m.sources?.vault ?? ""} (2 = dome, higher = flatter top)</td></tr>}
              <tr><td>Eye spacing</td><td>{m.ipd_mm.toFixed(0)} mm</td><td className={styles.note}>scale check (adults ~54–74)</td></tr>
              {m.yaw_deg !== null && <tr><td>Turned</td><td>{Math.abs(m.yaw_deg).toFixed(0)}°</td><td className={styles.note}>best under 12°</td></tr>}
            </tbody>
          </table>
          {fit!.warnings.map((w) => <p key={w} className={styles.errorBox}>{w}</p>)}
          <div className={styles.designBar}>
            <button className={styles.primary} onClick={() => onUse(fit!.id)}>Use this head</button>
          </div>
        </>
      )}
    </div>
  );
}
