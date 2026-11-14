"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import MeshView from "@/app/demo/MeshView";
import { SILVER } from "@/components/metal";
import { API } from "@/lib/run";

/**
 * The ear stage's three outputs, in reveal order: the crop with the fitted mesh points drawn on it, the depth AudioEar predicts from the photo, the reconstructed mesh. File names are the backend's FILES keys (backend/app/main.py).
 * Each view lists its files in preference order; the first one the backend wrote is shown. The fallbacks keep older backends (no depth.png, no ear_skin.glb) working.
 */
export type View = { file: string; label: string };
const VIEWS: View[][] = [
  [{ file: "overlay.jpg", label: "Key points" }],
  [{ file: "depth.png", label: "Depth map" }, { file: "mask.png", label: "Mask" }],
  [{ file: "ear_skin.glb", label: "3D model" }, { file: "ear.glb", label: "3D model" }],
];
const GAP = 12;
/** Pause between one view appearing and the next. */
const STEP_MS = 3000;
/** Dock icons end ~100px from the top; an opened view stops short of them. */
const DOCK_CLEAR = 116;

/**
 * Reveals the views one at a time, each straight into its OWN slot in the row (a stacked, tilted pile that fanned out read as jagged overlap). Each view waits for ITS file to exist (`files`) AND for STEP_MS after the previous one.
 * The row never closes itself: the caller sets `collapse` once EVERY row has formed and sat idle (rows share that state — see the dashboard), and hears back through `onRow` (all views shown) and `onOpen` (a view expanded or closed).
 * GSAP owns every card's transform — NEVER put transform in a card's style prop, or a re-render snaps it back. `anchor` returns the orb's rect: the stack centers on it at the first reveal.
 */
/** `y` is the row's center on screen and `size` its card size, for a caller stacking several rows (the dashboard's one row per ear); without them the row centers on the orb at the chat box's width. `label` names the row above its cards. `views` replaces the ear's three views (the head row has two); the row is as wide as its view count. */
export default function EarViews({ files, anchor, onGone, onRow, onOpen, collapse, y, size, label, testid = "ear-views", views = VIEWS }: { files?: Record<string, string>; anchor: () => DOMRect | null; onGone?: () => void; onRow?: () => void; onOpen?: (open: boolean) => void; collapse?: boolean; y?: number; size?: number; label?: string; testid?: string; views?: View[][] }) {
  const n = views.length;
  const pick = (i: number, f?: Record<string, string>) => views[i].find((v) => f?.[v.file]);
  const [shown, setShown] = useState(0);
  const [top, setTop] = useState<number | null>(null);
  const lastAt = useRef(0);
  const cards = useRef<(HTMLDivElement | null)[]>([]);
  // row: the fan-out finished, so cards are clickable. open: the view expanded into the modal, and its square on screen. gone: shrunk into the orb, render nothing.
  const [row, setRow] = useState(false);
  const [open, setOpen] = useState<{ i: number; left: number; top: number; size: number } | null>(null);
  const [gone, setGone] = useState(false);
  const collapsing = useRef(false);
  const modal = useRef<HTMLDivElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  // Dragging the 3D model ends in a click too — only a press that barely moved opens the view.
  const down = useRef({ x: 0, y: 0 });
  // Chat box is 600 wide (maxWidth viewport - 32); the row spans exactly that. ponytail: measured once, not on window resize.
  const [W] = useState(() => (size ? n * size + (n - 1) * GAP : Math.min(600, window.innerWidth - 32)));
  const S = (W - (n - 1) * GAP) / n;
  const left = (i: number) => i * (S + GAP);

  const ready = shown < n && !!pick(shown, files);
  useEffect(() => {
    if (!ready) return;
    const t = setTimeout(() => {
      lastAt.current = Date.now();
      if (shown === 0) {
        const r = anchor();
        setTop(y ?? (r ? r.top + r.height / 2 : window.innerHeight / 2));
      }
      setShown(shown + 1);
    }, shown === 0 ? 0 : Math.max(0, lastAt.current + STEP_MS - Date.now()));
    return () => clearTimeout(t);
  }, [ready, shown]); // eslint-disable-line react-hooks/exhaustive-deps

  useLayoutEffect(() => {
    if (!shown) return;
    gsap.fromTo(cards.current[shown - 1], { y: 24, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6, ease: "power3.out" });
  }, [shown]); // eslint-disable-line react-hooks/exhaustive-deps

  // The last view has landed: the row is formed and clickable.
  useEffect(() => {
    if (shown < n) return;
    const t = setTimeout(() => setRow(true), 600);
    return () => clearTimeout(t);
  }, [shown]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (row) onRow?.(); }, [row]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { onOpen?.(!!open); }, [!!open]); // eslint-disable-line react-hooks/exhaustive-deps

  // Collapse (the caller's call): shrink every card to the orb's CURRENT center (it moves up after a send, so re-read it rather than reuse `top`), then unmount.
  useEffect(() => {
    if (!collapse || open || gone || collapsing.current) return;
    collapsing.current = true;
    if (!shown) { setGone(true); onGone?.(); return; }   // a row whose files never came (e.g. no head) leaves with the rest
    const r = anchor(), dy = r && top !== null ? r.top + r.height / 2 - top : 0;
    gsap.to(cards.current.slice(0, shown), { x: (i: number) => W / 2 - S / 2 - left(i), y: dy, scale: 0, opacity: 0, duration: 0.7, ease: "power3.in", stagger: 0.06, onComplete: () => { setGone(true); onGone?.(); } });
  }, [collapse, open, gone]); // eslint-disable-line react-hooks/exhaustive-deps

  // FLIP: the modal is laid out at its final square, then starts transformed onto the clicked card's rect, so it grows up out of the row. transformOrigin 0 0 keeps the x/y math a plain offset.
  const flipFrom = (i: number, o: NonNullable<typeof open>) => {
    const c = cards.current[i]!.getBoundingClientRect();
    return { x: c.left - o.left, y: c.top - o.top, scale: c.width / o.size };
  };
  useLayoutEffect(() => {
    if (!open) return;
    gsap.set(cards.current[open.i], { opacity: 0 });
    gsap.fromTo(modal.current, { ...flipFrom(open.i, open), transformOrigin: "0 0" }, { x: 0, y: 0, scale: 1, duration: 0.55, ease: "power3.inOut" });
    gsap.fromTo(backdrop.current, { opacity: 0 }, { opacity: 1, duration: 0.4 });
  }, [open?.i]); // eslint-disable-line react-hooks/exhaustive-deps

  const openView = (i: number, e: React.MouseEvent) => {
    if (!row || open || collapsing.current || Math.hypot(e.clientX - down.current.x, e.clientY - down.current.y) > 5) return;
    const c = cards.current[i]!.getBoundingClientRect();
    // Grows UP from the row (bottom edge on the card's bottom) until it meets the dock; on a short screen whatever is left over extends downward instead of shrinking the view.
    const size = Math.min(W, window.innerHeight - DOCK_CLEAR - 24);
    setOpen({ i, left: (window.innerWidth - size) / 2, top: Math.max(DOCK_CLEAR, c.bottom - size), size });
  };
  const closeView = () => {
    if (!open) return;
    gsap.to(backdrop.current, { opacity: 0, duration: 0.35 });
    gsap.to(modal.current, { ...flipFrom(open.i, open), duration: 0.45, ease: "power3.inOut", onComplete: () => { gsap.set(cards.current[open.i], { opacity: 1 }); setOpen(null); } });
  };
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeView();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  // `caption`: ONLY the expanded view names itself — the small cards stay clean.
  const body = (i: number, h: number, fit: "cover" | "contain", caption = false) => {
    const v = pick(i, files) ?? views[i][0], url = `${API}${files?.[v.file]}`;
    return (
      <>
        {v.file.endsWith(".glb") ? (
          <MeshView url={url} height={h - 4} label={v.label} skin={v.file === "ear_skin.glb"} />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={v.label} style={{ display: "block", width: "100%", height: "100%", objectFit: fit }} />
        )}
        {/* Grey is the orb's "Processing…" (#757575). No pill behind it: the shadow keeps it legible over the bright photo without a box. pointerEvents none so it never blocks dragging the 3D model. */}
        {caption && <span style={{ position: "absolute", left: 0, right: 0, bottom: 10, textAlign: "center", color: "#757575", fontSize: 16, textShadow: "0 1px 6px rgba(0,0,0,0.9), 0 0 2px rgba(0,0,0,0.9)", pointerEvents: "none" }}>{v.label}</span>}
      </>
    );
  };
  const frame = { boxSizing: "border-box", overflow: "hidden", borderRadius: 16, border: "2px solid transparent", background: `linear-gradient(#000, #000) padding-box, ${SILVER} border-box` } as const;

  if (top === null || gone) return null;
  return (
    <>
    <div data-testid={testid} style={{ position: "fixed", left: "50%", top, width: W, height: S, transform: "translate(-50%, -50%)", zIndex: 15, pointerEvents: "none" }}>
      {label && <span style={{ position: "absolute", left: 0, bottom: "100%", marginBottom: 4, color: "#757575", fontSize: 14 }}>{label}</span>}
      {views.slice(0, shown).map((_, i) => (
        <div
          key={i}
          ref={(el) => { cards.current[i] = el; }}
          data-testid={`ear-view-${i}`}
          onPointerDown={(e) => { down.current = { x: e.clientX, y: e.clientY }; }}
          onClick={(e) => openView(i, e)}
          style={{ ...frame, position: "absolute", left: left(i), top: 0, width: S, height: S, zIndex: i, pointerEvents: "auto", cursor: row ? "pointer" : undefined }}
        >
          {body(i, S, "cover")}
        </div>
      ))}
    </div>
    {/* Outside the row container: its transform would make these fixed boxes position against IT instead of the viewport. Below the dock (20), above the row (15). */}
    {open && (
      <>
        <div ref={backdrop} onClick={closeView} style={{ position: "fixed", inset: 0, zIndex: 16, background: "rgba(0,0,0,0.6)" }} />
        <div ref={modal} data-testid="ear-view-modal" style={{ ...frame, position: "fixed", left: open.left, top: open.top, width: open.size, height: open.size, zIndex: 17, borderRadius: 20 }}>
          {body(open.i, open.size, "contain", true)}
          <button type="button" aria-label="Close view" onClick={closeView} style={{ position: "absolute", top: 12, right: 12, width: 32, height: 32, borderRadius: 999, border: 0, background: "rgba(0,0,0,0.55)", color: "#e6e8eb", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
      </>
    )}
    </>
  );
}
