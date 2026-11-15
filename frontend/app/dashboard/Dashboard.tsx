"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { MetalFx, SILVER } from "@/components/metal";
import Dock from "@/components/Dock";
import Orb, { type OrbNode } from "@/components/Orb";
import HearingTest from "@/components/HearingTest";
import { hearingPdf } from "@/lib/hearingPdf";
import { fakeHearing } from "@/lib/fakeHearing";
import type { Result } from "@/lib/audiometry";
import { pollRun, runNote, startRun, type EarPhoto, type Run } from "@/lib/run";
import type { Ear } from "@/lib/audiometry";
import { createSession, getLead, leadEvent, listSessions, MOVING, studyEvents, talkToLead, type LeadReply } from "@/lib/lead";
import SimRuns, { type Outcome } from "@/app/sim/SimRuns";
import AidOptions from "@/components/AidOptions";
import { designFile, designStatus, startDesign, startWaveCheck, waveGain, waveStatus } from "@/app/sim/lib/api";
import ResearchBoxes, { RESEARCH_LINE } from "@/components/ResearchBoxes";
import EarViews, { type View } from "@/components/EarViews";
import WaveBento from "@/components/WaveBento";
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
/** The two ear rows: label height above each row's cards, and the gap between the rows. */
const ROW_LABEL = 20, ROW_GAP = 12;
/** The sphere fills ~80% of the Orb canvas; the rest is transparent padding. Layout math uses the visible size, or the separated pair sits too far apart. */
const ORB_FILL = 0.8;
const DOCK_BOTTOM = 100;
/** Height kept free under the sphere for the loading sub text, so "Processing…" NEVER lands on the Capture pills. */
const ORB_SUB = 48;
/** Same, while the lead talks: room for THREE lines of its reply, which grows DOWN from the "Processing…" spot. */
const ORB_SUB_LEAD = 92;
/** Composer photo slots, in the order the camera, an upload or a drop fills them. The face is LAST and optional — a run never waits on it. */
const SLOTS = ["left", "right", "selfie"] as const;
type Slot = (typeof SLOTS)[number];
/** The dev shortcuts' patient (1 + 2, 3 + 4, 5): a FINISHED run in the backend's data folder. d60d88e7550d is the validation patient (done, left ear). */
const DEV_RUN_ID = process.env.NEXT_PUBLIC_DEV_RUN_ID ?? "d60d88e7550d";
const STUDY_LABEL: Record<LeadReply["status"], string> = { none: "talking", running: "researching", completed: "research done", failed: "research failed", cancelled: "cancelled", stopped: "research stopped", error: "could not start" };
const sessionLabel = (x: LeadReply) =>
  `${new Date(x.updated_at * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} · ${x.stage === "new" ? "processing" : STUDY_LABEL[x.status]}`;
const SLOT_NAME: Record<Slot, string> = { left: "Left ear", right: "Right ear", selfie: "Face" };
/** The head row's views (backend files.head): the MediaPipe landmarks drawn on the face, then the head carrying both ears. The raw selfie is NEVER shown — landmarks.jpg exists only if a face was found, and without it the row is the model alone (headViews). */
const HEAD_FACE: View[] = [{ file: "landmarks.jpg", label: "Face points" }];
const HEAD_MODEL: View[] = [{ file: "head_ears.glb", label: "Head model" }];
/** idle: behind the card. active: rising to, or resting at, the top. loading: at the top while a run is queued or running — the ONLY state that shows the "Processing…" sub text. */
type OrbState = "idle" | "active" | "loading";
/** Gap between the sent-state chat card and the bottom edge. */
const BOTTOM = 64;
/** Zoomed, the sphere spans this many times the shorter screen side — the camera flies THROUGH it, so it ends off screen and faded out. */
const ZOOM_FILL = 8;

export default function Dashboard() {
  // MetalFx renders a placeholder on the server and a WebGL canvas on the client — mounting after hydration avoids the mismatch.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const dockWrap = useRef<HTMLDivElement>(null);
  const chat = useRef<HTMLDivElement>(null);
  const orb = useRef<HTMLDivElement>(null);
  const spin = useRef({ a: 0 });
  // The center orb's dots as drawn, refilled every frame by Orb: the research view lands its info-board dots on them.
  const orbNodes = useRef<OrbNode[]>([]);
  // Drag-to-spin: last pointer x and time, the latest velocity (px/ms) for the release coast, and total travel so a drag never counts as a click.
  const drag = useRef<{ x: number; t: number; v: number; dist: number } | null>(null);
  const dragged = useRef(false);
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
  // Capture Ear: camOn mounts the feed panel; each shot fills the next empty ear slot (photos below).
  const [camOn, setCamOn] = useState(false);
  const [camErr, setCamErr] = useState<string | null>(null);
  // One photo per ear SLOT: the slot is the side, so the backend never guesses it. box is set only by the practice shortcut, which knows its photo; every other photo leaves it out and the backend detects the ear.
  const [photos, setPhotos] = useState<Partial<Record<Slot, EarPhoto>>>({});
  // The slot the camera, an upload or a drop fills next — left, right, then the face. All full: undefined.
  const nextSlot: Slot | undefined = SLOTS.find((s) => !photos[s]);
  // Rows (left, right, head) that have shrunk into the orb, as `${run}:${row}` so a new run never counts an old row. The lead opens from these (see the effect below).
  const [goneRows, setGoneRows] = useState<string[]>([]);
  // The rows share ONE closing: `${run}:${row}` ids of rows whose views have all landed, and of rows with a view expanded.
  const [formedRows, setFormedRows] = useState<string[]>([]);
  const [openRows, setOpenRows] = useState<string[]>([]);
  const [collapseRun, setCollapseRun] = useState<string | null>(null);
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
  const leadOn = lead !== null;
  // The lead's latest full reply: its stage and the simulation half (scenes, options, report). null before the lead speaks.
  const [view, setView] = useState<LeadReply | null>(null);
  // The research view: the four investigator boxes in the corners, and the chat card and pills go see-through so only their metal rings draw. Opens when the lead launches the study (or a launched session is picked); dev key 5 toggles it.
  const [research, setResearch] = useState(false);
  // Saved lead sessions for the picker under the chat card, one per run (agents server, most recent first). Empty when the server is down — the picker then offers only "New session".
  const [sessions, setSessions] = useState<LeadReply[]>([]);
  // null = the list could not load (agents server down, or an old one without /sessions) — said in the picker, NOT shown as an empty history.
  const [sessionsErr, setSessionsErr] = useState<string | null>(null);
  const refreshSessions = () => listSessions().then((l) => { setSessions(l); setSessionsErr(null); }, (e: Error) => setSessionsErr(/404/.test(e.message) ? "agents server is outdated, restart it" : "agents server unreachable"));
  // The open run IS the page's address (?session=<run id>), written as soon as a send starts it, so a refresh or a shared link lands back in the same session at whatever point it was saved. ONLY written while a run is open — "New session" clears it (openSession), or the first render would wipe the param before the restore below reads it.
  useEffect(() => {
    if (run) history.replaceState(null, "", `${location.pathname}?session=${run.id}`);
  }, [run?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const restored = useRef(false);
  useEffect(() => {
    if (!ready || restored.current) return;
    restored.current = true;
    const id = new URLSearchParams(location.search).get("session");
    if (id && /^[A-Za-z0-9_-]{1,64}$/.test(id)) void openSession(id);
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { void refreshSessions(); }, []);
  const fill = research ? "transparent" : "#000";
  // Seconds the agent orbs wait before flying out: the center orb's 0.9 s rise when 5 is pressed before any send.
  const flyDelay = useRef(0);
  // simReady makes the orb clickable; zoomed is the full-screen orb with the dock and chat hidden. ponytail: launch_requested stands in for "research finished" until the study workflow reports completion.
  const [simReady, setSimReady] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  // Escape and the X close the orb the SAME way (exitSim): a close can move the lead on.
  const exitRef = useRef(() => setZoomed(false));
  // Dev chord 3+4: the orb stays clickable whatever stage the lead reports — otherwise its reply, landing after the chord, switches it back off.
  const devSim = useRef(false);
  const bar = useRef<HTMLDivElement>(null);
  const simWrap = useRef<HTMLDivElement>(null);
  // True once the zoom-in has LANDED. The sims mount on this, never on zoomed: building their 3D scenes and workers blocks the main thread for seconds, and doing it mid-zoom freezes the zoom and the chrome fade.
  const [inside, setInside] = useState(false);
  useLayoutEffect(() => {
    if (inside) gsap.fromTo(simWrap.current, { opacity: 0 }, { opacity: 1, duration: 0.5, ease: "power1.out" });
  }, [inside]);
  const card = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!zoomed) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && exitRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomed]);
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
    // 750 ms: each ear's views appear as soon as the backend writes them; half the old 1.5 s between a file landing and the reveal.
    const t = setInterval(() => pollRun(run).then(setRun, () => {}), 750);
    return () => clearInterval(t);
  }, [run?.id, run?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const rowGone = (row: string) => !!run && goneRows.includes(`${run.id}:${row}`);
  // The head row gates the lead ONLY while a head can still arrive: head_ears.glb is written (the row WILL finish), or the job is still on an ear step or the head step (backend/app/jobs.py). Otherwise — a patient from before the head stage, or a head stage that failed (it never fails the job) — the lead opens as soon as both ear rows are gone and the head row is dropped, or the lead would wait forever.
  const headComing = !!run?.files?.head?.["head_ears.glb"] || run?.step === "head" || /:ear$/.test(run?.step ?? "");
  const earsGone = rowGone("left") && rowGone("right");
  useEffect(() => {
    if (run && !lead && earsGone && (rowGone("head") || !headComing)) void talk("");
  }, [run?.id, earsGone, headComing, goneRows]); // eslint-disable-line react-hooks/exhaustive-deps
  // Every expected row formed (the head row only while a head can still come, as above), none expanded, for 3 s: ALL rows close together. One row closing on its own timer while another was still revealing left a ragged screen.
  const rowsSettled = !!run && ["left", "right", ...(headComing ? ["head"] : [])].every((r) => formedRows.includes(`${run.id}:${r}`))
    && !openRows.some((r) => r.startsWith(`${run.id}:`));
  useEffect(() => {
    if (!run || !rowsSettled) return;
    const t = setTimeout(() => setCollapseRun(run.id), 3000);
    return () => clearTimeout(t);
  }, [run?.id, rowsSettled]); // eslint-disable-line react-hooks/exhaustive-deps
  const rowProps = (row: string) => run && ({
    collapse: collapseRun === run.id,
    onRow: () => setFormedRows((f) => [...f, `${run.id}:${row}`]),
    onOpen: (o: boolean) => setOpenRows((rs) => (o ? [...rs, `${run.id}:${row}`] : rs.filter((x) => x !== `${run.id}:${row}`))),
  });
  // After the first send the card slides down to the bottom and the orb rises into the space above it. Card moves by marginTop on the wrapper (its translate does the centering); the orb tween subtracts that same shift. An open panel (camera or hearing) returns both to center — the panel is sized for a centered stack. ponytail: measured on send/camera toggle only, not on window resize.
  useLayoutEffect(() => {
    const w = chat.current, o = orb.current, f = form.current;
    if (!w || !o || !f) return;
    let shift = 0, orbY = 0, s = 1, subH = ORB_SUB;
    if (sent && !panelOn) {
      // Card drops to BOTTOM px above the screen edge; the orb centers in the gap between the dock icons' bottom edge (DOCK_BOTTOM: dock top 12 + (panelHeight 100 - item 76) / 2 + 76) and the Capture Ear button's top (card top - 40 button - 12 margin), shrinking only when that gap is too short.
      const vh = window.innerHeight, h = f.offsetHeight, bar = 52, gap = 8;
      shift = vh - BOTTOM - h / 2 - vh / 2;
      const capTop = vh - BOTTOM - h - bar - (leadOn ? ORB_SUB_LEAD : ORB_SUB);
      s = Math.min(1, (capTop - DOCK_BOTTOM - 2 * gap) / (ORB_PX * ORB_FILL));
      orbY = (DOCK_BOTTOM + capTop) / 2 - (vh / 2 + shift);
      // Sphere bottom to Capture pills top, in the orb's own (unscaled) px: the lead's reply centers in this band.
      subH = (vh - BOTTOM - h - bar - ((DOCK_BOTTOM + capTop) / 2 + (s * ORB_PX * ORB_FILL) / 2)) / s;
      // Zoomed: the card keeps its place (it is hidden), so the orb undoes the card's shift to land on screen center.
      if (zoomed) {
        orbY = -shift;
        s = (Math.min(window.innerWidth, vh) * ZOOM_FILL) / (ORB_PX * ORB_FILL);
      }
    }
    setArrived(false);
    if (!zoomed) setInside(false);
    const ctx = gsap.context(() => {
      const dur = 0.9;
      // ONE ease for card and orb: the orb lives inside the card's wrapper, so its screen path is marginTop + y — a different ease on either makes the orb rise, dip, then rise again. power1.inOut is GSAP's closest match to After Effects' Easy Ease.
      const ease = "power1.inOut";
      gsap.to(w, { marginTop: shift, duration: dur, ease });
      // Zooming in accelerates (power2.in) so it reads as flying into the orb; the card does not move while zooming, so the shared-ease rule above does not apply.
      gsap.to(o, { y: orbY, scale: s, "--orb-s": s, "--orb-sub-h": `${subH}px`, duration: dur, ease: zoomed ? "power2.in" : ease, onComplete: () => { setArrived(sent && !panelOn); setInside(zoomed); } });
      // The fade covers the back half of the zoom in and the front half of the zoom out, so the orb is gone exactly when the camera is inside it.
      gsap.to(o, { opacity: zoomed ? 0 : 1, duration: dur / 2, delay: zoomed ? dur / 2 : 0, ease: "power1.in" });
      // Active (orb out from behind the card) turns the sphere a half turn about its vertical axis, still coasting briefly after the rise lands. It does NOT share the card/orb ease: spin is a yaw drawn in the canvas, not a position, so its curve cannot cause the dip.
      // Target the turn NEAREST the current yaw — after a drag spin.a can be many turns out, and an absolute target would unwind every one of them.
      const goal = sent && !panelOn ? Math.PI : 0;
      gsap.to(spin.current, { a: goal + 2 * Math.PI * Math.round((spin.current.a - goal) / (2 * Math.PI)), duration: dur * SPIN_STRETCH, ease: SPIN_EASE });
      // Opacity only — MetalFx forces visibility: visible on its children, so autoAlpha leaves the card showing. `inert` (in the JSX) keeps the faded chrome from catching clicks or Tab. The dock's strip, NEVER its items — the intro owns their opacity.
      gsap.to([dockWrap.current, bar.current, card.current], { opacity: zoomed ? 0 : 1, duration: zoomed ? 0.4 : 0.6, delay: zoomed ? 0 : 0.5, ease: "power1.out" });
    });
    return () => ctx.kill();
  }, [ready, sent, panelOn, zoomed, leadOn]);
  // apply and step are defined below the `ready` early return; the hooks here reach them through refs.
  const applyRef = useRef<(r: LeadReply) => void>(() => {});
  const stepRef = useRef<(event: string, data?: Record<string, unknown>) => Promise<void>>(async () => {});
  // Stages that move without the patient (research finishing, the scene picker) are polled; every other stage moves on a send or a step.
  useEffect(() => {
    if (!run || !view || !MOVING.includes(view.stage)) return;
    const t = window.setInterval(() => void getLead(run.id).then((r) => r && (r.stage !== view.stage || r.reply !== view.reply) && applyRef.current(r), () => {}), 3000);
    return () => window.clearInterval(t);
  }, [run?.id, view?.stage, view?.reply]); // eslint-disable-line react-hooks/exhaustive-deps
  // "Ready to run the simulation?" -> yes: the research boxes fade away, then unmount.
  const boxes = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!research || !view || view.stage === "launched" || view.stage === "sim_ready") return;
    const tw = gsap.to(boxes.current, { opacity: 0, duration: 0.8, ease: "power1.out", onComplete: () => setResearch(false) });
    return () => { tw.kill(); };
  }, [view?.stage, research]); // eslint-disable-line react-hooks/exhaustive-deps
  const DESIGN_MAX_SCENES = 64;
  // designing: ask the backend for the four designs from the simulations' deficits, poll, and hand them to the lead. ONE request per entry into the stage.
  const designing = useRef(false);
  useEffect(() => {
    if (!run || view?.stage !== "designing" || !view.sims || designing.current) return;
    designing.current = true;
    const { results, audiogram_db_hl } = view.sims, ear = view.ear ?? undefined;
    let live = true;
    (async () => {
      // The backend designs from at most 64 scenes (sim_api DesignRequest); a 100-scene run sends the 64 that weigh most:
      // scene weight × speech-weighted hearing lost. Over 64, the whole request failed with a 422.
      // The talker of each scene the lead picked: the designer aims each option at one of them.
      const talker = (id: string) => view.scenes?.find((sc) => sc.id === id)?.sources.find((src) => src.role === "talker");
      const need = (x: (typeof results)[number]) => x.weight * x.deficit_weighted.reduce((a, b) => a + b, 0);
      const scenes = results.filter((x) => x.weight > 0).sort((a, b) => need(b) - need(a)).slice(0, DESIGN_MAX_SCENES)
        .map((x) => ({ id: x.id, name: x.name, weight: x.weight, deficit_db: x.deficit_db, deficit_weighted: x.deficit_weighted, talker_az_deg: talker(x.id)?.az, talker_el_deg: talker(x.id)?.el }));
      // "already running" (a reload mid-design) is fine: the poll below picks that design up.
      await startDesign(run.id, audiogram_db_hl, scenes, ear).catch((e: Error) => { if (!/already running/.test(e.message)) throw e; });
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 1500));
        if (!live) return;
        const st = await designStatus(run.id, ear).catch(() => null);
        if (st?.status === "error") throw new Error(st.error ?? "design failed");
        if (st?.status !== "done" || !st.result) continue;
        const opts = st.result.options ?? [{ ...st.result.design, reason: "The best design for your scenes." }];
        return stepRef.current("options", { options: opts.map((o) => ({ id: o.id, reason: o.reason, key_met: o.key_met, gain_mean_db: o.gain_mean_db, files: o.files, recommended: o.recommended })) });
      }
    })().catch((e: Error) => { if (live) void stepRef.current("design_failed", { error: e.message }); }).finally(() => { designing.current = false; });
    return () => { live = false; };
  }, [run?.id, view?.stage]); // eslint-disable-line react-hooks/exhaustive-deps
  // The simulations' latest numbers (SimRuns onDone), sent to the lead when the patient closes the orb.
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // validating onward: the SAME scenes again, with the PICKED earpiece voxelized into the backend's wave sim (hornsim.aided_wave). Its gain is
  // the aided curve; the design's own 1D gain stands in ONLY if the check fails. A reload re-reads a finished check.
  // ponytail: 1.5 mm, not the check's 1.0 default — 1.0 takes 10+ minutes for five directions, 1.5 a couple of minutes.
  const [aidGain, setAidGain] = useState<number[] | null>(null);
  useEffect(() => {
    const did = view?.picked;
    setAidGain(null);
    if (!run || !did || !(view.stage === "validating" || view.stage === "final" || view.stage === "done")) return;
    const ear = view.ear ?? undefined;
    let live = true;
    (async () => {
      let st = await waveStatus(run.id, ear);
      if (st.design_id !== did || st.status === "none" || st.status === "error") await startWaveCheck(run.id, [0, 45, 90, 135, 180], 1.5, did, ear);
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 2000));
        if (!live) return;
        st = await waveStatus(run.id, ear);
        if (st.status === "error") throw new Error(st.error ?? "wave check failed");
        if (st.status === "done" && st.result && st.design_id === did) return setAidGain(waveGain(st.result));
      }
    })().catch(() => { if (live) setAidGain(view.options?.find((o) => o.id === did)?.gain_mean_db ?? null); });
    return () => { live = false; };
  }, [run?.id, view?.picked, view?.stage === "validating" || view?.stage === "final" || view?.stage === "done"]); // eslint-disable-line react-hooks/exhaustive-deps
  // done: the report PDF (lib/reportPdf.ts) and the print file download by themselves, ONCE per session — a reload of a
  // finished session must not download them again. The lead's own line under the orb says they are on the way.
  useEffect(() => {
    if (!run || view?.stage !== "done" || !view.report) return;
    const key = `auris-report:${run.id}`;
    try { if (localStorage.getItem(key)) return; } catch {}
    let live = true;
    const v = view, id = run.id;
    (async () => {
      const [{ buildReport, save }, events] = await Promise.all([import("@/lib/reportPdf"), studyEvents(id).then((r) => r.events, () => [])]);
      const pdf = await buildReport({ runId: id, view: v, events });
      if (!live) return;
      try { localStorage.setItem(key, "1"); } catch {}
      const day = new Date().toISOString().slice(0, 10);
      save(pdf, `Auris report ${day}.pdf`);
      if (!v.picked) return;
      // The lead's custom earpiece in S, M and L when it built; else the picked design's own print file.
      const e = v.earpiece;
      const prints = e?.status === "built" ? Object.entries(e.sizes ?? {}).filter(([, z]) => z.ok).map(([k, z]) => [`Auris earpiece ${k} ${day}.stl`, z.design_id] as const)
        : [[`Auris earpiece ${day}.stl`, v.picked] as const];
      for (const [name, did] of prints) {
        const stl = await fetch(designFile(id, did, "earpiece_print.stl", v.ear ?? undefined)).then((r) => (r.ok ? r.blob() : null), () => null);
        if (stl) save(stl, name);
      }
    })().catch(() => { if (live) setLead({ line: "I couldn't build the report file. Ask me again for your report.", waiting: false }); });
    return () => { live = false; };
  }, [run?.id, view?.stage, !!view?.report]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!ready) return null;

  const openCam = async () => {
    setCamErr(null);
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ video: true });
    } catch {
      setCamErr("Camera unavailable");
      return;
    }
    // Every slot full: the camera retakes ALL of them, left first.
    if (!nextSlot) clearPhoto();
    setZoom(1);
    setCamOn(true);
  };
  /** Clears one slot's photo, or every slot with no argument. */
  const clearPhoto = (slot?: Slot) => {
    setPhotos((ps) => {
      const next = { ...ps };
      for (const e of slot ? [slot] : SLOTS) {
        if (next[e]) URL.revokeObjectURL(next[e]!.url);
        delete next[e];
      }
      return next;
    });
  };
  const setPhoto = (ear: Slot, p: Omit<EarPhoto, "url">) => {
    clearPhoto(ear);
    setPhotos((ps) => ({ ...ps, [ear]: { ...p, url: URL.createObjectURL(p.blob) } }));
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
  // Dev-only practice attachments: the personal ear and face photos (public/dev/ear.png, face.png, gitignored) and a fake hearing test. ponytail: dev builds only — production has no such file and no business faking a patient.
  const practice = async () => {
    const res = await fetch("/dev/ear.png");
    if (!res.ok) return;
    const blob = await res.blob();
    // Ear in public/dev/ear.png (656x534): helix top ~y88, lobe/stud ~y400, canal side ~x270 to rim ~x455. It is a LEFT ear; the right slot gets it mirrored, box mirrored with it.
    const img = await createImageBitmap(blob), c = document.createElement("canvas");
    c.width = img.width;
    c.height = img.height;
    const g = c.getContext("2d")!;
    g.scale(-1, 1);
    g.drawImage(img, -img.width, 0);
    const flipped = await new Promise<Blob | null>((done) => c.toBlob(done, "image/png"));
    setPhoto("left", { blob, box: [240, 70, 470, 430] });
    if (flipped) setPhoto("right", { blob: flipped, box: [img.width - 470, 70, img.width - 240, 430] });
    // The practice face (public/dev/face.png, gitignored) is OPTIONAL like any selfie — without the file the backend builds an average head.
    const face = await fetch("/dev/face.png");
    if (face.ok) setPhoto("selfie", { blob: await face.blob() });
    const r = fakeHearing();
    attachHearing(hearingPdf(r), `Hearing test ${r.date}.pdf`, r);
  };
  // One router for the composer "+" and drops: an image is the next PHOTO slot (left ear, right ear, face), a PDF is the hearing test. A clinic audiogram that is an IMAGE must come through the pill "+" next to Capture Hearing, which always files it as a hearing test.
  const addFiles = (files: FileList | File[]) => {
    // Slots are tracked HERE, not read from nextSlot — state does not update mid-loop, so two images picked at once would both land in the left slot.
    const free = SLOTS.filter((e) => !photos[e]);
    for (const f of Array.from(files)) {
      // An image fills the next empty slot; with all three full, it starts over at left.
      if (f.type.startsWith("image/")) {
        if (!free.length) {
          clearPhoto();
          free.push(...SLOTS);
        }
        setPhoto(free.shift()!, { blob: f });
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
    const slot = nextSlot;
    if (!slot) return;
    c.toBlob((blob) => {
      if (!blob) return;
      setPhoto(slot, { blob, mirror: true });
      // The still becomes a chat attachment (chip in the composer). The camera stays live while a LATER slot is empty (left -> right -> face) and retracts after the last.
      if (SLOTS.slice(SLOTS.indexOf(slot) + 1).some((s) => !photos[s])) return;
      stopStream();
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

  // All three rows (left ear, head, right ear) fit BETWEEN the dock and the Capture pills of the sent layout (see the layout effect): cards shrink on short screens, or the top row lands under the dock. ALWAYS laid out for three — a head arriving later must not shift the ear rows already on screen.
  const earRows = () => {
    const vh = window.innerHeight, h = form.current?.offsetHeight ?? 112;
    const top = DOCK_BOTTOM + 16, bottom = vh - BOTTOM - h - 52 - 8;
    const size = Math.min(192, (bottom - top - 3 * ROW_LABEL - 2 * ROW_GAP) / 3), step = size + ROW_LABEL + ROW_GAP, mid = (top + bottom) / 2;
    return { size, ys: [-1, 0, 1].map((k) => mid + k * step + ROW_LABEL / 2) };
  };
  const head = run?.files?.head;
  // Without landmarks the face view would wait forever; once head.json (written LAST) exists and none came (no selfie, or no face found), the row is the model alone.
  const headViews = head?.["head.json"] && !head["landmarks.jpg"] ? [HEAD_MODEL] : [HEAD_FACE, HEAD_MODEL];
  // A row is ON SCREEN from its first file until it shrinks away. "Processing…" waits for every row to be off screen — it sat on top of the cards.
  const rowsOnScreen = !!run && ((["left", "right"] as const).some((e) => !!run.files?.[e]?.["overlay.jpg"] && !rowGone(e))
    || (!lead && !!(head?.["landmarks.jpg"] || head?.["head_ears.glb"]) && !rowGone("head")));
  const busy = starting || run?.status === "queued" || run?.status === "running";
  const orbState: OrbState = !sent || panelOn ? "idle" : arrived && busy ? "loading" : "active";
  const canRun = !!photos.left && !!photos.right && !!hearing && !busy;
  const faceHint = "add a face photo for a head model (optional)";
  const canSend = lead ? !lead.waiting : canRun;
  /** One lead reply onto the page: its line under the orb, the research boxes while research runs, and a clickable orb ONLY while simulations run (sim_running, validating). */
  const apply = (r: LeadReply) => {
    setView(r);
    setLead({ line: r.reply, waiting: false });
    if (r.stage === "launched") {
      // The study is running from here: the investigator boxes fly out, after the center orb's 0.9 s rise if it is still behind the card. Already open, ResearchBoxes ignores both.
      flyDelay.current = sent && !panelOn ? 0 : 0.9;
      setResearch(true);
    }
    setSimReady(devSim.current || r.stage === "sim_running" || r.stage === "validating");
  };
  const talk = async (message: string, id = run?.id) => {
    if (!id) return;
    setLead((l) => ({ line: l?.line ?? "", waiting: true }));
    try {
      apply(await talkToLead(id, message));
      void refreshSessions();
    } catch {
      setLead({ line: "The assistant is unreachable. Is the agents server running on :8010?", waiting: false });
    }
  };
  /** A dashboard step to the lead (lib/lead.ts leadEvent). A 409 means the session already moved on (another tab, a reload): re-read it. */
  const step = async (event: string, data: Record<string, unknown> = {}) => {
    if (!run) return;
    setLead((l) => ({ line: l?.line ?? "", waiting: true }));
    try {
      apply(await leadEvent(run.id, event, data));
    } catch {
      const r = await getLead(run.id).catch(() => null);
      if (r) apply(r);
      else setLead({ line: "The assistant is unreachable. Is the agents server running on :8010?", waiting: false });
    }
  };
  const exitSim = () => {
    setZoomed(false);
    if (!view || (view.stage !== "sim_running" && view.stage !== "validating")) return;
    // Closing early never moves the flow on: the runs keep going in the background, and the patient closes again once they finish.
    if (!outcome || (view.stage === "validating" && !outcome.aided))
      return setLead({ line: "Still running. Click the orb to watch, and close it once they finish.", waiting: false });
    const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
    const pct = (v: number) => `${Math.round(v * 100)}%`;
    const unaided = mean(outcome.results.map((x) => x.sii_unaided));
    const healthy = mean(outcome.results.map((x) => x.sii_healthy));
    if (view.stage === "sim_running") {
      return void step("sims_done", { ...outcome, summary: `Across ${outcome.results.length} scenes you hear ${pct(unaided)} of speech on average, against ${pct(healthy)} with normal hearing.` });
    }
    const aided = outcome.aided!.map((v) => v ?? 0);
    const n = (view.options?.findIndex((o) => o.id === view.picked) ?? 0) + 1;
    void step("validated", { aided, gain_db: aidGain, summary: `With option ${n} you hear ${pct(mean(aided))} of speech on average, against ${pct(healthy)} with normal hearing (${pct(unaided)} without it).` });
  };
  exitRef.current = exitSim;
  /** The orb's centre on screen (its rect already includes the rise's scale). */
  const orbSphere = () => {
    const r = orb.current?.getBoundingClientRect();
    return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null;
  };
  applyRef.current = apply;
  stepRef.current = step;
  const note = runErr ?? (run ? runNote(run) : "");
  // Dev shortcut: skip upload, run and ear views and land in the lead conversation, as if a run had just finished. The lead reads a FINISHED patient from the backend's data folder (job.json), so this needs one: d60d88e7550d is the validation patient (done, left ear); override with NEXT_PUBLIC_DEV_RUN_ID. The lead agents server (:8010) must be up.
  const skipToLead = () => {
    if (lead) return;
    const id = DEV_RUN_ID;
    if (panelOn) closePanel();
    clearPhoto();
    clearHearing();
    setRun({ id, status: "done" });
    setSent(true);
    void talk("", id);
  };
  /** Switches the dashboard to a saved session — its run, chat line and research view — or back to a fresh upload ("new"). */
  const openSession = async (id: string) => {
    if (panelOn) closePanel();
    setZoomed(false);
    setResearch(false);
    setSimReady(false);
    setView(null);
    setOutcome(null);
    devSim.current = false;
    setRunErr(null);
    if (id === "new") {
      history.replaceState(null, "", location.pathname);
      setRun(null);
      setLead(null);
      setSent(false);
      return;
    }
    clearPhoto();
    clearHearing();
    setSent(true);
    setLead(null);
    // Asked, not read from the picker's list: that list is empty on a fresh page load and may be stale.
    const saved = await getLead(id).catch(() => null);
    // The lead has not spoken (or the agents server never saw this run): the run may still be processing. "queued" resumes polling the backend; the ear rows replay and the lead opens when they clear, as for a fresh run.
    if (!saved || saved.stage === "new") return setRun({ id, status: "queued" });
    // status "done": the run finished before its lead opened, so nothing polls the backend and no ear row replays.
    setRun({ id, status: "done" });
    void talk("", id);
  };
  keyFn.current = (e) => {
    // Chord: both held, either order. Not while typing — "12" in the chat box is a message, and repeat must not refire it.
    const typing = e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement;
    if (!e.repeat && !typing && held.current.has("1") && held.current.has("2")) return skipToLead();
    // 3 + 4: the same skip, then straight to a clickable orb, as if the patient had already agreed to launch research.
    if (!e.repeat && !typing && held.current.has("3") && held.current.has("4")) {
      skipToLead();
      devSim.current = true;
      return setSimReady(true);
    }
    // 5: the research view, as if research had just launched. Pressing 5 again closes it.
    if (e.key === "5" && !e.repeat && !typing) {
      if (panelOn) closePanel();
      flyDelay.current = sent && !panelOn ? 0 : 0.9;
      setSent(true);
      if (!lead) setLead({ line: RESEARCH_LINE, waiting: false });
      return setResearch((r) => !r);
    }
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
    <div style={{ background: fill, borderRadius: 20 }}>
      <MetalFx variant="button" preset="silver" theme="dark" innerShadow ringCssPx={2} borderRadius={20}>
        <button type="button" aria-label={aria} onClick={onClick} style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, height: 40, minWidth: 40, padding: label ? "0 24px" : 0, border: 0, borderRadius: 20, background: fill, color, cursor: "pointer", font: "inherit", fontSize: 16 }}>
          <svg viewBox="0 0 24 24" width="1.1em" height="1.1em" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{d.map((p) => <path key={p} d={p} />)}</svg>
          {label}
        </button>
      </MetalFx>
    </div>
  );

  return (
    <>
    {/* The up arrow is live only once BOTH ear photos AND a hearing test are attached; plus is inert. Width 600 approximates the dock's resting width — retune if the dock changes. */}
    {/* The ear stage's three views, revealed as the backend writes them; the orb's rect is where the stack lands. */}
    {/* Keyed on the run: switching sessions remounts the boxes, so one study's traces never show under another's. Key 5 with no run shows the dev patient's study. */}
    {research && <div ref={boxes}><ResearchBoxes key={run?.id} runId={run?.id ?? DEV_RUN_ID} origin={() => orb.current?.getBoundingClientRect() ?? null} delay={flyDelay.current} nodes={orbNodes} /></div>}
    {/* Three rows — left ear on top, the head (face) in the MIDDLE, right ear at the bottom — each revealing its OWN files as the backend writes them. They close together (rowsSettled); the lead opens once they are gone (see headComing). */}
    {run && (["left", "right"] as const).map((ear) => (
      <EarViews key={`${run.id}:${ear}`} {...rowProps(ear)} label={`${ear === "left" ? "Left" : "Right"} ear`} testid={`ear-row-${ear}`} y={earRows().ys[ear === "left" ? 0 : 2]} size={earRows().size} files={run.files?.[ear]} anchor={() => orb.current?.getBoundingClientRect() ?? null}
        onGone={() => setGoneRows((g) => [...g, `${run.id}:${ear}`])} />
    ))}
    {/* Keyed on the view count: EarViews measures its width ONCE, so a row that drops the face view must remount. Unmounted once the lead talks — a head that never finished must not pop up mid-conversation. */}
    {run && !lead && (
      <EarViews key={`${run.id}:head:${headViews.length}`} {...rowProps("head")} label="Head" testid="ear-row-head" views={headViews} y={earRows().ys[1]} size={earRows().size} files={head} anchor={() => orb.current?.getBoundingClientRect() ?? null}
        onGone={() => setGoneRows((g) => [...g, `${run.id}:head`])} />
    )}
    <div ref={chat} style={{ position: "fixed", top: "50%", left: "50%", transform: "translate(-50%, -50%)", width: 600, maxWidth: "calc(100vw - 32px)", zIndex: 10 }}>
    {/* Orb draws at full resolution (components/Orb.tsx), so size is plain pixels. zIndex -1 sits behind the card and bar inside this wrapper's stacking context. The inner div carries the post-send y/scale tween, so GSAP NEVER rewrites the centering translate on the outer one. */}
    <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", zIndex: -1, pointerEvents: "none" }}>
      {/* Clickable ONLY once the simulation is ready and not already zoomed; the wrapper above stays click-through so the card under the orb's padding still works. */}
      <div ref={orb} data-testid="orb" data-state={orbState} data-zoomed={zoomed || undefined}
        {...(simReady && !zoomed ? { role: "button", tabIndex: 0, "aria-label": "Start simulation", onKeyDown: (e: React.KeyboardEvent) => (e.key === "Enter" || e.key === " ") && setZoomed(true) } : {})}
        // A drag past 4px is a spin, NEVER a click — otherwise every spin of a ready orb would also zoom in.
        onClick={() => simReady && !dragged.current && setZoomed(true)}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          gsap.killTweensOf(spin.current);
          drag.current = { x: e.clientX, t: performance.now(), v: 0, dist: 0 };
          dragged.current = false;
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          const dx = e.clientX - d.x, now = performance.now();
          // One sphere radius of drag is one radian, so the front face tracks the pointer.
          spin.current.a += dx / ((ORB_PX * ORB_FILL) / 2);
          d.v = dx / Math.max(1, now - d.t);
          d.dist += Math.abs(dx);
          d.x = e.clientX;
          d.t = now;
          if (d.dist > 4) dragged.current = true;
        }}
        onPointerUp={() => {
          const d = drag.current;
          drag.current = null;
          // Coast on release like a flicked ball: ~300ms worth of the last velocity, easing out.
          if (d && dragged.current) gsap.to(spin.current, { a: spin.current.a + (d.v * 300) / ((ORB_PX * ORB_FILL) / 2), duration: 1.2, ease: "power2.out" });
        }}
        onPointerCancel={() => (drag.current = null)}
        // Draggable whenever the orb is out from behind the card; the click-through wrapper above keeps the card usable under the orb's padding.
        style={{ position: "relative", pointerEvents: orbState !== "idle" && !zoomed ? "auto" : "none", cursor: simReady ? "pointer" : "grab", borderRadius: "50%", touchAction: "none", userSelect: "none" }}>
        <Orb px={ORB_PX} speed={orbState === "idle" ? 1 : 2} spin={spin.current} nodes={orbNodes} />
        {/* Sits under the visible sphere (canvas is ORB_FILL sphere + padding) and scales with the orb. Colour and font match the Capture Ear pill label (pill() default colour), one size up; dividing by --orb-s undoes the orb's scale so it stays 18px on short screens. */}
        {!zoomed && (lead ? orbState !== "idle" : orbState === "loading" && !rowsOnScreen) && <div role="status" className={lead ? "orb-sub orb-sub-still" : "orb-sub"} style={{ position: "absolute", left: 0, right: 0, textAlign: "center", ...(lead
          // The lead's reply is a band from the sphere's bottom to the Capture pills' top (--orb-sub-h, set with the orb's layout), its text centered vertically in it.
          ? { top: (ORB_PX * (1 + ORB_FILL)) / 2, height: "var(--orb-sub-h)", display: "flex", alignItems: "center", justifyContent: "center" }
          : { top: (ORB_PX * (1 + ORB_FILL)) / 2 + 28 }), fontSize: "calc(18px / var(--orb-s, 1))", lineHeight: "calc(22px / var(--orb-s, 1))", color: "#757575" }}>{lead ? (lead.waiting ? "…" : lead.line) : "Processing…"}</div>}
      </div>
    </div>
    {/* Bar floats above the card (bottom: 100%) so the card stays centered, and hugs its content. While a panel (camera or hearing) is open the bar joins the flow instead, so the wrapper (centered by its translate) re-centers feed + card together and the card is pushed down. Inert until capture is wired. Grey matches the textarea placeholder. */}
    <div ref={bar} inert={zoomed} style={panelOn ? { display: "flex", justifyContent: "center" } : { position: "absolute", bottom: "100%", left: 0, right: 0, marginBottom: 12, display: "flex", justifyContent: "center", gap: 10 }}>
      {!panelOn && (
        <>
          {pill(openCam, ["M4 8h3l2-3h6l2 3h3v11H4z", "M12 10a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z"], camErr ?? "Capture Ears & Face", camErr ? "#f87171" : undefined)}
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
            {/* Which ear the next shot fills — the slot IS the side the backend is told. */}
            <span data-testid="cam-ear" style={{ position: "absolute", top: 14, left: 14, padding: "3px 10px", borderRadius: 999, background: "rgba(0,0,0,0.55)", color: "#e6e8eb", fontSize: 13 }}>{SLOT_NAME[nextSlot ?? "left"]}</span>
            <button type="button" aria-label="Close camera" onClick={closePanel} style={{ position: "absolute", top: 12, right: 12, width: 32, height: 32, borderRadius: 999, border: 0, background: "rgba(0,0,0,0.55)", color: "#e6e8eb", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg viewBox="0 0 24 24" {...icon}><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
            {nextSlot && (
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
      ref={card}
      inert={zoomed}
      data-testid="drop-zone"
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) setDragging(true); }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false); }}
      onDrop={(e) => { setDragging(false); addFiles(e.dataTransfer.files); }}
      style={{ background: fill, borderRadius: 24, outline: dragging ? "2px dashed #757575" : "none", outlineOffset: 4 }}
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
        if (!photos.left || !photos.right || !hearing || busy) return;
        const ta = e.currentTarget.elements.namedItem("msg") as HTMLTextAreaElement;
        setStarting(true);
        setRunErr(null);
        try {
          const started = await startRun(photos as Record<Ear, EarPhoto> & { selfie?: EarPhoto }, hearing.result);
          setRun(started);
          // Every run is its own session from the start, so the picker can leave it mid-processing and come back. The agents server being down must not fail the run.
          void createSession(started.id).then(refreshSessions, () => {});
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
      style={{ boxSizing: "border-box", width: "100%", padding: 14, borderRadius: 24, background: fill }}
    >
      {(SLOTS.some((s) => photos[s]) || hearing) && <div style={{ display: "flex", gap: 10 }}>
      {SLOTS.map((ear) => photos[ear] && (
        <div key={ear} data-testid={`attachment-${ear}`} style={{ position: "relative", width: 64, height: 64, margin: "0 6px 8px" }}>
          <img src={photos[ear]!.url} alt={`${SLOT_NAME[ear]} photo`} style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 12, transform: photos[ear]!.mirror ? "scaleX(-1)" : undefined }} />
          {/* The slot's letter: which ear (or the face) the backend is told this photo is. */}
          <span style={{ position: "absolute", left: 4, bottom: 4, minWidth: 18, height: 18, borderRadius: 999, background: "rgba(0,0,0,0.7)", color: "#e6e8eb", fontSize: 11, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center" }}>{({ left: "L", right: "R", selfie: "F" } as const)[ear]}</span>
          <button type="button" aria-label={`Remove ${ear === "selfie" ? "face" : `${ear} ear`} photo`} onClick={() => clearPhoto(ear)} style={{ position: "absolute", top: -6, right: -6, width: 20, height: 20, padding: 0, borderRadius: 999, border: 0, background: "#3b3d42", color: "#e6e8eb", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
      ))}
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
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {/* ponytail: display only — nothing reads the choice; the agents server picks its models from agents/.env. */}
        <select aria-label="Model" data-testid="model-picker" defaultValue="Opus 5.5"
          style={{ padding: "4px 10px", borderRadius: 999, border: 0, outline: 0, background: "transparent", color: "#9aa0a8", font: "inherit", fontSize: 13, cursor: "pointer" }}>
          {["Fable 5.2", "Opus 5.5", "Haiku 5.5"].map((m) => <option key={m} style={{ background: "#000" }}>{m}</option>)}
        </select>
        <button type="submit" aria-label="Send" disabled={!canSend} title={lead ? (canSend ? undefined : "Waiting for a reply") : canSend ? (photos.selfie ? undefined : `Send, or ${faceHint}`) : `Add both ear photos and a hearing test to start; ${faceHint}`} style={{ ...iconBtn, border: 0, background: "#3b82f6", color: "#fff", opacity: canSend ? 1 : 0.35, cursor: canSend ? "pointer" : "not-allowed" }}>
          <svg viewBox="0 0 24 24" {...icon}><path d="M12 19V5M5 12l7-7 7 7" /></svg>
        </button>
        </div>
      </div>
    </form>
    </MetalFx>
    {/* Session picker, centered under the card in the BOTTOM gap (64px) — absolutely placed so the card's centering and drop never count it. */}
    <div style={{ position: "absolute", top: "100%", left: 0, right: 0, marginTop: 10, display: "flex", justifyContent: "center", alignItems: "center", gap: 10 }}>
    <select aria-label="Session" data-testid="session-picker" value={run ? run.id : "new"} onChange={(e) => void openSession(e.target.value)}
      style={{ minWidth: 0, padding: "4px 10px", borderRadius: 999, border: "1px solid rgba(255,255,255,0.18)", background: "#000", color: "#9aa0a8", font: "inherit", fontSize: 13, cursor: "pointer" }}>
      <option value="new">New session</option>
      {sessionsErr && <option disabled value="">Saved sessions unavailable: {sessionsErr}</option>}
      {/* The open run is listed even before the session list catches up with it. */}
      {run && !sessions.some((x) => x.run_id === run.id) && <option value={run.id}>Current session</option>}
      {sessions.map((x) => <option key={x.run_id} value={x.run_id}>{sessionLabel(x)}</option>)}
    </select>
    {/* The session's ID, the same one in the address bar; a click copies the link that reopens it. */}
    {run && (
      <button type="button" data-testid="session-id" title="Copy link to this session" onClick={() => void navigator.clipboard?.writeText(location.href)}
        style={{ padding: 0, border: 0, background: "transparent", color: "#5c5f66", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12, cursor: "copy" }}>{run.id}</button>
    )}
    </div>
    </div>
    </div>
    {/* Inside the orb: one bento box per speaker direction, left and right ear side by side (components/WaveBento), gain panel on the right. Mounted ONLY once the zoom lands (see inside) — ten wave viewers loading at once stall the main thread, and mid-zoom that freezes the zoom. The top padding keeps the header clear of the X. */}
    {/* The lead's simulations mount as soon as they exist and STAY mounted (hidden) outside the orb: the workers run in the background, and closing the orb must not restart them. */}
    {run && view?.scenes?.length ? (
      <div ref={simWrap} data-testid="sims" style={{ position: "fixed", inset: 0, zIndex: 25, overflow: "auto", paddingTop: 56, opacity: 0, display: inside ? "block" : "none" }}>
        <SimRuns pid={run.id} ear={view.ear} scenes={view.scenes} gain={aidGain ?? undefined} aidUrl={aidGain && view.picked ? designFile(run.id, view.picked, "earpiece.glb", view.ear ?? undefined) : undefined} onDone={setOutcome} />
      </div>
    ) : inside && run && (
      <div ref={simWrap} data-testid="sims" style={{ position: "fixed", inset: 0, zIndex: 25, overflow: "auto", paddingTop: 56, opacity: 0 }}>
        <WaveBento run={run} />
      </div>
    )}
    {/* `arrived`: the cards fade in ONLY once the orb has settled — mounted earlier they showed before it and were measured against a moving orb. */}
    {run && view?.stage === "options" && view.options && arrived && (
      <AidOptions runId={run.id} ear={view.ear} options={view.options} around={orbSphere} onPick={async (id) => { await step("picked", { design_id: id }); setZoomed(true); }} />
    )}
    {zoomed && (
      <button type="button" aria-label="Exit simulation" onClick={exitSim} style={{ position: "fixed", top: 20, left: 20, zIndex: 30, ...iconBtn, width: 40, height: 40, border: "1px solid rgba(255,255,255,0.18)", background: "rgba(0,0,0,0.55)", color: "#e6e8eb" }}>
        <svg viewBox="0 0 24 24" {...icon}><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    )}
    {/* The dock positions itself against its nearest positioned parent, so this fixed strip is the "top of the screen". It is click-through; the dock opts back in. */}
    <div ref={dockWrap} inert={zoomed} style={{ position: "fixed", top: 0, left: 0, right: 0, height: 140, zIndex: 20, pointerEvents: "none" }}>
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
