"use client";

import { useEffect, useRef, useState } from "react";
import { CALIBRATION_ID, PLAN, levelOf, newTrack, respond, toGain, type Ear, type Result } from "@/lib/audiometry";

/** Standard medical red flags (specs/01a § Safety questions). A "yes" ends the test with a referral, NEVER with results — a passive earpiece is the wrong answer for any of them. */
const RED_FLAGS = [
  "A sudden change in your hearing in the last 30 days",
  "Ear pain, discharge or bleeding",
  "Ringing or hearing loss in one ear only",
  "Dizziness with a change in hearing",
];

const btn = { height: 36, padding: "0 16px", borderRadius: 18, font: "inherit", fontSize: 14, cursor: "pointer" } as const;

/** In-app pure-tone screening inside the Capture Hearing panel (app/dashboard/Dashboard.tsx owns the panel animation). Procedure and flags live in lib/audiometry.ts; this file only plays tones and collects presses. */
export default function HearingTest({ onDone, onClose }: { onDone: (r: Result) => void; onClose: () => void }) {
  const [phase, setPhase] = useState<"intro" | "refer" | "run">("intro");
  const [step, setStep] = useState(0);
  const [flash, setFlash] = useState(false);
  const heard = useRef<HTMLButtonElement>(null);
  const pressed = useRef(false);
  // The run loop must NOT restart when the parent re-renders with a new onDone closure.
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });

  const press = () => {
    pressed.current = true;
    setFlash(true);
    setTimeout(() => setFlash(false), 150);
  };

  useEffect(() => {
    if (phase !== "run") return;
    let cancelled = false;
    const ac = new AudioContext();
    // Test hook: e2e/hearing.spec.ts shrinks every gap, window and pulse so a full test runs in seconds.
    const S = (window as unknown as { __hearingSpeed?: number }).__hearingSpeed ?? 1;
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms * S));
    // data-live/level/trial on the button let a scripted listener (Playwright) answer like a patient. Set on the DOM directly — a state round-trip could land after the response window closes.
    const mark = (live: string, level = "") => {
      const b = heard.current;
      if (!b) return;
      b.dataset.live = live;
      b.dataset.level = level;
      b.dataset.trial = String(Number(b.dataset.trial ?? 0) + 1);
    };
    // Two 150 ms pulses with 20 ms ramps — a hard on/off clicks, and the click is audible far below the tone's own threshold.
    const tone = (freq: number, ear: Ear, hl: number) => {
      const osc = new OscillatorNode(ac, { frequency: freq });
      const g = new GainNode(ac, { gain: 0 });
      const pan = new StereoPannerNode(ac, { pan: ear === "right" ? 1 : -1 });
      osc.connect(g).connect(pan).connect(ac.destination);
      const a = toGain(freq, hl), t = ac.currentTime + 0.02;
      for (let k = 0; k < 2; k++) {
        const t0 = t + k * 0.25 * S;
        g.gain.setValueAtTime(0, t0);
        g.gain.linearRampToValueAtTime(a, t0 + 0.02 * S);
        g.gain.setValueAtTime(a, t0 + 0.13 * S);
        g.gain.linearRampToValueAtTime(0, t0 + 0.15 * S);
      }
      osc.start(t);
      osc.stop(t + 0.5 * S);
    };
    // Response window: the tone (0.4 s) plus 0.6 s — a normal reaction is 0.3–0.5 s. Presses outside a window are ignored.
    const listen = async (play?: () => void) => {
      pressed.current = false;
      play?.();
      const end = performance.now() + 1000 * S;
      while (!pressed.current && !cancelled && performance.now() < end) await new Promise((r) => setTimeout(r, 10));
      mark("");
      return pressed.current;
    };
    (async () => {
      await ac.resume();
      const t0 = Date.now();
      const r: Result = { thresholds: { right: {}, left: {} }, catches: { presented: 0, falseAlarms: 0 }, date: new Date().toISOString().slice(0, 10), durationS: 0, calibration: CALIBRATION_ID };
      for (let i = 0; i < PLAN.length; i++) {
        const { ear, freq } = PLAN[i];
        setStep(i);
        if (heard.current) Object.assign(heard.current.dataset, { ear, freq: String(freq) });
        let t = newTrack();
        while (t.result === undefined) {
          // Random gap so the patient cannot press on rhythm instead of on sound.
          await sleep(200 + Math.random() * 400);
          if (cancelled) return;
          // Silent catch trial (~1 in 12): a press here is a false alarm, reported in the PDF.
          if (Math.random() < 1 / 12) {
            mark("silent");
            r.catches.presented++;
            if (await listen()) r.catches.falseAlarms++;
            continue;
          }
          const level = levelOf(t);
          mark("tone", String(level));
          t = respond(t, await listen(() => tone(freq, ear, level)));
          if (cancelled) return;
        }
        r.thresholds[ear][freq] = t.result;
      }
      r.durationS = Math.round((Date.now() - t0) / 1000);
      done.current(r);
    })();
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      e.preventDefault();
      press();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      cancelled = true;
      window.removeEventListener("keydown", onKey);
      ac.close();
    };
  }, [phase]);

  const { ear, freq } = PLAN[step];
  return (
    <div style={{ position: "relative", height: "100%", color: "#c9ccd1", fontSize: 14 }}>
      <button type="button" aria-label="Close hearing test" onClick={onClose} style={{ position: "absolute", top: 12, right: 12, width: 32, height: 32, borderRadius: 999, border: 0, background: "rgba(255,255,255,0.08)", color: "#e6e8eb", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1 }}>
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
      {phase === "intro" && (
        <div style={{ height: "100%", boxSizing: "border-box", padding: "18px 22px", overflowY: "auto" }}>
          <div style={{ fontSize: 16, color: "#e6e8eb", marginBottom: 6 }}>Before you start</div>
          <div>See a doctor instead if any of these apply:</div>
          <ul style={{ margin: "6px 0 10px", paddingLeft: 18, lineHeight: 1.5 }}>
            {RED_FLAGS.map((f) => <li key={f}>{f}</li>)}
          </ul>
          <div style={{ lineHeight: 1.5 }}>Wear headphones, set the volume to 50% and find a quiet room. Press the button or Space every time you hear a beep, even a faint one. About 30 seconds.</div>
          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <button type="button" onClick={() => setPhase("refer")} style={{ ...btn, border: "1px solid rgba(255,255,255,0.18)", background: "transparent", color: "#c9ccd1" }}>One of these applies</button>
            <button type="button" onClick={() => setPhase("run")} style={{ ...btn, border: 0, background: "#3b82f6", color: "#fff" }}>Start test</button>
          </div>
        </div>
      )}
      {phase === "refer" && (
        <div style={{ height: "100%", boxSizing: "border-box", padding: "18px 22px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 8, lineHeight: 1.5 }}>
          <div style={{ fontSize: 16, color: "#e6e8eb" }}>Please see a doctor first</div>
          <div>These signs need a medical check before any hearing device. A sudden change in hearing needs care within 72 hours.</div>
        </div>
      )}
      {phase === "run" && (
        <div style={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14 }}>
          <div style={{ color: "#e6e8eb", fontSize: 16 }}>{ear === "right" ? "Right" : "Left"} ear · {freq >= 1000 ? `${freq / 1000} kHz` : `${freq} Hz`}</div>
          <div style={{ width: 200, height: 4, borderRadius: 2, background: "rgba(255,255,255,0.12)" }}>
            <div style={{ width: `${(step / PLAN.length) * 100}%`, height: "100%", borderRadius: 2, background: "#3b82f6", transition: "width 0.3s" }} />
          </div>
          <button ref={heard} type="button" aria-label="Heard beep" onClick={press} style={{ width: 72, height: 72, padding: 0, borderRadius: 999, border: "3px solid #fff", background: "rgba(255,255,255,0.85)", boxShadow: "0 0 0 3px rgba(0,0,0,0.35) inset", cursor: "pointer", transform: flash ? "scale(0.9)" : "none", transition: "transform 0.12s" }} />
          <div style={{ fontSize: 13, color: "#757575" }}>Press when you hear a beep (or Space)</div>
        </div>
      )}
    </div>
  );
}
