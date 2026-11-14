import { test, expect } from "@playwright/test";
import { PLAN, flags, levelOf, newTrack, respond, type Result } from "../lib/audiometry";
import { hearingPdf } from "../lib/hearingPdf";

// A listener who hears every tone at or above their true threshold. Runs the real procedure with no browser and no audio.
const run = (truth: Record<"right" | "left", Record<number, number>>, count?: number[]): Result => {
  const r: Result = { thresholds: { right: {}, left: {} }, catches: { presented: 3, falseAlarms: 0 }, date: "2026-11-14", durationS: 30, calibration: "test" };
  for (const { ear, freq } of PLAN) {
    let t = newTrack(), n = 0;
    while (t.result === undefined) (t = respond(t, levelOf(t) >= truth[ear][freq])), n++;
    count?.push(n);
    r.thresholds[ear][freq] = t.result;
  }
  return r;
};
const sloping = { 500: 15, 1000: 20, 2000: 35, 4000: 50 };

// Catches a broken halving search: the result must be the quietest 10 dB step the patient hears — never quieter than their real threshold, never more than one step above it.
test("recovers a sloping high-frequency loss to the next 10 dB step", () => {
  const truth = { right: sloping, left: { 500: 20, 1000: 25, 2000: 33, 4000: 47 } };
  const r = run(truth);
  for (const ear of ["right", "left"] as const)
    for (const [f, want] of Object.entries(truth[ear])) {
      const got = r.thresholds[ear][+f] as number;
      expect(got).toBeGreaterThanOrEqual(want);
      expect(got - want).toBeLessThan(10);
    }
});

// Catches the test drifting past ~30 s: every pitch must take EXACTLY 3 beeps (8 pitches = 24 beeps plus a few silent trials).
test("every pitch takes exactly 3 beeps", () => {
  const count: number[] = [];
  run({ right: sloping, left: { 500: 0, 1000: 999, 2000: 60, 4000: 5 } }, count);
  expect(count).toEqual(Array(8).fill(3));
});

// Catches a silent pitch being reported as a number — "no response" must stay a marker, never a fake threshold.
test("never hearing a pitch gives no response, not a number", () => {
  const r = run({ right: { ...sloping, 4000: 999 }, left: sloping });
  expect(r.thresholds.right[4000]).toBe("nr");
});

// Catches the referral and reliability flags going missing — they are the safety net for an uncalibrated self-test.
test("flags guessing, asymmetry and loss beyond a passive device", () => {
  const r = run({ right: sloping, left: { 500: 35, 1000: 40, 2000: 55, 4000: 60 } });
  r.catches = { presented: 3, falseAlarms: 1 };
  const f = flags(r).join(" ");
  expect(f).toContain("silent trials");
  expect(f).toContain("differ by 15 dB");
  expect(f).toContain("powered hearing aid");
  expect(flags(run({ right: { 500: 10, 1000: 10, 2000: 20, 4000: 30 }, left: { 500: 10, 1000: 10, 2000: 20, 4000: 30 } }))).toEqual([]);
});

// Catches a corrupt PDF: a wrong xref offset makes strict readers refuse the file.
test("hearing PDF has a valid header and xref", async () => {
  const txt = await hearingPdf(run({ right: sloping, left: sloping })).text();
  expect(txt.startsWith("%PDF-1.4")).toBe(true);
  const at = Number(txt.match(/startxref\n(\d+)/)![1]);
  expect(txt.slice(at, at + 4)).toBe("xref");
  for (const [i, off] of [...txt.matchAll(/(\d{10}) 00000 n/g)].entries()) expect(txt.slice(Number(off[1])).startsWith(`${i + 1} 0 obj`)).toBe(true);
});
