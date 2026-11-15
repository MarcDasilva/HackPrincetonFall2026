// Port of backend/hornsim/scoring.py (_sii_terms, hearing_level, prescription_gain "nal_r") and the
// target rule of hornsim/target.py `triage`:  T(f) = min(NAL-R, max(0, Σ_s w_s · deficit_s(f))).
//
// One difference from the backend, on purpose for a live view: speech and babble enter as the ANSI
// S3.5 standard speech spectrum (U_i) at the scene level, not as band levels measured from the
// Harvard clips. Direction filters from the wave sim then shift each band, exactly where the
// backend applies them to the clip.

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

export type SceneSource = { role: "talker" | "babble"; az: number; el: number; levelDb: number; gainDb: number[] };

/** One scene through a healthy ear and this ear, no device (runner.run_scene). With `deviceGainDb`
 * (the earpiece's insertion gain per band) also the aided SII: the device sits in front of the
 * eardrum, so speech AND noise both get its gain (runner applies gains to the mixture). */
export function sceneDeficit(sources: SceneSource[], ag: Audiogram, deviceGainDb?: number[]) {
  const talk = sources.filter((s) => s.role === "talker");
  const noise = sources.filter((s) => s.role === "babble");
  if (!talk.length) return null;
  const E = powerSum(talk.map((s) => speechBands(s.levelDb, s.gainDb)));
  const N = noise.length ? powerSum(noise.map((s) => speechBands(s.levelDb, s.gainDb))) : null;
  const hl0 = SII_FREQS.map(() => 0), hl = hearingLevel(ag, SII_FREQS);
  const healthy = siiTerms(E, N, hl0), impaired = siiTerms(E, N, hl);
  const deficit = healthy.aud.map((a, i) => a - impaired.aud[i]);
  return {
    deficit,
    deficitWeighted: deficit.map((d, i) => d * SII_IMPORTANCE[i]),
    siiHealthy: sii(E, N, hl0),
    siiUnaided: sii(E, N, hl),
    siiAided: deviceGainDb ? sii(E.map((e, i) => e + deviceGainDb[i]), N ? N.map((x, i) => x + deviceGainDb[i]) : null, hl) : undefined,
  };
}

/** target.triage's target: weighted mean deficit, floored at 0, capped at NAL-R. */
export function targetGain(deficits: number[][], weights: number[], ag: Audiogram) {
  const W = weights.reduce((a, b) => a + b, 0) || 1;
  const need = Array.from({ length: NB }, (_, i) => Math.max(0, deficits.reduce((s, d, k) => s + (weights[k] / W) * d[i], 0)));
  const nal = nalR(ag);
  return { need, nal, target: need.map((n, i) => Math.min(n, nal[i])) };
}
