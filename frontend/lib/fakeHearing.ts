import { CALIBRATION_ID, type Result } from "@/lib/audiometry";

/** Practice patient for the dev "z" shortcut (Dashboard.tsx): a mild sloping loss, ears within 15 dB and nothing above 40 dB HL, so flags() stays empty. Goes through the SAME hearingPdf as the in-app test, so the attachment is byte-for-byte the real format. */
export const fakeHearing = (): Result => ({
  thresholds: { right: { 500: 10, 1000: 20, 2000: 30, 4000: 40 }, left: { 500: 20, 1000: 20, 2000: 30, 4000: 40 } },
  catches: { presented: 3, falseAlarms: 0 },
  date: new Date().toISOString().slice(0, 10),
  durationS: 30,
  calibration: CALIBRATION_ID,
});
