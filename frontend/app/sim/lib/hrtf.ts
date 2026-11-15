"use client";
// Each ear's response to every direction (backend hornsim/hrtf_table.py, by reciprocity at 1.5 mm),
// computed once per head, and once more with both earpieces in. With a table, a scene needs no
// simulation of its own: every source's direction is a lookup, for scoring and for listening.
import { bandFreqs } from "./bands";
import type { EarTF } from "./binaural";
import type { Side } from "./fdtd";

export type HrtfTableJson = {
  az_step: number; elevations: number[]; azel: [number, number][]; bins: number[]; audio_sr: number; audio_n: number;
  left_b64: string; right_b64: string; dx_mm: number; aided: boolean; elapsed_s: number;
};
export type HrtfTable = { json: HrtfTableJson; data: Record<Side, Float32Array>; byKey: Map<string, number> };

function decode(b64: string) {
  const bin = atob(b64), u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Float32Array(u8.buffer);
}

export function loadTable(j: HrtfTableJson): HrtfTable {
  const byKey = new Map<string, number>();
  j.azel.forEach(([a, e], i) => byKey.set(`${a},${e}`, i));
  return { json: j, data: { left: decode(j.left_b64), right: decode(j.right_b64) }, byKey };
}

/** Index of the table direction nearest (az, el): az to the table's step, el to the nearest stored elevation. */
function nearestIndex(t: HrtfTable, az: number, el: number) {
  const a = ((Math.round(az / t.json.az_step) * t.json.az_step) % 360 + 360) % 360;
  const e = t.json.elevations.reduce((b, x) => (Math.abs(x - el) < Math.abs(b - el) ? x : b), t.json.elevations[0]);
  return t.byKey.get(`${a},${e}`)!;
}

/** The two ears' transfer functions toward (az, el), on the AUDIO_N FFT bins (lib/binaural.ts). */
export function tfAt(t: HrtfTable, az: number, el: number): EarTF {
  const i = nearestIndex(t, az, el), nb = t.json.audio_n / 2 + 1, nk = t.json.bins.length;
  const one = (s: Side) => {
    const re = new Float32Array(nb), im = new Float32Array(nb), d = t.data[s];
    t.json.bins.forEach((k, j) => { re[k] = d[(i * nk + j) * 2]; im[k] = d[(i * nk + j) * 2 + 1]; });
    return { re, im };
  };
  return { left: one("left"), right: one("right") };
}

/** |H| at the band-analysis frequencies (lib/bands.ts), interpolated on log f between bins: the same
 * quantity the browser's own runs give (their click spectrum cancels in every ratio). */
export function spectraAt(t: HrtfTable, az: number, el: number): Record<Side, number[]> {
  const i = nearestIndex(t, az, el), nk = t.json.bins.length, df = t.json.audio_sr / t.json.audio_n;
  const fb = t.json.bins.map((k) => k * df);
  const one = (s: Side) => {
    const d = t.data[s], mag = fb.map((_, j) => Math.hypot(d[(i * nk + j) * 2], d[(i * nk + j) * 2 + 1]));
    return bandFreqs().map((f) => {
      if (f <= fb[0]) return mag[0];
      let j = 1;
      while (j < fb.length - 1 && fb[j] < f) j++;
      const u = (Math.log(f) - Math.log(fb[j - 1])) / (Math.log(fb[j]) - Math.log(fb[j - 1]));
      return mag[j - 1] + Math.min(1, Math.max(0, u)) * (mag[j] - mag[j - 1]);
    });
  };
  return { left: one("left"), right: one("right") };
}
