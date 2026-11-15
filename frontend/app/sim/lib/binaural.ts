"use client";
// Listen to a scene the way the simulated head hears it. Each talker direction's FDTD run gives the
// pressure at both eardrums for a far plane wave (fdtd.worker.ts `transfer`): a head-related transfer
// function from THIS patient's head and ears, with the interaural time and level differences in it.
// A speech clip played through the left and right responses over headphones sounds like it comes from
// that direction. On top, per ear: the patient's audiogram as attenuation (unaided) and the designed
// earpiece's insertion gain (aided).
//
// Equalisation: the responses are divided by the mean of the two ears' FRONTAL magnitude, so the
// canal resonance the eardrum sees (your own ears add theirs on playback) is taken out once, while the
// differences between directions and between the ears stay. Hearing loss as plain attenuation is a
// first approximation: it reproduces audibility, not recruitment or loss of frequency resolution.
import { CLICK_SIGMA } from "./fdtd";
import { hearingLevel, SII_FREQS, type Audiogram } from "./hearing";
import { dirKey, type Source } from "./scenes";
import { renderAlarm, renderBirds, renderEDM, renderTraffic } from "./soundGen";

export const AUDIO_SR = 48000;
export const AUDIO_N = 512;          // FIR length: 10.7 ms holds the head's delays and the eardrum ring
export const TF_MAX_HZ = 12000;      // the click's usable band (CLICK_SIGMA); faded out above 10 kHz
const FADE_FROM_HZ = 10000;

export type EarTF = { left: { re: Float32Array; im: Float32Array }; right: { re: Float32Array; im: Float32Array } };
export type Condition = "healthy" | "unaided" | "aided";

/** Eardrum pressure over the incident plane wave, H(f) = P_ear(f) / P_click(f), on the bins of an AUDIO_N-point
 * FFT at AUDIO_SR, up to TF_MAX_HZ (the click still has energy there; above it H is left at 0). Both ears share
 * the run's time base, so the delay between them (the ITD) is in the phase. Runs in the FDTD worker. */
export function transfer(trace: Float32Array, dt: number) {
  const nb = AUDIO_N / 2 + 1, re = new Float32Array(nb), im = new Float32Array(nb);
  const n = trace.length, click = new Float64Array(n);
  for (let t = 0; t < n; t++) { const tt = t * dt - 4 * CLICK_SIGMA; click[t] = (-tt / CLICK_SIGMA) * Math.exp(-(tt * tt) / (2 * CLICK_SIGMA * CLICK_SIGMA)); }
  for (let k = 1; k < nb; k++) {
    const fHz = (k * AUDIO_SR) / AUDIO_N;
    if (fHz > TF_MAX_HZ) break;
    const w = 2 * Math.PI * fHz * dt;
    let pr = 0, pi = 0, cr = 0, ci = 0;
    for (let t = 0; t < n; t++) {
      const c = Math.cos(w * t), s = Math.sin(w * t);
      pr += trace[t] * c; pi -= trace[t] * s;
      cr += click[t] * c; ci -= click[t] * s;
    }
    const den = cr * cr + ci * ci || 1e-30;            // (pr + i pi) / (cr + i ci)
    re[k] = (pr * cr + pi * ci) / den;
    im[k] = (pi * cr - pr * ci) / den;
  }
  return { re, im };
}

/** Gain in dB at f from per-SII-band values, linear in log f, flat beyond the ends. */
function bandDb(db: number[], f: number) {
  if (f <= SII_FREQS[0]) return db[0];
  const n = SII_FREQS.length;
  if (f >= SII_FREQS[n - 1]) return db[n - 1];
  let i = 1;
  while (SII_FREQS[i] < f) i++;
  const t = (Math.log(f) - Math.log(SII_FREQS[i - 1])) / (Math.log(SII_FREQS[i]) - Math.log(SII_FREQS[i - 1]));
  return db[i - 1] + t * (db[i] - db[i - 1]);
}

/** Stereo impulse response for one direction: tf over the frontal reference, times each ear's band gain (dB). */
export function impulseResponse(ctx: BaseAudioContext, tf: EarTF, ref: EarTF, gainDb: Record<"left" | "right", number[]>) {
  const nb = AUDIO_N / 2 + 1, buf = ctx.createBuffer(2, AUDIO_N, AUDIO_SR);
  const refMag = new Float32Array(nb);
  for (let k = 0; k < nb; k++) refMag[k] = (Math.hypot(ref.left.re[k], ref.left.im[k]) + Math.hypot(ref.right.re[k], ref.right.im[k])) / 2;
  let floor = 0;
  for (let k = 0; k < nb; k++) floor = Math.max(floor, refMag[k]);
  floor *= 1e-3;
  (["left", "right"] as const).forEach((ear, ch) => {
    const re = new Float64Array(nb), im = new Float64Array(nb);
    for (let k = 1; k < nb; k++) {
      const f = (k * AUDIO_SR) / AUDIO_N;
      if (f > TF_MAX_HZ) break;
      const fade = f <= FADE_FROM_HZ ? 1 : 0.5 * (1 + Math.cos((Math.PI * (f - FADE_FROM_HZ)) / (TF_MAX_HZ - FADE_FROM_HZ)));
      const g = (fade * 10 ** (bandDb(gainDb[ear], f) / 20)) / Math.max(refMag[k], floor);
      re[k] = tf[ear].re[k] * g;
      im[k] = tf[ear].im[k] * g;
    }
    // inverse real DFT (N is small; direct sum keeps this dependency-free)
    const out = buf.getChannelData(ch);
    for (let n = 0; n < AUDIO_N; n++) {
      let s = re[0];
      for (let k = 1; k < nb - 1; k++) { const a = (2 * Math.PI * k * n) / AUDIO_N; s += 2 * (re[k] * Math.cos(a) - im[k] * Math.sin(a)); }
      s += re[nb - 1] * Math.cos(Math.PI * n);
      out[n] = s / AUDIO_N;
    }
    for (let n = AUDIO_N - 64; n < AUDIO_N; n++) out[n] *= 0.5 * (1 + Math.cos((Math.PI * (n - (AUDIO_N - 64))) / 64));   // no wrap-around click
  });
  return buf;
}

/** Per-ear band gains (dB) for a listening condition. */
export function conditionGains(cond: Condition, ag: Record<"left" | "right", Audiogram>, aid: Record<"left" | "right", number[] | undefined>) {
  const out = { left: SII_FREQS.map(() => 0), right: SII_FREQS.map(() => 0) };
  if (cond === "healthy") return out;
  for (const ear of ["left", "right"] as const) {
    const hl = hearingLevel(ag[ear], SII_FREQS);
    out[ear] = hl.map((h, i) => -h + (cond === "aided" ? aid[ear]?.[i] ?? 0 : 0));
  }
  return out;
}

/** Unit vector of a direction (az 0 front, 90 right; el up), for nearest-neighbour lookup. */
function vec(az: number, el: number) {
  const a = (az * Math.PI) / 180, e = (el * Math.PI) / 180;
  return [Math.cos(e) * Math.cos(a), Math.cos(e) * Math.sin(a), Math.sin(e)];
}

/** The simulated direction closest to (az, el): exact if it has run, else the nearest one that has. */
export function nearestTF(tfs: Record<string, EarTF>, az: number, el: number): { key: string; tf: EarTF } | null {
  const exact = dirKey(az, el);
  if (tfs[exact]) return { key: exact, tf: tfs[exact] };
  const v = vec(az, el);
  let best: string | null = null, bd = -2;
  for (const k of Object.keys(tfs)) {
    const [a, e] = k.split(",").map(Number), u = vec(a, e), d = u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
    if (d > bd) { bd = d; best = k; }
  }
  return best ? { key: best, tf: tfs[best] } : null;
}

/** What a source plays: your own file if given; else talkers cycle the clean speech clips, babble the
 * babble noise, music the generated EDM loop and traffic the generated road noise. */
export function clipFor(src: Source, index: number) {
  if (src.custom) return `url:${src.custom.url}`;
  if (src.role === "music") return "gen:edm";
  if (src.role === "traffic") return "gen:traffic";
  if (src.role === "alarm") return "gen:alarm";
  if (src.role === "birds") return "gen:birds";
  return src.role === "talker" ? `clean_${(index % 3) + 1}` : `babble_${(index % 4) + 1}_noise`;
}

/** Playback stays at a safe loudness: a scene whose loudest source is above SAFE_DB plays that much
 * quieter overall (the differences between sources are kept), and a limiter catches peaks. */
export const SAFE_DB = 75;
export const playbackOffsetDb = (sources: Source[]) => Math.max(0, Math.max(0, ...sources.map((s) => s.levelDb)) - SAFE_DB);

type Voice = { src: AudioBufferSourceNode; level: GainNode; conv: ConvolverNode; mix: GainNode; key: string; clip: string };

/** Plays one scene binaurally. update() follows source moves, level changes and condition changes; a
 * new direction crossfades over XFADE seconds so dragging a talker sweeps the sound around the head. */
export class ScenePlayer {
  private ctx: AudioContext;
  private master: GainNode;
  private voices = new Map<string, Voice>();
  private clips = new Map<string, Promise<AudioBuffer>>();
  private static XFADE = 0.06;
  private queue: Promise<void> = Promise.resolve();

  private clipUrl: (name: string) => string;

  constructor(clipUrl: (name: string) => string) {
    this.clipUrl = clipUrl;
    this.ctx = new AudioContext({ sampleRate: AUDIO_SR });
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.6;
    const limiter = this.ctx.createDynamicsCompressor();        // peaks from loud scenes and custom tracks
    limiter.threshold.value = -6; limiter.knee.value = 0; limiter.ratio.value = 20; limiter.attack.value = 0.003; limiter.release.value = 0.15;
    this.master.connect(limiter).connect(this.ctx.destination);
  }

  private clip(name: string) {
    let p = this.clips.get(name);
    if (!p) {
      const url = name.startsWith("url:") ? name.slice(4) : this.clipUrl(name);
      p = name === "gen:edm" ? renderEDM(AUDIO_SR) : name === "gen:traffic" ? renderTraffic(AUDIO_SR)
        : name === "gen:alarm" ? renderAlarm(AUDIO_SR) : name === "gen:birds" ? renderBirds(AUDIO_SR)
        : fetch(url).then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`clip ${name}: HTTP ${r.status}`)))).then((b) => this.ctx.decodeAudioData(b));
      this.clips.set(name, p);
      p.catch(() => this.clips.delete(name));
    }
    return p;
  }

  /** One update at a time (a drag fires many; overlapping ones would start a source twice). */
  update(sources: Source[], tfs: Record<string, EarTF>, ref: EarTF, gainDb: Record<"left" | "right", number[]>, condKey: string) {
    this.queue = this.queue.then(() => this.apply(sources, tfs, ref, gainDb, condKey)).catch(() => {});
    return this.queue;
  }

  /** ref: the OPEN ears' frontal response, the equalisation for every condition (aided included). */
  private async apply(sources: Source[], tfs: Record<string, EarTF>, ref: EarTF, gainDb: Record<"left" | "right", number[]>, condKey: string) {
    if (this.closed) return;
    if (this.ctx.state === "suspended") await this.ctx.resume();
    const keep = new Set(sources.map((s) => s.id));
    const offset = playbackOffsetDb(sources);
    for (const [id, v] of this.voices) if (!keep.has(id)) { this.fadeOut(v); this.voices.delete(id); }
    for (const [i, s] of sources.entries()) {
      const near = nearestTF(tfs, s.az, s.el);
      if (!near) continue;
      const key = `${near.key}|${condKey}`, clip = clipFor(s, i);
      const level = 10 ** ((s.levelDb - 65 - offset) / 20);
      const v = this.voices.get(s.id);
      if (v && v.key === key && v.clip === clip) { v.level.gain.setTargetAtTime(level, this.ctx.currentTime, 0.03); continue; }
      const buffer = await this.clip(clip).catch(() => null);
      if (!buffer) continue;
      const conv = this.ctx.createConvolver();
      conv.normalize = false;
      conv.buffer = impulseResponse(this.ctx, near.tf, ref, gainDb);
      const mix = this.ctx.createGain();
      mix.gain.value = 0;
      conv.connect(mix).connect(this.master);
      if (v && v.clip === clip) {                       // same sound, new direction or condition: crossfade the filter
        v.level.connect(conv);
        mix.gain.setTargetAtTime(1, this.ctx.currentTime, ScenePlayer.XFADE / 3);
        const old = { conv: v.conv, mix: v.mix };
        old.mix.gain.setTargetAtTime(0, this.ctx.currentTime, ScenePlayer.XFADE / 3);
        window.setTimeout(() => { try { v.level.disconnect(old.conv); } catch { /* already gone */ } old.mix.disconnect(); }, ScenePlayer.XFADE * 4000);
        Object.assign(v, { conv, mix, key });
        v.level.gain.setTargetAtTime(level, this.ctx.currentTime, 0.03);
      } else {
        if (v) this.fadeOut(v);
        const src = this.ctx.createBufferSource();
        src.buffer = buffer;
        src.loop = true;
        const g = this.ctx.createGain();
        g.gain.value = level;
        src.connect(g).connect(conv);
        // stagger loops so overlapping talkers do not start in lockstep
        src.start(0, (i * 0.37) % buffer.duration);
        mix.gain.setTargetAtTime(1, this.ctx.currentTime, ScenePlayer.XFADE / 3);
        this.voices.set(s.id, { src, level: g, conv, mix, key, clip });
      }
    }
  }

  private fadeOut(v: Voice) {
    v.mix.gain.setTargetAtTime(0, this.ctx.currentTime, 0.03);
    window.setTimeout(() => { try { v.src.stop(); } catch { /* not started */ } v.src.disconnect(); v.mix.disconnect(); }, 200);
  }

  private closed = false;

  stop() {
    this.closed = true;
    for (const v of this.voices.values()) this.fadeOut(v);
    this.voices.clear();
    window.setTimeout(() => this.ctx.close().catch(() => {}), 300);
  }
}
