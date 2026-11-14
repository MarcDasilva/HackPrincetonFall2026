// Port of backend/hornsim/scoring.py (_sii_terms, hearing_level, prescription_gain "nal_r") and the
// target rule of hornsim/target.py `triage`:  T(f) = min(NAL-R, max(0, Σ_s w_s · deficit_s(f))).
//
// One difference from the backend, on purpose for a live view: speech and babble enter as the ANSI
// S3.5 standard speech spectrum (U_i) at the scene level, not as band levels measured from the
// Harvard clips. Direction filters from the wave sim then shift each band, exactly where the
// backend applies them to the clip.

import { SOUNDS, type Role } from "./sounds";

export const SII_FREQS = [160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000];
export const SII_IMPORTANCE = [0.0083, 0.0095, 0.015, 0.0289, 0.044, 0.0578, 0.0653, 0.0711, 0.0818, 0.0844, 0.0882, 0.0898, 0.0868, 0.0844, 0.0771, 0.0527, 0.0364, 0.0185];
const SII_X = [0.6, -1.7, -3.9, -6.1, -8.2, -9.7, -10.8, -11.9, -12.5, -13.5, -15.4, -17.7, -21.2, -24.2, -25.9, -23.6, -15.8, -7.1];
const SII_U = [32.41, 34.48, 34.75, 33.98, 34.59, 34.27, 32.06, 28.3, 25.01, 23.0, 20.15, 17.32, 13.18, 11.55, 9.33, 5.31, 2.59, 1.13];
const BW = SII_FREQS.map((f) => f * (2 ** (1 / 6) - 2 ** (-1 / 6)));
const HASPI_FREQS = [250, 500, 1000, 2000, 4000, 6000];
const NB = SII_FREQS.length;

export type Audiogram = Record<number, number>; // Hz -> dB HL
export const toAudiogram = (o: Record<string, number>): Audiogram => Object.fromEntries(Object.entries(o).map(([k, v]) => [Number(k), Number(v)]));
// hornsim/defaults.yaml: PLACEHOLDER example audiogram until a real hearing test is supplied
export const EXAMPLE_AUDIOGRAM: Audiogram = { 250: 15, 500: 20, 1000: 30, 2000: 45, 4000: 55, 6000: 55 };

/** Overall level of the U_i spectrum (≈ 62.35 dB SPL, ANSI "normal" effort). */
const U_OVERALL = 10 * Math.log10(SII_U.reduce((s, u, i) => s + 10 ** (u / 10) * BW[i], 0));

/** dB HL at freqs, linear on log frequency, flat beyond the ends (scoring.hearing_level). */
export function hearingLevel(ag: Audiogram, freqs: number[]) {
  const f = Object.keys(ag).map(Number).sort((a, b) => a - b);
  const lf = f.map(Math.log), v = f.map((k) => ag[k]);
  return freqs.map((x) => {
    const l = Math.log(x);
    if (l <= lf[0]) return v[0];
    if (l >= lf[lf.length - 1]) return v[v.length - 1];
    const i = lf.findIndex((y) => y >= l);
    const t = (l - lf[i - 1]) / (lf[i] - lf[i - 1]);
    return v[i - 1] + t * (v[i] - v[i - 1]);
  });
}

/** Byrne & Dillon (1986) NAL-R on the HASPI frequencies, interpolated on log f to the SII bands. */
export function nalR(ag: Audiogram) {
  const hl = hearingLevel(ag, HASPI_FREQS);
  const bias = [-17, -8, 1, -1, -2, -2];
  const crit = hl[1] + hl[2] + hl[3];
  const x = crit <= 180 ? 0.05 * crit : 9.0 + 0.116 * (crit - 180);
  const g = hl.map((h, i) => Math.max(0, x + 0.31 * h + bias[i]));
  return hearingLevel(Object.fromEntries(HASPI_FREQS.map((f, i) => [f, g[i]])), SII_FREQS);
}

/** Band spectrum levels (dB SPL/Hz) of standard-spectrum speech at `level_db`, shifted per band by `gainDb`. */
export function speechBands(levelDb: number, gainDb: number[]) {
  return SII_U.map((u, i) => u + levelDb - U_OVERALL + gainDb[i]);
}

/** Sum of incoherent band levels (dB). */
export function powerSum(levels: number[][]) {
  return Array.from({ length: NB }, (_, i) => 10 * Math.log10(levels.reduce((s, L) => s + 10 ** (L[i] / 10), 0)));
}

/** ANSI S3.5-1997 one-third-octave terms (scoring._sii_terms): audibility E'−D clipped to ±15 dB, and L. */
export function siiTerms(E: number[], N: number[] | null, hl: number[]) {
  const Nn = N ?? E.map(() => -Infinity);
  const B = E.map((e, i) => Math.max(Nn[i], e - 24));
  const C = B.map((b, i) => -80 + 0.6 * (b + 10 * Math.log10(SII_FREQS[i]) - 6.353));
  const Z = B.slice();
  for (let i = 1; i < NB; i++) {
    let s = Number.isFinite(Nn[i]) ? 10 ** (0.1 * Nn[i]) : 0;
    for (let k = 0; k < i; k++) s += 10 ** (0.1 * (B[k] + 3.32 * C[k] * Math.log10((0.89 * SII_FREQS[i]) / SII_FREQS[k])));
    Z[i] = 10 * Math.log10(s);
  }
  const D = Z.map((z, i) => Math.max(z, SII_X[i] + hl[i]));
  const L = E.map((e, i) => Math.min(1, Math.max(0, 1 - (e - SII_U[i] - 10) / 160)));
  const aud = E.map((e, i) => Math.min(15, Math.max(-15, e - D[i])));
  return { aud, L };
}

export function sii(E: number[], N: number[] | null, hl: number[]) {
  const { aud, L } = siiTerms(E, N, hl);
  return aud.reduce((s, a, i) => s + SII_IMPORTANCE[i] * L[i] * ((a + 15) / 30), 0);
}

export type SceneSource = { role: Role; target?: boolean; az: number; el: number; levelDb: number; gainDb: number[] };

// Long-term spectrum shapes for the noise sources, band spectrum level in dB relative to an arbitrary
// reference, per SII band. APPROXIMATE, from the usual descriptions rather than measured recordings:
// club music close to pink with a bass lift (spectrum level -4.5 dB/octave, +4 dB at 160 Hz); road
// noise flat below 315 Hz then -6 dB/octave, with a small tyre-noise bump around 1 kHz. Babble uses the
// speech spectrum (U_i) like a talker.
const MUSIC_SHAPE = SII_FREQS.map((f) => -4.5 * Math.log2(f / 160) + (f <= 160 ? 4 : f <= 200 ? 2 : f <= 250 ? 1 : 0));
const TRAFFIC_SHAPE = SII_FREQS.map((f) => (f < 315 ? 0 : -6 * Math.log2(f / 315)) + (f >= 800 && f <= 1250 ? 3 : 0));
// smoke alarm: a ~3.1 kHz tone (its band) with weaker harmonics; birdsong: chirps between ~2.5 and 8 kHz
const ALARM_SHAPE = SII_FREQS.map((f) => (f === 3150 ? 0 : f === 6300 ? -12 : f === 2500 || f === 4000 ? -18 : -45));
const BIRDS_SHAPE = SII_FREQS.map((f) => -10 * Math.log2(f / 4500) ** 2);
function shapedBands(shape: number[], levelDb: number, gainDb: number[]) {
  const overall = 10 * Math.log10(shape.reduce((s, u, i) => s + 10 ** (u / 10) * BW[i], 0));
  return shape.map((u, i) => u + levelDb - overall + gainDb[i]);
}
/** Band spectrum levels of any source at `level_db` (overall dB SPL over the SII bands). */
export function sourceBands(role: SceneSource["role"], levelDb: number, gainDb: number[]) {
  if (role === "music") return shapedBands(MUSIC_SHAPE, levelDb, gainDb);
  if (role === "traffic") return shapedBands(TRAFFIC_SHAPE, levelDb, gainDb);
  if (role === "alarm") return shapedBands(ALARM_SHAPE, levelDb, gainDb);
  if (role === "birds") return shapedBands(BIRDS_SHAPE, levelDb, gainDb);
  return speechBands(levelDb, gainDb);
}

/** Is this the sound the listener wants to hear? Talkers by default; any source can be marked. */
export const isTarget = (s: { role: SceneSource["role"]; target?: boolean }) => s.target ?? SOUNDS[s.role].target;

/** Band-importance weights for a target. Speech: the ANSI S3.5 one-third-octave importance function.
 * Anything else (music, an alarm, birdsong): where that sound carries its energy, compressed (square
 * root of each band's energy share) so its quieter bands still count. That reuses the SII's audibility
 * machinery with a different importance function, as the standard allows; for non-speech it is an
 * audibility index (AI), not an intelligibility score. */
export function importanceFor(role: SceneSource["role"], bands: number[]) {
  if (SOUNDS[role].speech) return SII_IMPORTANCE;
  const share = bands.map((b, i) => Math.sqrt(10 ** (b / 10) * BW[i]));
  const sum = share.reduce((a, b) => a + b, 0) || 1;
  return share.map((s) => s / sum);
}

/** Audibility index: sum of importance × (audibility + 15) / 30, with the speech level-distortion factor
 * only for speech. */
function audIndex(E: number[], N: number[] | null, hl: number[], imp: number[], speech: boolean) {
  const { aud, L } = siiTerms(E, N, hl);
  return aud.reduce((s, a, i) => s + imp[i] * (speech ? L[i] : 1) * ((a + 15) / 30), 0);
}

/** One scene through a healthy ear and this ear, no device (runner.run_scene), for each sound the
 * listener wants to hear (the targets) against everything else (the maskers). The deficit per band
 * is what the earpiece should restore; weighted by each target's importance it steers the design
 * toward where THAT sound lives. With `deviceGainDb` (the earpiece's insertion gain per band) also
 * the aided index: the device sits in front of the eardrum, so target AND maskers get its gain. */
export function sceneDeficit(sources: SceneSource[], ag: Audiogram, deviceGainDb?: number[]) {
  const targets = sources.filter(isTarget);
  const maskers = sources.filter((s) => !isTarget(s));
  if (!targets.length) return null;
  const N = maskers.length ? powerSum(maskers.map((s) => sourceBands(s.role, s.levelDb, s.gainDb))) : null;
  const hl0 = SII_FREQS.map(() => 0), hl = hearingLevel(ag, SII_FREQS);
  const per = targets.map((t) => {
    const E = sourceBands(t.role, t.levelDb, t.gainDb), speech = SOUNDS[t.role].speech;
    const imp = importanceFor(t.role, E);
    const healthy = siiTerms(E, N, hl0), impaired = siiTerms(E, N, hl);
    const deficit = healthy.aud.map((a, i) => a - impaired.aud[i]);
    return {
      deficit, weighted: deficit.map((d, i) => d * imp[i]),
      healthy: audIndex(E, N, hl0, imp, speech), unaided: audIndex(E, N, hl, imp, speech),
      aided: deviceGainDb ? audIndex(E.map((e, i) => e + deviceGainDb[i]), N ? N.map((x, i) => x + deviceGainDb[i]) : null, hl, imp, speech) : undefined,
    };
  });
  const mean = (k: "healthy" | "unaided") => per.reduce((s, p) => s + p[k], 0) / per.length;
  const meanV = (k: "deficit" | "weighted") => SII_FREQS.map((_, i) => per.reduce((s, p) => s + p[k][i], 0) / per.length);
  return {
    deficit: meanV("deficit"),
    deficitWeighted: meanV("weighted"),
    metric: targets.every((t) => SOUNDS[t.role].speech) ? "SII" : "AI",
    targetRoles: [...new Set(targets.map((t) => t.role))],
    siiHealthy: mean("healthy"),
    siiUnaided: mean("unaided"),
    siiAided: deviceGainDb ? per.reduce((s, p) => s + (p.aided ?? 0), 0) / per.length : undefined,
  };
}

/** target.triage's target: weighted mean deficit, floored at 0, capped at NAL-R. */
export function targetGain(deficits: number[][], weights: number[], ag: Audiogram) {
  const W = weights.reduce((a, b) => a + b, 0) || 1;
  const need = Array.from({ length: NB }, (_, i) => Math.max(0, deficits.reduce((s, d, k) => s + (weights[k] / W) * d[i], 0)));
  const nal = nalR(ag);
  return { need, nal, target: need.map((n, i) => Math.min(n, nal[i])) };
}
