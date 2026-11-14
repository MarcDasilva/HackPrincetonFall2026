/** Pure-tone hearing screening (specs/01a-hearing-test.md): the up-down procedure, calibration and result flags. No audio and no DOM here — components/HearingTest.tsx plays the tones, so this file is testable without a browser (e2e/audiometry.spec.ts). */

export type Ear = "right" | "left";
/** A threshold in dB HL, or "nr": no response at the loudest level the calibration allows. */
export type Threshold = number | "nr";

/** Chart floor only; the test itself never goes below LEVELS[0]. */
export const MIN_HL = -10;
/** 10 dB grid. Not heard at the top level = "nr". 7 levels + "nr" = 8 outcomes = EXACTLY 3 presentations per pitch. */
export const LEVELS = [0, 10, 20, 30, 40, 50, 60];
export const MAX_HL = LEVELS[LEVELS.length - 1];

// ponytail: ~30 s screening — 4 pitches per ear, 3 beeps each, no retest, 10 dB resolution. The clinical up-down method (5 dB steps, 2-of-3 confirmations, 250 Hz and 8 kHz, a 1 kHz retest) takes ~6 min; bring it back if accuracy matters more than speed.
export const AXIS = [500, 1000, 2000, 4000];
const ORDER = [1000, 2000, 4000, 500];
export const PLAN: { ear: Ear; freq: number }[] = (["right", "left"] as const).flatMap((ear) => ORDER.map((freq) => ({ ear, freq })));

// ponytail: ASSUMED calibration — ISO 389-2 insert-earphone reference levels on headphones assumed to play 100 dB SPL at full scale at the instructed 50% volume. Every threshold shifts by however wrong that is (typically 10–20 dB); replace with a measured or listener-tuned table per specs/01a.
export const CALIBRATION_ID = "assumed-v1";
const RETSPL: Record<number, number> = { 500: 5.5, 1000: 0, 2000: 3, 4000: 5.5 };
const FULL_SCALE_SPL = 100;
/** Linear peak amplitude (0..1) for a tone at `hl` dB HL. */
export const toGain = (freq: number, hl: number) => 10 ** ((hl + RETSPL[freq] - FULL_SCALE_SPL) / 20);

/** Halving search over LEVELS: the answer is an index in [lo, hi], where hi = LEVELS.length means "nr". */
export type Track = { lo: number; hi: number; result?: Threshold };
export const newTrack = (): Track => ({ lo: 0, hi: LEVELS.length });
export const levelOf = (t: Track) => LEVELS[(t.lo + t.hi) >> 1];

/** Threshold = the quietest grid level heard. ONE press per level decides it, so a single missed beep reads 10+ dB worse — the price of 30 s. */
export function respond(t: Track, heard: boolean): Track {
  const mid = (t.lo + t.hi) >> 1;
  const n: Track = heard ? { lo: t.lo, hi: mid } : { lo: mid + 1, hi: t.hi };
  return n.lo === n.hi ? { ...n, result: n.lo === LEVELS.length ? "nr" : LEVELS[n.lo] } : n;
}

export type Result = {
  thresholds: Record<Ear, Record<number, Threshold>>;
  catches: { presented: number; falseAlarms: number };
  date: string;
  durationS: number;
  calibration: string;
};

/** Reliability and referral flags (specs/01a § Reliability flags). Plain-language text goes straight into the PDF. */
export function flags(r: Result): string[] {
  const out: string[] = [];
  const num = (v: Threshold | undefined): v is number => typeof v === "number";
  if (r.catches.presented && r.catches.falseAlarms / r.catches.presented > 0.2)
    out.push(`Answered ${r.catches.falseAlarms} of ${r.catches.presented} silent trials. Consider retaking the test in a quieter room.`);
  const diff = AXIS.map((f) => {
    const a = r.thresholds.right[f], b = r.thresholds.left[f];
    return num(a) && num(b) ? Math.abs(a - b) : 0;
  });
  if (diff.some((d, i) => i > 0 && d >= 15 && diff[i - 1] >= 15))
    out.push("Your ears differ by 15 dB or more at neighbouring pitches. Please see an audiologist.");
  if ((["right", "left"] as const).some((e) => [500, 1000, 2000, 4000].some((f) => { const v = r.thresholds[e][f]; return v === "nr" || (num(v) && v > 40); })))
    out.push("Some thresholds are above 40 dB HL. A powered hearing aid is likely a better fit than a passive earpiece; please see an audiologist.");
  return out;
}
