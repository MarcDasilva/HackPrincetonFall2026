"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { MetalFx, SILVER } from "@/components/metal";
import Dock from "@/components/Dock";
import Orb from "@/components/Orb";
import HearingTest from "@/components/HearingTest";
import { hearingPdf } from "@/lib/hearingPdf";
import { fakeHearing } from "@/lib/fakeHearing";
import type { Result } from "@/lib/audiometry";
import { pollRun, runNote, startRun, type Run } from "@/lib/run";
import { talkToLead } from "@/lib/lead";
import EarViews from "@/components/EarViews";
import gsap from "gsap";
import { CustomEase } from "gsap/CustomEase";

gsap.registerPlugin(CustomEase);
// Easy Ease's soft start (0.33, 0) with a long coast out (0.2, 1): the orb winds DOWN like a spun ball instead of braking symmetrically.
const SPIN_EASE = CustomEase.create("orbSpin", "0.33,0,0.2,1");
// Peak speed of SPIN_EASE is 2.6× its average vs 2× for power1.inOut — the spin runs 1.3× the rise so its top speed matches the old one; shorter and it reads as FASTER.
const SPIN_STRETCH = 1.3;
import { supabase } from "@/lib/supabase";

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
/** Height kept free under the sphere for the loading sub text, so "Processing…" NEVER lands on the Capture pills. */
const ORB_SUB = 48;
/** idle: behind the card. active: rising to, or resting at, the top. loading: at the top while a run is queued or running — the ONLY state that shows the "Processing…" sub text. */
type OrbState = "idle" | "active" | "loading";
/** Gap between the sent-state chat card and the bottom edge. */
const BOTTOM = 64;

export default function Dashboard() {
  // MetalFx renders a placeholder on the server and a WebGL canvas on the client — mounting after hydration avoids the mismatch.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const dockWrap = useRef<HTMLDivElement>(null);
  const chat = useRef<HTMLDivElement>(null);
  const orb = useRef<HTMLDivElement>(null);
  const spin = useRef({ a: 0 });
  // True once the rise tween completes; loading waits for it so the sub text rises in under a settled orb.
  const [arrived, setArrived] = useState(false);
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
  // Capture Ear: camOn mounts the feed panel; photo is the still taken from it (null while live). ponytail: the photo only lives in state until the backend upload (POST /api/patients) is wired.
  const [camOn, setCamOn] = useState(false);
  const [camErr, setCamErr] = useState<string | null>(null);
  // box and side are set only by the practice shortcut, which knows its photo; every other photo leaves them out and the backend detects the ear.
  const [photo, setPhoto] = useState<{ blob: Blob; url: string; box?: [number, number, number, number]; side?: "left" | "right"; mirror?: boolean } | null>(null);
  // mirror is true ONLY for camera captures: the live feed is shown selfie-style, so its still is too. Uploaded and dropped files show as they are.
  // Software zoom (CSS scale on the feed, same crop baked into the snapshot) — most webcams expose no hardware zoom constraint. ponytail: use track.applyConstraints({zoom}) where supported if quality matters.
  const [zoom, setZoom] = useState(1);
  // Capture Hearing: hearOn mounts the hearing-test panel in the SAME slot and refs as the camera (only one panel is ever open). hearing is the attached report — the generated PDF or an uploaded file.
  const [hearOn, setHearOn] = useState(false);
  const [hearing, setHearing] = useState<{ blob: Blob; url: string; name: string; result?: Result } | null>(null);
  // The pipeline run the up arrow starts. starting covers the POST; run then tracks the backend job (and its files, which EarViews reveals) until done or error.
  const [starting, setStarting] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  // The lead agent takes over once the ear cards vanish (EarViews onGone). From then on the composer talks to it, and its latest reply replaces "Processing…" under the orb. null = not started.
  const [lead, setLead] = useState<{ line: string; waiting: boolean } | null>(null);
  const upload = useRef<HTMLInputElement>(null);
  // Composer "+" and drag-drop share one router (addFiles below); dragging lights the card while a file hovers over it.
  const pick = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  // A file dropped OUTSIDE the card would otherwise make the browser navigate to it and throw away the page.
  useEffect(() => {
    const stop = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => {
      window.removeEventListener("dragover", stop);
      window.removeEventListener("drop", stop);
    };
  }, []);
  const panelOn = camOn || hearOn;
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
    if (!camOn && !hearOn) return;
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
  }, [camOn, hearOn]);
  // Dev shortcut, two keys (handler assigned each render below; the listener lives in a hook above the early return): turning Caps Lock ON attaches the practice ear and fake hearing test, then Enter sends them like any submit. Only the ON transition counts — macOS fires keydown for ON and keyup for OFF, other platforms keydown for both, so getModifierState keeps turning it OFF from re-attaching. Enter is swallowed ONLY when focus is on the page itself, so the textarea and buttons keep their own Enter. Dev builds only.
  const keyFn = useRef<(e: KeyboardEvent) => void>(() => {});
  const held = useRef(new Set<string>());
  useEffect(() => {
    if (process.env.NODE_ENV === "production") return;
    // Held keys, for chords: "1 + 2" needs to know 1 is still down when 2 arrives. A key released while the window is blurred never sends keyup, so blur clears the set or a stuck "1" would fire the chord on the next "2".
    const onKey = (e: KeyboardEvent) => {
      held.current.add(e.key);
      keyFn.current(e);
    };
    const onUp = (e: KeyboardEvent) => held.current.delete(e.key);
    const clear = () => held.current.clear();
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onUp);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onUp);
      window.removeEventListener("blur", clear);
    };
  }, []);
  // Poll the backend job. Deps are id+status only — new files and steps arrive through setRun without restarting the timer.
  useEffect(() => {
    if (!run || run.status === "done" || run.status === "error") return;
    const t = setInterval(() => pollRun(run).then(setRun, () => {}), 1500);
    return () => clearInterval(t);
  }, [run?.id, run?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  // After the first send the card slides down to the bottom and the orb rises into the space above it. Card moves by marginTop on the wrapper (its translate does the centering); the orb tween subtracts that same shift. An open panel (camera or hearing) returns both to center — the panel is sized for a centered stack. ponytail: measured on send/camera toggle only, not on window resize.
  useLayoutEffect(() => {
    const w = chat.current, o = orb.current, f = form.current;
    if (!w || !o || !f) return;
    let shift = 0, orbY = 0, s = 1;
    if (sent && !panelOn) {
      // Card drops to BOTTOM px above the screen edge; the orb centers in the gap between the dock icons' bottom edge (DOCK_BOTTOM: dock top 12 + (panelHeight 100 - item 76) / 2 + 76) and the Capture Ear button's top (card top - 40 button - 12 margin), shrinking only when that gap is too short.
      const vh = window.innerHeight, h = f.offsetHeight, bar = 52, gap = 8;
      shift = vh - BOTTOM - h / 2 - vh / 2;
      const capTop = vh - BOTTOM - h - bar - ORB_SUB;
      s = Math.min(1, (capTop - DOCK_BOTTOM - 2 * gap) / (ORB_PX * ORB_FILL));
      orbY = (DOCK_BOTTOM + capTop) / 2 - (vh / 2 + shift);
    }
    setArrived(false);
    const ctx = gsap.context(() => {
      const dur = 0.9;
      // ONE ease for card and orb: the orb lives inside the card's wrapper, so its screen path is marginTop + y — a different ease on either makes the orb rise, dip, then rise again. power1.inOut is GSAP's closest match to After Effects' Easy Ease.
      const ease = "power1.inOut";
      gsap.to(w, { marginTop: shift, duration: dur, ease });
      gsap.to(o, { y: orbY, scale: s, "--orb-s": s, duration: dur, ease, onComplete: () => setArrived(sent && !panelOn) });
      // Active (orb out from behind the card) turns the sphere a half turn about its vertical axis, still coasting briefly after the rise lands. It does NOT share the card/orb ease: spin is a yaw drawn in the canvas, not a position, so its curve cannot cause the dip.
      gsap.to(spin.current, { a: sent && !panelOn ? Math.PI : 0, duration: dur * SPIN_STRETCH, ease: SPIN_EASE });
    });
    return () => ctx.kill();
  }, [ready, sent, panelOn]);
  if (!ready) return null;

  const openCam = async () => {
    setCamErr(null);
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ video: true });
    } catch {
      setCamErr("Camera unavailable");
      return;
    }
    if (photo) URL.revokeObjectURL(photo.url);
    setPhoto(null);
    setZoom(1);
    setCamOn(true);
  };
  const clearPhoto = () => {
    if (photo) URL.revokeObjectURL(photo.url);
    setPhoto(null);
  };
  const closePanel = () => {
    gsap.to(camPanel.current, { height: 0, marginBottom: 0, borderWidth: 0, duration: 0.45, ease: "power2.in", onComplete: () => { stopStream(); setCamOn(false); setHearOn(false); } });
    gsap.to(camInner.current, { yPercent: 100, duration: 0.45, ease: "power2.in" });
  };
  // result is set ONLY for the in-app test (and the practice report) — its numbers feed the run. An uploaded file carries none.
  const attachHearing = (blob: Blob, name: string, result?: Result) => {
    if (hearing) URL.revokeObjectURL(hearing.url);
    setHearing({ blob, url: URL.createObjectURL(blob), name, result });
  };
  const clearHearing = () => {
    if (hearing) URL.revokeObjectURL(hearing.url);
    setHearing(null);
  };
  // Dev-only practice attachments: the personal ear photo (public/dev/ear.png, gitignored) and a fake hearing test. ponytail: dev builds only — production has no such file and no business faking a patient.
  const practice = async () => {
    const res = await fetch("/dev/ear.png");
    if (!res.ok) return;
    clearPhoto();
    const blob = await res.blob();
    // Ear in public/dev/ear.png (656x534): helix top ~y88, lobe/stud ~y400, canal side ~x270 to rim ~x455.
    setPhoto({ blob, url: URL.createObjectURL(blob), box: [240, 70, 470, 430], side: "left" });
    const r = fakeHearing();
    attachHearing(hearingPdf(r), `Hearing test ${r.date}.pdf`, r);
  };
  // One router for the composer "+" and drops: an image is the EAR photo, a PDF is the hearing test. A clinic audiogram that is an IMAGE must come through the pill "+" next to Capture Hearing, which always files it as a hearing test.
  const addFiles = (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      if (f.type.startsWith("image/")) {
        clearPhoto();
        setPhoto({ blob: f, url: URL.createObjectURL(f) });
      } else if (f.type === "application/pdf") attachHearing(f, f.name);
    }
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
      setPhoto({ blob, url: URL.createObjectURL(blob), mirror: true });
      // The still becomes a chat attachment (chip in the composer), so the panel retracts instead of lingering over it.
      closePanel();
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

  const busy = starting || run?.status === "queued" || run?.status === "running";
  const orbState: OrbState = !sent || panelOn ? "idle" : arrived && busy ? "loading" : "active";
  const canRun = !!photo && !!hearing && !busy;
  const canSend = lead ? !lead.waiting : canRun;
  const talk = async (message: string, id = run?.id) => {
    if (!id) return;
    setLead((l) => ({ line: l?.line ?? "", waiting: true }));
    try {
      setLead({ line: (await talkToLead(id, message)).reply, waiting: false });
    } catch {
      setLead({ line: "The assistant is unreachable. Is the agents server running on :8010?", waiting: false });
    }
  };
  const note = runErr ?? (run ? runNote(run) : "");
  // Dev shortcut: skip upload, run and ear views and land in the lead conversation, as if a run had just finished. The lead reads a FINISHED patient from the backend's data folder (job.json), so this needs one: d60d88e7550d is the validation patient (done, left ear); override with NEXT_PUBLIC_DEV_RUN_ID. The lead agents server (:8010) must be up.
  const skipToLead = () => {
    if (lead) return;
    const id = process.env.NEXT_PUBLIC_DEV_RUN_ID ?? "d60d88e7550d";
    if (panelOn) closePanel();
    clearPhoto();
    clearHearing();
    setRun({ id, status: "done" });
    setSent(true);
    void talk("", id);
  };
  keyFn.current = (e) => {
    // Chord: both held, either order. Not while typing — "12" in the chat box is a message, and repeat must not refire it.
    const typing = e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement;
    if (!e.repeat && !typing && held.current.has("1") && held.current.has("2")) return skipToLead();
    if (e.key === "CapsLock" && e.getModifierState("CapsLock")) void practice();
    else if (e.key === "Enter" && canRun && e.target === document.body) {
      e.preventDefault();
      form.current?.requestSubmit();
    }
  };
  const iconBtn = { display: "flex", alignItems: "center", justifyContent: "center", width: 34, height: 34, borderRadius: 999, cursor: "pointer", font: "inherit" } as const;
  const zoomBtn = { ...iconBtn, width: 38, height: 38, border: 0, background: "rgba(0,0,0,0.55)", color: "#e6e8eb" } as const;
  const icon = { width: 18, height: 18, fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  // Metal-ringed pill above the card. No label = round icon-only button, so it needs an aria-label.
  const pill = (onClick: () => void, d: string[], label?: string, color = "#757575", aria?: string) => (
    <div style={{ background: "#000", borderRadius: 20 }}>
      <MetalFx variant="button" preset="silver" theme="dark" innerShadow ringCssPx={2} borderRadius={20}>
        <button type="button" aria-label={aria} onClick={onClick} style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, height: 40, minWidth: 40, padding: label ? "0 24px" : 0, border: 0, borderRadius: 20, background: "#000", color, cursor: "pointer", font: "inherit", fontSize: 16 }}>
          <svg viewBox="0 0 24 24" width="1.1em" height="1.1em" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{d.map((p) => <path key={p} d={p} />)}</svg>
          {label}
        </button>
      </MetalFx>
    </div>
  );

  return (
    <>
    {/* The up arrow is live only once an ear photo AND a hearing test are attached; plus is inert. Width 600 approximates the dock's resting width — retune if the dock changes. */}
    {/* The ear stage's three views, revealed as the backend writes them; the orb's rect is where the stack lands. */}
    {run && <EarViews key={run.id} files={run.files} anchor={() => orb.current?.getBoundingClientRect() ?? null} onGone={() => void talk("")} />}
    <div ref={chat} style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)", width: 600, maxWidth: "calc(100vw - 32px)", zIndex: 10 }}>
    {/* Orb draws at full resolution (components/Orb.tsx), so size is plain pixels. zIndex -1 sits behind the card and bar inside this wrapper's stacking context. The inner div carries the post-send y/scale tween, so GSAP NEVER rewrites the centering translate on the outer one. */}
    <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", zIndex: -1, pointerEvents: "none" }}>
      <div ref={orb} data-testid="orb" data-state={orbState} style={{ position: "relative" }}>
        <Orb px={ORB_PX} speed={orbState === "idle" ? 1 : 2} spin={spin.current} />
        {/* Sits under the visible sphere (canvas is ORB_FILL sphere + padding) and scales with the orb. Colour and font match the Capture Ear pill label (pill() default colour), one size up; dividing by --orb-s undoes the orb's scale so it stays 18px on short screens. */}
        {(lead ? orbState !== "idle" : orbState === "loading") && <div role="status" className="orb-sub" style={{ position: "absolute", top: `calc(${(ORB_PX * (1 + ORB_FILL)) / 2 + 28}px + 22px / var(--orb-s, 1))`, transform: "translateY(-100%)", left: 0, right: 0, textAlign: "center", fontSize: "calc(18px / var(--orb-s, 1))", lineHeight: "calc(22px / var(--orb-s, 1))", color: "#757575" }}>{/* Anchored by its BOTTOM edge at the one-line spot: ORB_SUB reserves room for ONE line, so a longer lead reply grows UP over the orb, never down onto the Capture pills. */}{lead ? (lead.waiting ? "…" : lead.line) : "Processing…"}</div>}
      </div>
    </div>
    {/* Bar floats above the card (bottom: 100%) so the card stays centered, and hugs its content. While a panel (camera or hearing) is open the bar joins the flow instead, so the wrapper (centered by its translate) re-centers feed + card together and the card is pushed down. Inert until capture is wired. Grey matches the textarea placeholder. */}
    <div style={panelOn ? { display: "flex", justifyContent: "center" } : { position: "absolute", bottom: "100%", left: 0, right: 0, marginBottom: 12, display: "flex", justifyContent: "center", gap: 10 }}>
      {!panelOn && (
        <>
          {pill(openCam, ["M4 8h3l2-3h6l2 3h3v11H4z", "M12 10a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z"], camErr ?? "Capture Ear", camErr ? "#f87171" : undefined)}
          {pill(() => setHearOn(true), ["M3 14v-2a9 9 0 0 1 18 0v2", "M21 15a2 2 0 0 1-2 2h-1v-5h3z", "M3 15a2 2 0 0 0 2 2h1v-5H3z"], "Capture Hearing")}
          {pill(() => upload.current?.click(), ["M12 5v14", "M5 12h14"], undefined, undefined, "Upload hearing test")}
          {/* Upload path for patients who already have a clinic audiogram (specs/01a path A). */}
          <input ref={upload} data-testid="hearing-input" type="file" accept="application/pdf,image/*" hidden onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) attachHearing(f, f.name);
            e.target.value = "";
          }} />
        </>
      )}
      {/* Camera panel REPLACES the Capture Ear button above the card. It is in flow, so growing its height shoves the card down while the centered wrapper keeps the pair centered. The 12px gap is animated on the panel (not the bar) so the swap back to the floating button does not jump the card; border is a box-shadow for the same reason. Height cap keeps the pair clear of the 140px dock; see the camOn effect. */}
      {camOn && (
        <div ref={camPanel} style={{ width: "100%", overflow: "hidden", borderRadius: 24, border: "2px solid transparent", background: `linear-gradient(#000, #000) padding-box, ${SILVER} border-box` }}>
          <div ref={camInner} style={{ position: "relative", height: "max(180px, min(340px, calc(100vh - 420px)))" }}>
            <video ref={camVideo} muted playsInline style={{ width: "100%", height: "100%", objectFit: "cover", display: "block", transform: `scaleX(-1) scale(${zoom})` }} />
            {photo && <img src={photo.url} alt="Captured ear" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", transform: "scaleX(-1)" }} />}
            <button type="button" aria-label="Close camera" onClick={closePanel} style={{ position: "absolute", top: 12, right: 12, width: 32, height: 32, borderRadius: 999, border: 0, background: "rgba(0,0,0,0.55)", color: "#e6e8eb", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg viewBox="0 0 24 24" {...icon}><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
            {!photo && (
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
      {hearOn && (
        <div ref={camPanel} style={{ width: "100%", overflow: "hidden", borderRadius: 24, border: "2px solid transparent", background: `linear-gradient(#000, #000) padding-box, ${SILVER} border-box` }}>
          <div ref={camInner} style={{ position: "relative", height: "max(180px, min(340px, calc(100vh - 420px)))" }}>
            <HearingTest
              onClose={closePanel}
              onDone={(r) => {
                attachHearing(hearingPdf(r), `Hearing test ${r.date}.pdf`, r);
                closePanel();
              }}
            />
          </div>
        </div>
      )}
    </div>
    <div
      data-testid="drop-zone"
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) setDragging(true); }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }}
      onDrop={(e) => { setDragging(false); addFiles(e.dataTransfer.files); }}
      style={{ background: "#000", borderRadius: 24, outline: dragging ? "2px dashed #757575" : "none", outlineOffset: 4 }}
    >
    <MetalFx variant="button" preset="silver" theme="dark" innerShadow ringCssPx={2} borderRadius={24} style={{ width: "100%" }}>
    <form
      ref={form}
      onSubmit={async (e) => {
        e.preventDefault();
        if (lead) {
          // Once the lead is on, the composer is ITS input — it never starts another run.
          const ta = e.currentTarget.elements.namedItem("msg") as HTMLTextAreaElement;
          const msg = ta.value.trim();
          if (!msg || lead.waiting) return;
          ta.value = "";
          void talk(msg);
          return;
        }
        // A run needs BOTH inputs. Enter in the textarea submits too, so the guard lives here, not only on the arrow.
        if (!photo || !hearing || busy) return;
        const ta = e.currentTarget.elements.namedItem("msg") as HTMLTextAreaElement;
        setStarting(true);
        setRunErr(null);
        try {
          setRun(await startRun(photo.blob, hearing.result, photo.box, photo.side));
          ta.value = "";
          setSent(true);
          clearPhoto();
          clearHearing();
        } catch (err) {
          // Attachments stay so the patient can retry without retaking either.
          setRunErr(err instanceof Error && err.message !== "Failed to fetch" ? err.message : "Could not reach the server.");
        } finally {
          setStarting(false);
        }
      }}
      style={{ boxSizing: "border-box", width: "100%", padding: 14, borderRadius: 24, background: "#000" }}
    >
      {(photo || hearing) && <div style={{ display: "flex", gap: 10 }}>
      {photo && (
        <div data-testid="attachment" style={{ position: "relative", width: 64, height: 64, margin: "0 6px 8px" }}>
          <img src={photo.url} alt="Captured ear attachment" style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 12, transform: photo.mirror ? "scaleX(-1)" : undefined }} />
          <button type="button" aria-label="Remove attachment" onClick={clearPhoto} style={{ position: "absolute", top: -6, right: -6, width: 20, height: 20, padding: 0, borderRadius: 999, border: 0, background: "#3b3d42", color: "#e6e8eb", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
      )}
      {hearing && (
        <div data-testid="hearing-attachment" style={{ position: "relative", width: 64, height: 64, margin: "0 6px 8px" }}>
          <a href={hearing.url} target="_blank" rel="noreferrer" title={hearing.name} style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4, width: "100%", height: "100%", borderRadius: 12, background: "#1c1d20", color: "#c9ccd1", fontSize: 11, textDecoration: "none" }}>
            <svg viewBox="0 0 24 24" {...icon}><path d="M14 3H6v18h12V7z" /><path d="M14 3v4h4" /><path d="M9 13h6M9 17h6" /></svg>
            {(hearing.name.split(".").pop() ?? "").toUpperCase()}
          </a>
          <button type="button" aria-label="Remove hearing test" onClick={clearHearing} style={{ position: "absolute", top: -6, right: -6, width: 20, height: 20, padding: 0, borderRadius: 999, border: 0, background: "#3b3d42", color: "#e6e8eb", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
      )}
      </div>}
      {note && (
        <div data-testid="run-status" role="status" style={{ padding: "0 6px 8px", fontSize: 13, color: runErr || run?.status === "error" ? "#f87171" : "#9aa0a8" }}>{note}</div>
      )}
      <textarea
        name="msg"
        rows={2}
        placeholder="How can I help you today?"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
        }}
        style={{ display: "block", width: "100%", boxSizing: "border-box", resize: "none", border: 0, outline: 0, background: "transparent", color: "#e6e8eb", font: "inherit", fontSize: 16, padding: "4px 6px" }}
      />
      <input ref={pick} data-testid="add-input" type="file" multiple accept="image/*,application/pdf" hidden onChange={(e) => {
        if (e.target.files) addFiles(e.target.files);
        e.target.value = "";
      }} />
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
        <button type="button" aria-label="Add" onClick={() => pick.current?.click()} style={{ ...iconBtn, border: "1px solid rgba(255,255,255,0.18)", background: "transparent", color: "#c9ccd1" }}>
          <svg viewBox="0 0 24 24" {...icon}><path d="M12 5v14M5 12h14" /></svg>
        </button>
        <button type="submit" aria-label="Send" disabled={!canSend} title={canSend ? undefined : lead ? "Waiting for a reply" : "Add an ear photo and a hearing test to start"} style={{ ...iconBtn, border: 0, background: "#3b82f6", color: "#fff", opacity: canSend ? 1 : 0.35, cursor: canSend ? "pointer" : "not-allowed" }}>
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
