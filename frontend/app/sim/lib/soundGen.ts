"use client";
// Sounds for listening that are not speech, generated in the browser so nothing copyrighted ships with
// the app: an original four-bar EDM loop (128 BPM: kick on every beat, off-beat hats, a side-chained
// supersaw chord progression and a bass line) and road noise. For a real track, give a music source
// your own audio file ("use my audio"); it is decoded in the browser and never uploaded.

const BPM = 128;
const BEAT = 60 / BPM;
const BARS = 4;

/** An original EDM loop, mono, BARS bars at BPM. */
export async function renderEDM(sr: number): Promise<AudioBuffer> {
  const len = BARS * 4 * BEAT;
  const ctx = new OfflineAudioContext(1, Math.ceil(len * sr), sr);
  const out = ctx.createDynamicsCompressor();
  out.threshold.value = -10; out.ratio.value = 4;
  out.connect(ctx.destination);
  const noise = ctx.createBuffer(1, sr, sr);
  const nd = noise.getChannelData(0);
  for (let i = 0; i < nd.length; i++) nd[i] = Math.random() * 2 - 1;

  // chords (vi–IV–I–V in C: Am F C G), one per bar; root of each for the bass
  const chords = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]];
  const hz = (m: number) => 440 * 2 ** ((m - 69) / 12);
  const pad = ctx.createGain();
  const padLp = ctx.createBiquadFilter();
  padLp.type = "lowpass"; padLp.frequency.value = 2400; padLp.Q.value = 0.7;
  pad.connect(padLp).connect(out);

  for (let bar = 0; bar < BARS; bar++) {
    const t0 = bar * 4 * BEAT;
    for (const m of chords[bar]) for (const det of [-9, 0, 9]) {            // supersaw: three detuned saws per note
      const o = ctx.createOscillator();
      o.type = "sawtooth"; o.frequency.value = hz(m + 12); o.detune.value = det;
      const g = ctx.createGain(); g.gain.value = 0.018;
      o.connect(g).connect(pad);
      o.start(t0); o.stop(t0 + 4 * BEAT);
    }
    for (let b = 0; b < 4; b++) {
      const t = t0 + b * BEAT;
      // side-chain pump on the pad
      pad.gain.setValueAtTime(0.25, t);
      pad.gain.linearRampToValueAtTime(1, t + BEAT * 0.6);
      // kick: a sine falling from 150 to 45 Hz
      const k = ctx.createOscillator(), kg = ctx.createGain();
      k.frequency.setValueAtTime(150, t); k.frequency.exponentialRampToValueAtTime(45, t + 0.12);
      kg.gain.setValueAtTime(0.9, t); kg.gain.exponentialRampToValueAtTime(0.001, t + 0.35);
      k.connect(kg).connect(out); k.start(t); k.stop(t + 0.36);
      // off-beat hat: high-passed noise
      const h = ctx.createBufferSource(), hp = ctx.createBiquadFilter(), hg = ctx.createGain();
      h.buffer = noise; hp.type = "highpass"; hp.frequency.value = 7000;
      const th = t + BEAT / 2;
      hg.gain.setValueAtTime(0.12, th); hg.gain.exponentialRampToValueAtTime(0.001, th + 0.06);
      h.connect(hp).connect(hg).connect(out); h.start(th, Math.random() * 0.5, 0.08);
      // bass on the off-beat, the chord's root
      const bs = ctx.createOscillator(), bl = ctx.createBiquadFilter(), bg = ctx.createGain();
      bs.type = "sawtooth"; bs.frequency.value = hz(chords[bar][0] - 24);
      bl.type = "lowpass"; bl.frequency.value = 420;
      bg.gain.setValueAtTime(0.0001, th); bg.gain.exponentialRampToValueAtTime(0.35, th + 0.02); bg.gain.exponentialRampToValueAtTime(0.001, th + BEAT * 0.45);
      bs.connect(bl).connect(bg).connect(out); bs.start(th); bs.stop(th + BEAT * 0.5);
    }
  }
  return ctx.startRendering();
}

/** Road noise: low-passed brown noise with slow swells (cars passing), loopable. */
export async function renderTraffic(sr: number): Promise<AudioBuffer> {
  const len = 8;
  const ctx = new OfflineAudioContext(1, len * sr, sr);
  const buf = ctx.createBuffer(1, len * sr, sr), d = buf.getChannelData(0);
  let b = 0;
  for (let i = 0; i < d.length; i++) { b = (b + 0.02 * (Math.random() * 2 - 1)) / 1.02; d[i] = b * 3.5; }
  const src = ctx.createBufferSource(); src.buffer = buf;
  const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 900;
  const tyre = ctx.createBiquadFilter(); tyre.type = "peaking"; tyre.frequency.value = 1000; tyre.gain.value = 4; tyre.Q.value = 1;
  const g = ctx.createGain();
  for (const [t, v] of [[0, 0.5], [1.5, 1], [3, 0.55], [5, 1], [6.5, 0.6], [8, 0.5]] as const) g.gain.linearRampToValueAtTime(v, t);
  src.connect(lp).connect(tyre).connect(g).connect(ctx.destination);
  src.start();
  return ctx.startRendering();
}

/** Smoke alarm: the temporal-three pattern (three 0.5 s beeps, 1.5 s pause) of a ~3.1 kHz tone. */
export async function renderAlarm(sr: number): Promise<AudioBuffer> {
  const len = 4;
  const ctx = new OfflineAudioContext(1, len * sr, sr);
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = "square"; o.frequency.value = 3100;
  const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 7000;
  g.gain.value = 0;
  for (const t of [0, 1, 2]) { g.gain.setValueAtTime(0.25, t); g.gain.setValueAtTime(0, t + 0.5); }
  o.connect(lp).connect(g).connect(ctx.destination);
  o.start(); o.stop(len);
  return ctx.startRendering();
}

/** Birdsong: short frequency-swept chirps and trills between ~2.5 and 7 kHz at irregular times. */
export async function renderBirds(sr: number): Promise<AudioBuffer> {
  const len = 6;
  const ctx = new OfflineAudioContext(1, len * sr, sr);
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let t = 0.1; t < len - 0.4; t += 0.15 + rnd() * 0.6) {
    const n = 1 + Math.floor(rnd() * 4);                       // a trill of n notes
    for (let k = 0; k < n; k++) {
      const t0 = t + k * 0.09, f0 = 2500 + rnd() * 3000, f1 = f0 * (0.6 + rnd() * 0.9);
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.setValueAtTime(f0, t0); o.frequency.exponentialRampToValueAtTime(Math.min(7000, f1), t0 + 0.07);
      g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.2, t0 + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.08);
      o.connect(g).connect(ctx.destination); o.start(t0); o.stop(t0 + 0.09);
    }
  }
  return ctx.startRendering();
}
