"use client";
// A scene's sound clip through the simulation: what reaches the eardrum over time, how much of it this ear
// hears, and the wave field the clip makes. Level convention as hornsim/scoring.py: a clip with RMS 1 is
// its source's level_db dB SPL, and the direction gain (wave sim, re frontal) shifts each SII band.
//
// The field: a head run's frames are the response to an incident plane click c = σ·G′ (headFdtd.ts, G a Gaussian
// with σ = 25 µs). Their running sum over time is the response to G itself, and G is narrower than one audio
// sample, so linear acoustics gives the field for any clip u as Σ_k cum_k · u(t − kΔ). Summing the frames FIRST
// matters: c integrates to zero, and convolving its coarsely sampled frames (Δ ≈ 0.6σ) with ∫u leaves only
// sampling error. G rolls off the top bands a little (−1.7 dB at 4 kHz, −7 dB at 8 kHz): display only.
import { useEffect, useState } from "react";
import { hearingLevel, sii, siiTerms, SII_FREQS, type Audiogram } from "./hearing";

export const SR = 24000;            // covers the top SII band (8 kHz, upper edge 8.98 kHz)
export const WIN = 1024, HOP = 512; // 43 ms Hann frames every 21 ms
const NB = SII_FREQS.length;
const BW = SII_FREQS.map((f) => f * (2 ** (1 / 6) - 2 ** (-1 / 6)));
export const CLIPS = ["clean_1", "clean_2", "clean_3"] as const;

export type ClipSrc = { role: "talker" | "babble"; levelDb: number; gainDb: number[]; clip: string; x: Float32Array };
export type Cond = "healthy" | "you" | "aided";
export type ClipAnalysis = {
  srcs: ClipSrc[]; n: number; duration: number; frames: number;
  /** short-time SII per frame, 0–1 */
  sii: Record<Cond, number[] | undefined>;
  /** audibility E′−D per frame and band, −15 (nothing) .. +15 dB (all) */
  aud: Record<Cond, number[][] | undefined>;
  /** the talkers' mix at the speaker (RMS 1), for the timeline's waveform */
  talk: Float32Array;
};

/** In-place radix-2 FFT; length a power of two. */
export function fft(re: Float64Array, im: Float64Array, inverse = false) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = ((inverse ? 2 : -2) * Math.PI) / len, wr = Math.cos(ang), wi = Math.sin(ang), h = len >> 1;
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < h; k++) {
        const a = i + k, b = a + h;
        const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
        const nc = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nc;
      }
    }
  }
  if (inverse) for (let i = 0; i < n; i++) { re[i] /= n; im[i] /= n; }
}

const decoded = new Map<string, Promise<Float32Array>>();
/** A clip from public/sim/clips (backend/assets/speech), mono at SR, scaled to RMS 1. */
export function loadClip(name: string) {
  let p = decoded.get(name);
  if (!p) {
    // "bank:<label>" is the backend's sound bank (GET /api/sim/sounds/{label}); anything else a speech clip in public/sim/clips
    p = fetch(name.startsWith("bank:") ? `/api/sim/sounds/${encodeURIComponent(name.slice(5))}` : `/sim/clips/${name}.wav`)
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`clip ${name}: HTTP ${r.status}`))))
      .then((b) => new OfflineAudioContext(1, 1, SR).decodeAudioData(b))
      .then((buf) => {
        const x = Float32Array.from(buf.getChannelData(0));
        const rms = Math.sqrt(x.reduce((s, v) => s + v * v, 0) / x.length) || 1;
        for (let i = 0; i < x.length; i++) x[i] /= rms;
        return x;
      });
    decoded.set(name, p);
    p.catch(() => decoded.delete(name));
  }
  return p;
}

/** A source with a bank `sound` plays that clip. Otherwise talkers take `talkerClip` (the first of them) then cycle the
 * clean speech clips, and babble cycles the babble noise. */
export function clipNames(sources: { role: ClipSrc["role"]; sound?: string }[], talkerClip?: string) {
  let t = 0, b = 0;
  return sources.map(({ role: r, sound }) => (sound ? `bank:${sound}` : r === "talker" ? (t++ === 0 && talkerClip ? talkerClip : CLIPS[(t - 1) % 3]) : `babble_${(b++ % 4) + 1}_noise`));
}

/** A clip's long-term level per SII band (dB/Hz) at 0 dB overall — the SAME band powers analyse() takes per frame, power-
 * averaged over the whole clip. speechBands adds the source's level_db, so a scene scores the sound that actually plays. */
export function bandShape(x: Float32Array): number[] {
  const frames = Math.max(1, Math.floor((x.length - WIN) / HOP) + 1);
  const hann = Float64Array.from({ length: WIN }, (_, i) => 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / WIN));
  const norm = 2 / (WIN * hann.reduce((s, w) => s + w * w, 0));
  const band = bandOfBin(WIN), P = new Float64Array(NB), re = new Float64Array(WIN), im = new Float64Array(WIN);
  for (let f = 0; f < frames; f++) {
    for (let i = 0; i < WIN; i++) { re[i] = at(x, f * HOP + i) * hann[i]; im[i] = 0; }
    fft(re, im);
    for (let k = 0; k <= WIN / 2; k++) if (band[k] >= 0) P[band[k]] += ((re[k] ** 2 + im[k] ** 2) * norm) / frames;
  }
  return Array.from(P, (p, b) => (p > 0 ? 10 * Math.log10(p / BW[b]) : -100));
}

const shapes = new Map<string, Promise<number[]>>();
/** Per scene, per source: its clip's bandShape, null until the clips have loaded (tiles score only once they have). */
export function useClipShapes(scenes: { sources: { role: ClipSrc["role"]; sound?: string }[] }[]) {
  const [got, setGot] = useState<Record<string, number[]>>({});
  const names = scenes.map((s) => clipNames(s.sources));
  const key = [...new Set(names.flat())].sort().join("|");
  useEffect(() => {
    let live = true;
    for (const n of key.split("|").filter(Boolean)) {
      if (!shapes.has(n)) shapes.set(n, loadClip(n).then(bandShape));
      shapes.get(n)!.then((v) => live && setGot((g) => (g[n] ? g : { ...g, [n]: v })), () => shapes.delete(n));
    }
    return () => { live = false; };
  }, [key]);
  return names.map((ns) => ns.map((n) => got[n] ?? null));
}

/** Sample i of a source, looped (babble runs under the whole talker clip). */
const at = (x: Float32Array, i: number) => x[i % x.length];

function bandOfBin(N: number) {
  return Array.from({ length: N / 2 + 1 }, (_, k) => {
    const f = (k * SR) / N;
    return SII_FREQS.findIndex((c) => f >= c * 2 ** (-1 / 6) && f < c * 2 ** (1 / 6));
  });
}

/** Per-frame SII terms for a scene: the backend's _band_spectrum_levels on each 43 ms frame instead of the whole clip. */
export function analyse(srcs: ClipSrc[], ag: Audiogram, G?: number[]): ClipAnalysis {
  const talkers = srcs.filter((s) => s.role === "talker");
  // The scene lasts as long as what you want to hear. A target shorter than 1.5 s (a bark, a chirp) repeats under the
  // rest of the scene, up to 3 s, instead of cutting everything to a fraction of a second.
  const tMax = Math.max(...(talkers.length ? talkers : srcs).map((s) => s.x.length)), all = Math.max(...srcs.map((s) => s.x.length));
  const n = tMax < 1.5 * SR ? Math.max(Math.round(1.5 * SR), Math.min(all, 3 * SR)) : tMax;
  const frames = Math.max(1, Math.floor((n - WIN) / HOP) + 1);
  const hann = Float64Array.from({ length: WIN }, (_, i) => 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / WIN));
  const norm = 2 / (WIN * hann.reduce((s, w) => s + w * w, 0)); // one-sided: bins sum to the frame's mean square
  const band = bandOfBin(WIN);
  const Ep = Array.from({ length: frames }, () => new Float64Array(NB));
  const Np = srcs.some((s) => s.role === "babble") ? Array.from({ length: frames }, () => new Float64Array(NB)) : null;
  const re = new Float64Array(WIN), im = new Float64Array(WIN);
  for (const s of srcs) {
    const into = s.role === "talker" ? Ep : Np!;
    for (let f = 0; f < frames; f++) {
      for (let i = 0; i < WIN; i++) { re[i] = at(s.x, f * HOP + i) * hann[i]; im[i] = 0; }
      fft(re, im);
      const S = new Float64Array(NB);
      for (let k = 0; k <= WIN / 2; k++) if (band[k] >= 0) S[band[k]] += (re[k] ** 2 + im[k] ** 2) * norm;
      for (let b = 0; b < NB; b++) into[f][b] += S[b] * 10 ** ((s.levelDb + s.gainDb[b]) / 10) / BW[b];
    }
  }
  const db = (p: number) => (p > 0 ? 10 * Math.log10(p) : -100);
  const hl0 = SII_FREQS.map(() => 0), hl = hearingLevel(ag, SII_FREQS);
  const out: ClipAnalysis = { srcs, n, duration: n / SR, frames, sii: { healthy: [], you: [], aided: G ? [] : undefined }, aud: { healthy: [], you: [], aided: G ? [] : undefined }, talk: new Float32Array(n) };
  for (let f = 0; f < frames; f++) {
    const E = Array.from(Ep[f], db), N = Np ? Array.from(Np[f], db) : null;
    const conds: [Cond, number[], number[] | null, number[]][] = [["healthy", E, N, hl0], ["you", E, N, hl]];
    if (G) conds.push(["aided", E.map((e, b) => e + G[b]), N && N.map((x, b) => x + G[b]), hl]);
    for (const [c, e, nn, h] of conds) { out.aud[c]!.push(siiTerms(e, nn, h).aud); out.sii[c]!.push(sii(e, nn, h)); }
  }
  for (const s of talkers) { const a = 10 ** ((s.levelDb - 65) / 20); for (let i = 0; i < n; i++) out.talk[i] += a * at(s.x, i); }
  return out;
}

/** Gain in dB at frequency f from per-band values, linear on log f, held beyond the ends. */
function bandInterp(f: number, v: number[]) {
  if (f <= SII_FREQS[0]) return v[0];
  if (f >= SII_FREQS[NB - 1]) return v[NB - 1];
  const i = SII_FREQS.findIndex((c) => c >= f);
  const t = Math.log(f / SII_FREQS[i - 1]) / Math.log(SII_FREQS[i] / SII_FREQS[i - 1]);
  return v[i - 1] + t * (v[i] - v[i - 1]);
}

/** The scene as one ear hears it, mono at SR: each source filtered by its direction gain plus `extraDb` per band
 * (−HL for this ear: hearing loss as plain attenuation, a first approximation; +G with the aid), summed by level. */
export function renderMix(a: ClipAnalysis, extraDb: number[], delays?: (number | null)[]) {
  let N = 1;
  while (N < a.n) N <<= 1;
  const out = new Float32Array(a.n);
  const gain = new Float64Array(N / 2 + 1);
  for (const s of a.srcs) {
    const re = new Float64Array(N), im = new Float64Array(N);
    for (let i = 0; i < a.n; i++) re[i] = at(s.x, i);
    fft(re, im);
    const tot = s.gainDb.map((g, b) => g + extraDb[b]);
    for (let k = 0; k <= N / 2; k++) gain[k] = 10 ** (bandInterp(Math.max(1, (k * SR) / N), tot) / 20);
    for (let k = 0; k < N; k++) { const g = gain[k <= N / 2 ? k : N - k]; re[k] *= g; im[k] *= g; }
    fft(re, im, true);
    // `delays` (s per source): when the sound reaches THIS ear after the earlier one — the ITD, so the two channels of a
    // stereo render place the source as the head does (lib/twoEar.ts onsets)
    const amp = 10 ** ((s.levelDb - 65) / 20), d = Math.round((delays?.[a.srcs.indexOf(s)] ?? 0) * SR);
    for (let i = d; i < a.n; i++) out[i] += amp * re[i - d];
  }
  return out;
}

/** A source's clip looped to n samples (babble runs under the whole talker clip). */
export const looped = (x: Float32Array, n: number) => Float32Array.from({ length: n }, (_, i) => at(x, i));

/** x with everything below fc removed (a half-octave cosine ramp up to fc, no ringing), same length. */
export function highpass(x: Float32Array, fc: number) {
  let N = 1;
  while (N < x.length) N <<= 1;
  const re = new Float64Array(N), im = new Float64Array(N);
  for (let i = 0; i < x.length; i++) re[i] = x[i];
  fft(re, im);
  for (let k = 0; k < N; k++) {
    const f = (Math.min(k, N - k) * SR) / N, lo = fc / Math.SQRT2;
    const g = f >= fc ? 1 : f <= lo ? 0 : 0.5 - 0.5 * Math.cos((Math.PI * Math.log(f / lo)) / Math.log(fc / lo));
    re[k] *= g; im[k] *= g;
  }
  fft(re, im, true);
  return Float32Array.from(x, (_, i) => re[i]);
}

/** Running sum of a run's frames over time: the response to the Gaussian G instead of the click G′ (see top). */
export function cumulate(frames: Float32Array[]) {
  const out: Float32Array[] = [];
  let acc: Float32Array | null = null;
  for (const f of frames) { const nxt: Float32Array = acc ? Float32Array.from(f, (v, j) => v + acc![j]) : Float32Array.from(f); out.push(nxt); acc = nxt; }
  return out;
}

/** The click peaks 4σ = 100 µs after a run starts (lib/fdtd.ts click, headFdtd.ts clickTable): frame k holds the response
 * k·Δ − ONSET after it. The backend viewers' clocks (head_viewer.html, wave_viewer.html clockField) use the SAME rule. */
export const ONSET_S = 100e-6;

/** One source's run as the field needs it: its CUMULATED frames (cumulate), level and clip. */
export type FieldRun = { frames: Float32Array[]; a: number; U: Float32Array };
const sample = (U: Float32Array, t: number) => {
  const p = t * SR, i = Math.floor(p);
  if (i < 0 || i >= U.length - 1) return 0;
  return U[i] + (p - i) * (U[i + 1] - U[i]);
};

/** The slice's pressure at clip time t (s): Σ_sources a·Σ_k cum_k · u(t − k·step). `step` = seconds between frames. */
export function fieldAt(out: Float32Array, runs: FieldRun[], t: number, step: number) {
  out.fill(0);
  for (const r of runs) for (let k = 0; k < r.frames.length; k++) {
    const u = r.a * sample(r.U, t - k * step + ONSET_S);
    if (!u) continue;
    const f = r.frames[k];
    for (let j = 0; j < out.length; j++) out[j] += u * f[j];
  }
  return out;
}

/** The same sum at ONE slice cell (the eardrum receiver). */
export function pointAt(runs: FieldRun[], t: number, step: number, j: number) {
  let v = 0;
  for (const r of runs) for (let k = 0; k < r.frames.length; k++) v += r.a * sample(r.U, t - k * step + ONSET_S) * r.frames[k][j];
  return v;
}

/** The scene's clip analysis once every source has its direction gain; null until then. */
export function useClipAnalysis(sources: { role: ClipSrc["role"]; level_db: number; sound?: string }[], gains: (number[] | null)[] | null, ag: Audiogram | null, G?: number[], talkerClip?: string) {
  const [res, setRes] = useState<ClipAnalysis | null>(null);
  const key = JSON.stringify([sources.map((s) => [s.role, s.level_db, s.sound]), gains, ag, G, talkerClip]);
  useEffect(() => {
    if (!ag || !gains || gains.some((g) => !g)) return;
    let live = true;
    const names = clipNames(sources, talkerClip);
    Promise.all(names.map(loadClip)).then((xs) => {
      if (!live) return;
      const srcs = sources.map((s, i) => ({ role: s.role, levelDb: s.level_db, gainDb: gains[i]!, clip: names[i], x: xs[i] }));
      setRes(analyse(srcs, ag, G));
    }, () => {});
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return res;
}
