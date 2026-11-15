import { CALIBRATION_ID, type Result } from "@/lib/audiometry";

/** Practice patient for the dev Caps Lock shortcut (Dashboard.tsx). Goes through the SAME hearingPdf as the in-app test, so the
 * attachment is byte-for-byte the real format. The left ear is above 40 dB HL, so the PDF carries the "powered aid" note — true
 * for this ear. The right ear stays 5–10 dB milder: the left is then the aided (worse) ear, and no ear-difference flag fires. */
export const fakeHearing = (): Result => ({
  // 250 and 6000 Hz too: the research's HASPI evaluator needs a measured threshold at EVERY HASPI frequency
  // (250–6000 Hz) and refuses to fill gaps (agents hornsim_evaluator.py missing_data_rule) — without them research never starts.
  thresholds: { right: { 250: 40, 500: 45, 1000: 40, 2000: 35, 4000: 50, 6000: 20 }, left: { 250: 45, 500: 50, 1000: 45, 2000: 40, 4000: 60, 6000: 20 } },
  catches: { presented: 3, falseAlarms: 0 },
  date: new Date().toISOString().slice(0, 10),
  durationS: 30,
  calibration: CALIBRATION_ID,
});
