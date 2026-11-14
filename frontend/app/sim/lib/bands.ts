import { SII_FREQS } from "./hearing";

export const PER_BAND = 5; // frequencies averaged as power across each one-third-octave band (target.PER_BAND)

/** PER_BAND log-spaced frequencies inside each SII band, flattened. */
export function bandFreqs() {
  return SII_FREQS.flatMap((f) => Array.from({ length: PER_BAND }, (_, k) => f * 2 ** (-1 / 6 + (k + 0.5) / (3 * PER_BAND))));
}

/** Direction gain per band, dB: power-mean |E_src|² / |E_ref|² inside each band. */
export function bandGainDb(spec: number[], ref: number[]) {
  return SII_FREQS.map((_, b) => {
    let s = 0, r = 0;
    for (let k = 0; k < PER_BAND; k++) { s += spec[b * PER_BAND + k] ** 2; r += ref[b * PER_BAND + k] ** 2; }
    return 10 * Math.log10(s / r);
  });
}
