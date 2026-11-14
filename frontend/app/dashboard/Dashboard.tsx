"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { MetalFx } from "@/components/metal";
import Dock from "@/components/Dock";
import Orb from "@/components/Orb";
import gsap from "gsap";
import { supabase } from "@/lib/supabase";
import { classifyPhoto, earReadyForSim, fitHead, KIND_LABEL, patientStatus, uploadEar, type PhotoKind } from "./intake";

/** auto: the label came from the photo (face found / nose direction), not from upload order. box: where the ear is. */
type Attachment = { id: string; blob: Blob; url: string; kind: PhotoKind; mirror: boolean; auto: boolean; box?: [number, number, number, number] };
type Msg = { id: string; text: string; link?: { href: string; label: string }; tone?: "error" };
let seq = 0;
const nid = () => `a${++seq}`;

// Same chrome ramp as the "Auris" title on the splash (app/page.tsx). Gradient ids are document-global, so each icon gets its OWN id — a shared one breaks when the first icon unmounts.
const svg = (id: string, d: string[]) => (
  <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke={`url(#metal-${id})`} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <defs>
      <linearGradient id={`metal-${id}`} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#ffffff" />
        <stop offset="0.3" stopColor="#c9ccd1" />
        <stop offset="0.52" stopColor="#7d8189" />
        <stop offset="0.75" stopColor="#e6e8eb" />
        <stop offset="1" stopColor="#9aa0a8" />
      </linearGradient>
    </defs>
    {d.map((p) => <path key={p} d={p} />)}
  </svg>
);

/** Black square with a silver metal ring. MetalFx strips the CHILD's background (transparent !important) and a root-background fill does not paint, so the black fill is a wrapper div under each MetalFx — the ring still draws on top. variant="circle" forces a round outline whatever borderRadius says, so the square needs "button". The child and MetalFx take the SAME radius — a mismatch draws the ring off the tile edge. The dock runs with tiles off, so this square IS the tile — MetalFx must wrap a child that fills the dock face or the ring collapses to the glyph. */
const RADIUS = 12;
// Same chrome ramp as the title and icon strokes, as a CSS border (MetalFx would bake its ring from the panel's size mid-animation).
const SILVER = "linear-gradient(135deg, #ffffff 0%, #c9ccd1 30%, #7d8189 52%, #e6e8eb 75%, #9aa0a8 100%)";
const metal = (glyph: React.ReactNode) => (
  <div style={{ width: "100%", height: "100%", background: "#000", borderRadius: RADIUS }}>
  <MetalFx variant="button" preset="silver" theme="dark" innerShadow ringCssPx={2} borderRadius={RADIUS} style={{ width: "100%", height: "100%" }}>
    <span style={{ display: "flex", alignItems: "center", justifyContent: "center", width: "100%", height: "100%", borderRadius: RADIUS, background: "#000", color: "#c9ccd1", fontSize: "0.62em" }}>
      {glyph}
    </span>
  </MetalFx>
  </div>
);

// One icon per panel in handoff.md: ear, audiogram, cochlea spiral, experiment grid, speaker.
const items = [
  { icon: metal(svg("ear", ["M6 8.5a6.5 6.5 0 1 1 13 0c0 6-6 6-6 10a3.5 3.5 0 1 1-7 0", "M15 8.5a2.5 2.5 0 0 0-5 0v1a2 2 0 1 1 0 4"])), label: "Ear and horn" },
  { icon: metal(svg("audiogram", ["M3 3v18h18", "M7 8l4 3 3-2 5 7"])), label: "Ear profile" },
  { icon: metal(svg("cochlea", ["M12 12a1 1 0 0 1 1-1 2 2 0 0 1 2 2 4 4 0 0 1-4 4 6 6 0 0 1-6-6 8 8 0 0 1 8-8 9 9 0 0 1 9 9"])), label: "Cochlea" },
  { icon: metal(svg("experiments", ["M4 4h6v6H4z", "M14 4h6v6h-6z", "M4 14h6v6H4z", "M14 14h6v6h-6z"])), label: "Experiments" },
  { icon: metal(svg("listen", ["M11 5 6 9H2v6h4l5 4z", "M15.5 8.5a5 5 0 0 1 0 7", "M18.5 5.5a9 9 0 0 1 0 13"])), label: "Listen" },
  { separator: true },
  { icon: metal(svg("user", ["M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M4 21a8 8 0 0 1 16 0"])), label: "Profile" },
];

/** Resolves once fonts are loaded and 3 frames in a row land under 25ms, or after 400ms regardless. The dashboard mounts a dozen WebGL rings and the orb at once; animating through that init drops frames and the icons judder. */
const settled = async () => {
  await document.fonts.ready;
  await new Promise<void>((done) => {
    const t0 = performance.now();
    let last = t0;
    let calm = 0;
    const tick = (now: number) => {
      calm = now - last < 25 ? calm + 1 : 0;
      last = now;
      if (calm >= 3 || now - t0 > 400) done();
      else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
};

const ORB_PX = 450;
/** The sphere fills ~80% of the Orb canvas; the rest is transparent padding. Layout math uses the visible size, or the separated pair sits too far apart. */
const ORB_FILL = 0.8;
const DOCK_BOTTOM = 100;
/** Gap between the sent-state chat card and the bottom edge. */
const BOTTOM = 64;

export default function Dashboard() {
  // MetalFx renders a placeholder on the server and a WebGL canvas on the client — mounting after hydration avoids the mismatch.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const dockWrap = useRef<HTMLDivElement>(null);
  const chat = useRef<HTMLDivElement>(null);
  const orb = useRef<HTMLDivElement>(null);
  const form = useRef<HTMLFormElement>(null);
  // Flips on the first send; the orb and card split apart from then on (see the layout effect below).
  const [sent, setSent] = useState(false);
  // Anchor point under the Profile icon, or null when the popover is closed.
  const [profileAt, setProfileAt] = useState<{ x: number; y: number } | null>(null);
  // Intro drops each icon in one at a time with a SINGLE overshoot (back.out, not bounce.out). Translate only, NEVER scale — MetalFx sizes its WebGL ring from getBoundingClientRect, so a scaled item bakes a wrong-size border. clearProps hands transform back to Dock's per-frame magnification — leftover inline transform would fight it.
  // Layout effect so the dock and chat are hidden BEFORE first paint; the animation then waits for the page to settle (see settled) — starting it while the WebGL rings and orb are still initializing is what made it lag and look jagged.
  useLayoutEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const ctx = gsap.context(() => gsap.set([".dock-item", chat.current], { opacity: 0 }), dockWrap);
    settled().then(() => {
      if (cancelled) return;
      ctx.add(() => {
        // fromTo, not from: the layout effect already set opacity 0, and from() would read that as the END value.
        const dock = gsap.fromTo(".dock-item", { y: -70, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6, ease: "back.out(2.4)", stagger: 0.18, clearProps: "transform,opacity", });
        // Chat fades in once the last icon lands. Opacity only — the wrapper's translate centers it, and clearProps there would drop that.
        gsap.fromTo(chat.current, { opacity: 0 }, { opacity: 1, duration: 0.8, ease: "power1.out", clearProps: "opacity", delay: dock.totalDuration() });
      });
    });
    return () => {
      cancelled = true;
      ctx.revert();
    };
  }, [ready]);
  // Dismiss on Escape or any click outside the popover and the Profile icon (the icon's own click toggles it).
  useEffect(() => {
    if (!profileAt) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setProfileAt(null);
    const onDown = (e: PointerEvent) => {
      const t = e.target as Element;
      if (!t.closest("[data-profile-pop]") && !t.closest('[aria-label="Profile"]')) setProfileAt(null);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [profileAt]);
  // Capture Ear: camOn mounts the feed panel; each still taken from it becomes a chat attachment.
  const [camOn, setCamOn] = useState(false);
  const [camErr, setCamErr] = useState<string | null>(null);
  // Chat attachments: camera stills and picked files, each labelled left ear / right ear / front face.
  const [photos, setPhotos] = useState<Attachment[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  // What the chat has set up for /sim so far: a patient id per ear and a head shape id.
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [intake, setIntake] = useState<{ left?: string; right?: string; head?: string; ready: Record<string, boolean> }>({ ready: {} });
  const say = (m: Omit<Msg, "id"> & { id?: string }) => setMsgs((ms) => {
    const id = m.id ?? nid();
    const i = ms.findIndex((x) => x.id === id);
    const next = { ...m, id } as Msg;
    return i < 0 ? [...ms, next] : ms.map((x, k) => (k === i ? next : x));
  });
  const polls = useRef<number[]>([]);
  const moving = useRef(false);   // navigating to /sim (once)
  useEffect(() => () => polls.current.forEach((t) => window.clearInterval(t)), []);
  // Software zoom (CSS scale on the feed, same crop baked into the snapshot) — most webcams expose no hardware zoom constraint. ponytail: use track.applyConstraints({zoom}) where supported if quality matters.
  const [zoom, setZoom] = useState(1);
  const camPanel = useRef<HTMLDivElement>(null);
  const camInner = useRef<HTMLDivElement>(null);
  const camVideo = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const stopStream = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  };
  // Stream tracks outlive the component — leaving them running keeps the camera light on after navigation.
  useEffect(() => stopStream, []);
  // The panel grows from the chat card's top edge: the wrapper's height clips while the content rises out from behind the card. Height animates on this plain-bordered wrapper, NEVER on a MetalFx — it sizes its ring from getBoundingClientRect once.
  useEffect(() => {
    if (!camOn) return;
    const v = camVideo.current;
    if (v && stream.current) {
      v.srcObject = stream.current;
      v.play().catch(() => {});
    }
    const ctx = gsap.context(() => {
      gsap.fromTo(camPanel.current, { height: 0, marginBottom: 0, borderWidth: 0 }, { height: "auto", marginBottom: 12, borderWidth: 2, duration: 0.6, ease: "power3.out" });
      gsap.fromTo(camInner.current, { yPercent: 100 }, { yPercent: 0, duration: 0.6, ease: "power3.out" });
    });
    return () => ctx.revert();
  }, [camOn]);
  // After the first send the card slides down to the bottom and the orb rises into the space above it. Card moves by marginTop on the wrapper (its translate does the centering); the orb tween subtracts that same shift. Camera mode returns both to center — the feed is sized for a centered stack. ponytail: measured on send/camera toggle only, not on window resize.
  useLayoutEffect(() => {
    const w = chat.current, o = orb.current, f = form.current;
    if (!w || !o || !f) return;
    let shift = 0, orbY = 0, s = 1;
    if (sent && !camOn) {
      // Card drops to BOTTOM px above the screen edge; the orb centers in the gap between the dock icons' bottom edge (DOCK_BOTTOM: dock top 12 + (panelHeight 100 - item 76) / 2 + 76) and the Capture Ear button's top (card top - 40 button - 12 margin), shrinking only when that gap is too short.
      const vh = window.innerHeight, h = f.offsetHeight, bar = 52, gap = 8;
      shift = vh - BOTTOM - h / 2 - vh / 2;
      const capTop = vh - BOTTOM - h - bar;
      s = Math.min(1, (capTop - DOCK_BOTTOM - 2 * gap) / (ORB_PX * ORB_FILL));
      orbY = (DOCK_BOTTOM + capTop) / 2 - (vh / 2 + shift);
    }
    const ctx = gsap.context(() => {
      gsap.to(w, { marginTop: shift, duration: 0.9, ease: "power3.inOut" });
      gsap.to(o, { y: orbY, scale: s, duration: 0.9, ease: "power3.inOut" });
    });
    return () => ctx.kill();
  }, [ready, sent, camOn]);
  if (!ready) return null;

  const openCam = async () => {
    setCamErr(null);
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ video: true });
    } catch {
      setCamErr("Camera unavailable");
      return;
    }
    setZoom(1);
    setCamOn(true);
  };
  /** Add photos as attachments, labelled from the photo itself: a face looking at the camera is the front
   * photo; an ear photo's side comes from which way the nose points. Only when no face is found at all
   * does the label fall back to whichever ear is still missing (marked so you check it). */
  const addPhotos = async (items: { blob: Blob; mirror: boolean }[]) => {
    for (const it of items) {
      const c = await classifyPhoto(it.blob).catch(() => ({ kind: "ear" as const, ear: null }));
      setPhotos((ps) => {
        const have = new Set([...ps.map((p) => p.kind), ...(intake.left ? ["left"] : []), ...(intake.right ? ["right"] : []), ...(intake.head ? ["face"] : [])]);
        const base = { id: nid(), blob: it.blob, url: URL.createObjectURL(it.blob), mirror: it.mirror };
        if (c.kind === "face") return [...ps, { ...base, kind: "face", auto: true }];
        if (c.ear) return [...ps, { ...base, kind: c.ear.side, auto: true, box: c.ear.box }];
        const k: PhotoKind = !have.has("right") ? "right" : !have.has("left") ? "left" : "right";
        return [...ps, { ...base, kind: k, auto: false }];
      });
    }
  };
  const removePhoto = (id: string) => setPhotos((ps) => {
    const p = ps.find((x) => x.id === id);
    if (p) URL.revokeObjectURL(p.url);
    return ps.filter((x) => x.id !== id);
  });
  const setKind = (id: string, kind: PhotoKind) => setPhotos((ps) => ps.map((p) => (p.id === id ? { ...p, kind, auto: false } : p)));

  /** Send: each ear starts the ear pipeline, the front face becomes a head shape; once both ears and the
   * head are ready the chat links to /sim with all three. */
  const submitPhotos = async (batch: Attachment[]) => {
    const next = { ...intake, ready: { ...intake.ready } };
    const tryLink = (s: typeof next) => {
      if (s.left && s.right && s.head && s.ready[s.left] && s.ready[s.right] && !moving.current) {
        const href = `/sim?left=${s.left}&right=${s.right}&head=${s.head}`;
        moving.current = true;
        say({ id: "link", text: "Both ears and the head are ready. Opening the scene simulation…", link: { href, label: "Open it now" } });
        window.setTimeout(() => window.location.assign(href), 1500);   // a beat to read the message
      }
    };
    for (const p of batch) {
      if (p.kind === "face") {
        const id = nid();
        say({ id, text: "Front face: finding landmarks and fitting the head shape…" });
        try {
          const fit = await fitHead(p.blob);
          next.head = fit.id;
          say({ id, text: `Front face: head ${fit.meta.breadth_mm.toFixed(0)} mm wide, chin to crown ${(fit.meta.crown_mm - fit.meta.chin_mm).toFixed(0)} mm.${fit.warnings.length ? " " + fit.warnings.join(" ") : ""}` });
        } catch (e) {
          say({ id, text: `Front face: ${(e as Error).message}`, tone: "error" });
        }
      } else {
        const side = p.kind;
        const id = nid();
        say({ id, text: `${KIND_LABEL[side]}: uploading…` });
        try {
          const pid = await uploadEar(p.blob, side, p.box);
          next[side] = pid;
          say({ id, text: `${KIND_LABEL[side]}: reconstructing the ear (patient ${pid}, about 15 seconds)…` });
          const t = window.setInterval(async () => {
            try {
              const j = await patientStatus(pid);
              const sc = j.results?.side_check;
              const doubt = sc && !sc.agrees ? ` Note: the ear's shape fits a ${sc.side} ear better; if this photo is mirrored, re-send it labelled ${KIND_LABEL[sc.side as PhotoKind] ?? sc.side}.` : "";
              if (earReadyForSim(j)) {
                window.clearInterval(t);
                say({ id, text: `${KIND_LABEL[side]}: ear reconstructed and fitted (patient ${pid}).${doubt}` });
                setIntake((s) => { const u = { ...s, ready: { ...s.ready, [pid]: true } }; tryLink(u); return u; });
              } else if (j.status === "error") {
                window.clearInterval(t);
                say({ id, text: `${KIND_LABEL[side]}: ${j.error ?? "the ear pipeline failed"}. Retake with the ear filling most of the frame.`, tone: "error" });
              } else {
                say({ id, text: `${KIND_LABEL[side]}: ${j.status === "queued" ? "waiting for the other ear" : `step ${j.step ?? "…"}`} (patient ${pid})…` });
              }
            } catch { /* transient: keep polling */ }
          }, 3000);
          polls.current.push(t);
        } catch (e) {
          say({ id, text: `${KIND_LABEL[side]}: ${(e as Error).message}`, tone: "error" });
        }
      }
    }
    setIntake((s) => {
      const u = { ...s, left: next.left ?? s.left, right: next.right ?? s.right, head: next.head ?? s.head, ready: { ...next.ready, ...s.ready } };
      const missing = [!u.left && "left ear", !u.right && "right ear", !u.head && "front face"].filter(Boolean);
      if (missing.length) say({ id: "todo", text: `Still needed for the simulation: ${missing.join(", ")} photo${missing.length > 1 ? "s" : ""}.` });
      else setMsgs((ms) => ms.filter((m) => m.id !== "todo"));
      tryLink(u);
      return u;
    });
  };
  const closeCam = () => {
    gsap.to(camPanel.current, { height: 0, marginBottom: 0, borderWidth: 0, duration: 0.45, ease: "power2.in", onComplete: () => { stopStream(); setCamOn(false); } });
    gsap.to(camInner.current, { yPercent: 100, duration: 0.45, ease: "power2.in" });
  };
  const snap = () => {
    const v = camVideo.current;
    if (!v || !v.videoWidth) return;
    // WYSIWYG: the feed is object-fit cover inside the panel, then scaled by zoom about the center — crop the same region from the full-resolution frame.
    const pa = v.clientWidth / v.clientHeight;
    const cw = v.videoWidth / v.videoHeight > pa ? v.videoHeight * pa : v.videoWidth;
    const sw = cw / zoom;
    const sh = sw / pa;
    const c = document.createElement("canvas");
    c.width = Math.round(sw);
    c.height = Math.round(sh);
    c.getContext("2d")?.drawImage(v, (v.videoWidth - sw) / 2, (v.videoHeight - sh) / 2, sw, sh, 0, 0, c.width, c.height);
    c.toBlob((blob) => {
      if (!blob) return;
      stopStream();
      addPhotos([{ blob, mirror: true }]);
      // The still becomes a chat attachment (chip in the composer), so the panel retracts instead of lingering over it.
      closeCam();
    }, "image/jpeg", 0.92);
  };

  // The Dock calls item.onClick with no arguments, so find the icon in the DOM to anchor the popover under it.
  const toggleProfile = () => {
    const el = dockWrap.current?.querySelector('[aria-label="Profile"]');
    if (!el) return;
    const r = el.getBoundingClientRect();
    setProfileAt((cur) => (cur ? null : { x: r.left + r.width / 2, y: r.bottom + 10 }));
  };
  const dockItems = items.map((it) => (it.label === "Profile" ? { ...it, onClick: toggleProfile } : it));

  const iconBtn = { display: "flex", alignItems: "center", justifyContent: "center", width: 34, height: 34, borderRadius: 999, cursor: "pointer", font: "inherit" } as const;
  const zoomBtn = { ...iconBtn, width: 38, height: 38, border: 0, background: "rgba(0,0,0,0.55)", color: "#e6e8eb" } as const;
  const icon = { width: 18, height: 18, fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" } as const;

  return (
    <>
    {/* Send uploads attached photos (left ear, right ear, front face) and links to /sim once ready; text alone has no backend yet. Width 600 approximates the dock's resting width — retune if the dock changes. */}
    <div ref={chat} style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)", width: 600, maxWidth: "calc(100vw - 32px)", zIndex: 10 }}>
    {/* Orb draws at full resolution (components/Orb.tsx), so size is plain pixels. zIndex -1 sits behind the card and bar inside this wrapper's stacking context. The inner div carries the post-send y/scale tween, so GSAP NEVER rewrites the centering translate on the outer one. */}
    <div aria-hidden style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", zIndex: -1, pointerEvents: "none" }}>
      <div ref={orb} data-testid="orb"><Orb px={ORB_PX} /></div>
    </div>
    {/* Bar floats above the card (bottom: 100%) so the card stays centered, and hugs its content. While the camera is ON the bar joins the flow instead, so the wrapper (centered by its translate) re-centers feed + card together and the card is pushed down. Inert until capture is wired. Grey matches the textarea placeholder. */}
    <div style={camOn ? { display: "flex", justifyContent: "center" } : { position: "absolute", bottom: "100%", left: 0, right: 0, marginBottom: 12, display: "flex", justifyContent: "center" }}>
      {!camOn && <div style={{ background: "#000", borderRadius: 20 }}>
      <MetalFx variant="button" preset="silver" theme="dark" innerShadow ringCssPx={2} borderRadius={20}>
        <button type="button" onClick={openCam} style={{ display: "flex", alignItems: "center", gap: 8, height: 40, padding: "0 24px", border: 0, borderRadius: 20, background: "#000", color: camErr ? "#f87171" : "#757575", cursor: "pointer", font: "inherit", fontSize: 16 }}>
          <svg viewBox="0 0 24 24" width="1.1em" height="1.1em" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><path d="M12 10a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z" /></svg>
          {camErr ?? "Capture Ear"}
        </button>
      </MetalFx>
      </div>}
      {/* Camera panel REPLACES the Capture Ear button above the card. It is in flow, so growing its height shoves the card down while the centered wrapper keeps the pair centered. The 12px gap is animated on the panel (not the bar) so the swap back to the floating button does not jump the card; border is a box-shadow for the same reason. Height cap keeps the pair clear of the 140px dock; see the camOn effect. */}
      {camOn && (
        <div ref={camPanel} style={{ width: "100%", overflow: "hidden", borderRadius: 24, border: "2px solid transparent", background: `linear-gradient(#000, #000) padding-box, ${SILVER} border-box` }}>
          <div ref={camInner} style={{ position: "relative", height: "max(180px, min(340px, calc(100vh - 420px)))" }}>
            <video ref={camVideo} muted playsInline style={{ width: "100%", height: "100%", objectFit: "cover", display: "block", transform: `scaleX(-1) scale(${zoom})` }} />
            <button type="button" aria-label="Close camera" onClick={closeCam} style={{ position: "absolute", top: 12, right: 12, width: 32, height: 32, borderRadius: 999, border: 0, background: "rgba(0,0,0,0.55)", color: "#e6e8eb", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg viewBox="0 0 24 24" {...icon}><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
            {(
              <div style={{ position: "absolute", bottom: 16, left: 0, right: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                <span style={{ padding: "3px 10px", borderRadius: 999, background: "rgba(0,0,0,0.55)", color: "#e6e8eb", fontSize: 13, fontVariantNumeric: "tabular-nums" }}>{zoom.toFixed(1)}×</span>
                <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
                  <button type="button" aria-label="Zoom out" disabled={zoom <= 1} onClick={() => setZoom((z) => Math.max(1, z - 0.5))} style={{ ...zoomBtn, opacity: zoom <= 1 ? 0.4 : 1 }}>
                    <svg viewBox="0 0 24 24" {...icon}><path d="M5 12h14" /></svg>
                  </button>
                  <button type="button" aria-label="Take picture" onClick={snap} style={{ width: 52, height: 52, padding: 0, borderRadius: 999, border: "3px solid #fff", background: "rgba(255,255,255,0.85)", boxShadow: "0 0 0 3px rgba(0,0,0,0.35) inset", cursor: "pointer" }} />
                  <button type="button" aria-label="Zoom in" disabled={zoom >= 4} onClick={() => setZoom((z) => Math.min(4, z + 0.5))} style={{ ...zoomBtn, opacity: zoom >= 4 ? 0.4 : 1 }}>
                    <svg viewBox="0 0 24 24" {...icon}><path d="M12 5v14M5 12h14" /></svg>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
    <div style={{ background: "#000", borderRadius: 24 }}>
    <MetalFx variant="button" preset="silver" theme="dark" innerShadow ringCssPx={2} borderRadius={24} style={{ width: "100%" }}>
    <form
      ref={form}
      onSubmit={(e) => {
        e.preventDefault();
        const ta = e.currentTarget.elements.namedItem("msg") as HTMLTextAreaElement;
        if (ta.value.trim() || photos.length) {
          ta.value = "";
          setSent(true);
        }
        const batch = photos;
        setPhotos([]);
        if (batch.length) submitPhotos(batch).finally(() => batch.forEach((p) => URL.revokeObjectURL(p.url)));
      }}
      style={{ boxSizing: "border-box", width: "100%", padding: 14, borderRadius: 24, background: "#000" }}
    >
      {msgs.length > 0 && (
        <div data-testid="chat-log" style={{ maxHeight: 180, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6, margin: "0 6px 10px", fontSize: 14, lineHeight: 1.4 }}>
          {msgs.map((m) => (
            <div key={m.id} style={{ color: m.tone === "error" ? "#f87171" : "#c9ccd1" }}>
              {m.text}
              {m.link && <> <a href={m.link.href} style={{ color: "#60a5fa" }}>{m.link.label} →</a></>}
            </div>
          ))}
        </div>
      )}
      {photos.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, margin: "0 6px 8px" }}>
          {photos.map((p) => (
            <div key={p.id} data-testid="attachment" style={{ display: "flex", flexDirection: "column", gap: 4, width: 76 }}>
              <div style={{ position: "relative", width: 76, height: 76 }}>
                <img src={p.url} alt={`${KIND_LABEL[p.kind]} attachment`} style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 12, transform: p.mirror ? "scaleX(-1)" : undefined }} />
                <button type="button" aria-label="Remove attachment" onClick={() => removePhoto(p.id)} style={{ position: "absolute", top: -6, right: -6, width: 20, height: 20, padding: 0, borderRadius: 999, border: 0, background: "#3b3d42", color: "#e6e8eb", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
                </button>
              </div>
              <select aria-label="What this photo shows" value={p.kind} onChange={(e) => setKind(p.id, e.target.value as PhotoKind)}
                title={p.auto ? "Detected from the photo; change it if wrong" : "Could not tell from the photo: check this"}
                style={{ width: "100%", background: "#16171a", color: p.auto ? "#c9ccd1" : "#fbbf24", border: `1px solid ${p.auto ? "rgba(255,255,255,0.18)" : "#fbbf24"}`, borderRadius: 6, fontSize: 11, padding: "2px 2px" }}>
                {(Object.keys(KIND_LABEL) as PhotoKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
              </select>
            </div>
          ))}
        </div>
      )}
      <textarea
        name="msg"
        rows={2}
        placeholder="How can I help you today? Add photos of each ear and your face with +"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
        }}
        style={{ display: "block", width: "100%", boxSizing: "border-box", resize: "none", border: 0, outline: 0, background: "transparent", color: "#e6e8eb", font: "inherit", fontSize: 16, padding: "4px 6px" }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
        <button type="button" aria-label="Add photos" title="Add photos: left ear, right ear, front face" onClick={() => fileInput.current?.click()} style={{ ...iconBtn, border: "1px solid rgba(255,255,255,0.18)", background: "transparent", color: "#c9ccd1" }}>
          <svg viewBox="0 0 24 24" {...icon}><path d="M12 5v14M5 12h14" /></svg>
        </button>
        <input ref={fileInput} type="file" accept="image/*" multiple hidden onChange={(e) => {
          const fs = Array.from(e.target.files ?? []);
          e.target.value = "";
          addPhotos(fs.map((blob) => ({ blob, mirror: false })));
        }} />
        <button type="submit" aria-label="Send" style={{ ...iconBtn, border: 0, background: "#3b82f6", color: "#fff" }}>
          <svg viewBox="0 0 24 24" {...icon}><path d="M12 19V5M5 12l7-7 7 7" /></svg>
        </button>
      </div>
    </form>
    </MetalFx>
    </div>
    </div>
    {/* The dock positions itself against its nearest positioned parent, so this fixed strip is the "top of the screen". It is click-through; the dock opts back in. */}
    <div ref={dockWrap} style={{ position: "fixed", top: 0, left: 0, right: 0, height: 140, zIndex: 20, pointerEvents: "none" }}>
      <Dock
        items={dockItems}
        position="top"
        tiles={false}
        showIndicators={false}
        roundness={0}
        baseItemSize={76}
        magnification={108}
        panelHeight={100}
        gap={16}
        style={{
          pointerEvents: "auto",
          // Tray is see-through: only the metal squares draw. Both backdrop-filter spellings or Safari keeps the blur.
          "--dock-panel": "transparent",
          "--dock-panel-edge": "transparent",
          "--dock-panel-highlight": "transparent",
          "--dock-panel-shadow": "0 0 0 0 transparent",
          backdropFilter: "none",
          WebkitBackdropFilter: "none",
        }}
      />
      {profileAt && (
        <div
          data-profile-pop=""
          style={{ position: "fixed", left: profileAt.x, top: profileAt.y, transform: "translateX(-50%)", pointerEvents: "auto", zIndex: 30 }}
        >
          <button
            type="button"
            onClick={async () => {
              await supabase?.auth.signOut();
              window.location.assign("/");
            }}
            style={{
              padding: "8px 18px",
              border: "1px solid rgba(255,255,255,0.18)",
              borderRadius: 999,
              background: "rgba(10,10,12,0.85)",
              color: "#e6e8eb",
              font: "inherit",
              fontSize: 14,
              letterSpacing: "0.04em",
              cursor: "pointer",
              boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
            }}
          >
            sign out
          </button>
        </div>
      )}
    </div>
    </>
  );
}
