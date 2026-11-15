"use client";
// The four designs as metal cards: the two-view render (in the ear, on its own) and a blue select
// button in the corner. A card click expands it into BOTH 3D models side by side to turn around.
// The 3D viewers mount ONLY while expanded — each owns a WebGL context, and Chrome drops the
// oldest past ~16 per page (the dashboard's metal rings share ONE offscreen renderer, so the cards are free).
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { MetalFx, SILVER } from "@/components/metal";
import EarpieceView from "@/app/sim/EarpieceView";
import { designFile } from "@/app/sim/lib/api";
import { snapAid } from "@/app/sim/lib/aidSnap";
import type { AidOption } from "@/lib/lead";
import s from "./AidOptions.module.css";

const Arrow = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M7 17 17 7M9 7h8v8" /></svg>
);

/** `around`: the orb's centre (screen px). The cards sit in ONE row IN FRONT of the orb, centred on it; ABSENT, or a screen too narrow, puts them in a row at the top. */
type Props = { runId: string; ear?: string | null; options: AidOption[]; onPick: (id: string) => void; around?: () => { x: number; y: number } | null };

const GAP = 24;
/** "meets N of M key bands" is design jargon the patient NEVER sees; designs saved before scene_design.reason dropped it
 * still carry it (the agents server's no_key_bands strips it the SAME way for the report). */
const plain = (reason: string) => reason.replace(/(:\s*)?\b[Mm]eets \d+ of \d+ key bands,?\s*/g, (_, colon) => (colon ? ", " : ""));

/** The card's picture: the piece seated in the patient's OWN photo-coloured ear, then on its own (lib/aidSnap). The
 * backend's preview.png (a pale, see-through ear) shows ONLY until that renders, or if it cannot (no ear skin, no head). */
function Preview({ runId, ear, src, piece, alt }: { runId: string; ear?: string | null; src: string; piece: string; alt: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [ok, setOk] = useState(false);
  useEffect(() => {
    if (ear !== "left" && ear !== "right") return;
    let live = true;
    snapAid(canvas.current!, runId, ear, `/api/patients/${runId}/files/${ear}/ear_skin.glb`, piece).then(() => live && setOk(true), () => {});
    return () => { live = false; };
  }, [runId, ear, piece]);
  return (
    <>
      {!ok && <img className={s.preview} src={src} alt={alt} />}
      <canvas ref={canvas} data-testid="aid-preview" width={560} height={300} role="img" aria-label={alt} className={s.preview} style={{ display: ok ? "block" : "none" }} />
    </>
  );
}

export default function AidOptions({ runId, ear, options, onPick, around }: Props) {
  const [open, setOpen] = useState<number | null>(null);
  // The orb moves (GSAP) and the window resizes: re-measure on resize and once the orb's tweens have settled.
  const [at, setAt] = useState<{ x: number; y: number; card: number } | null>(null);
  useLayoutEffect(() => {
    const measure = () => {
      const o = around?.();
      // Card width: 250, or less so all four and their gaps fit across the screen.
      const card = Math.min(250, (window.innerWidth - 3 * GAP - 32) / 4);
      setAt(o && card >= 160 ? { ...o, card } : null);
    };
    measure();
    const t = window.setTimeout(measure, 1000);
    window.addEventListener("resize", measure);
    return () => { window.clearTimeout(t); window.removeEventListener("resize", measure); };
  }, [around]);
  const file = (id: string, name: string) => designFile(runId, id, name, ear ?? undefined);
  useEffect(() => {
    if (open === null) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  const o = open === null ? null : options[open];

  return (
    <>
      <div data-testid="aid-options" className={at ? s.around : s.row} style={at ? { left: at.x, top: at.y } : undefined}>
        <div className={s.grid} style={at ? { gridTemplateColumns: `repeat(4, ${at.card}px)`, gap: GAP } : undefined}>
          {options.map((x, i) => (
            <div key={x.id} data-testid="aid-option" className={s.card} role="button" tabIndex={0} aria-label={`Open option ${i + 1}`} title={plain(x.reason)}
              onClick={() => setOpen(i)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setOpen(i))}>
              <MetalFx variant="button" preset="silver" theme="dark" innerShadow ringCssPx={2} borderRadius={20}>
                <div className={s.face}>
                  <Preview runId={runId} ear={ear} src={file(x.id, "preview.png")} piece={file(x.id, "earpiece.glb")} alt={`Option ${i + 1}: in your ear and on its own`} />
                </div>
              </MetalFx>
              {x.recommended && <span data-testid="aid-recommended" className={s.badge}>Recommended</span>}
              <button type="button" className={s.select} aria-label={`Select option ${i + 1}`} onClick={(e) => { e.stopPropagation(); onPick(x.id); }}><Arrow /></button>
            </div>
          ))}
        </div>
      </div>
      {o && (
        <div className={s.backdrop} onClick={() => setOpen(null)}>
          <div data-testid="aid-expanded" className={s.panel} role="dialog" aria-label={`Option ${open! + 1}`} onClick={(e) => e.stopPropagation()}>
            {/* A CSS silver edge, NOT MetalFx: the metal ring measures once at mount, mid grow-animation, and drew a clipped, see-through frame. */}
            <div className={s.inner} style={{ background: `linear-gradient(#000, #000) padding-box, ${SILVER} border-box` }}>
                <div className={s.head}>
                  <span className={s.title}>Option {open! + 1}{o.recommended ? " · Recommended" : ""}</span>
                  <button type="button" className={s.close} aria-label="Close option" onClick={() => setOpen(null)}>
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
                  </button>
                </div>
                <div className={s.models}>
                  {/* "In your ear" is the patient's photo-coloured ear with the piece in it, NOT the pale ear baked into earpiece_in_ear.glb */}
                  {([[ear ? [`/api/patients/${runId}/files/${ear}/ear_skin.glb`, file(o.id, "earpiece.glb")] : file(o.id, "earpiece_in_ear.glb"), "In your ear"], [file(o.id, "earpiece.glb"), "On its own"]] as const).map(([url, tag]) => (
                    <div key={tag} data-testid="aid-model" className={s.model}>
                      <span className={s.tag}>{tag} · drag to turn</span>
                      <EarpieceView url={url} className={s.model} />
                    </div>
                  ))}
                </div>
                <div className={s.foot}>
                  <span className={s.reason}>{plain(o.reason)}</span>
                  <button type="button" className={`${s.select} ${s.labelled}`} aria-label={`Select option ${open! + 1}`} onClick={() => onPick(o.id)}>Select <Arrow /></button>
                </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
