import { AXIS, MAX_HL, MIN_HL, flags, type Result } from "./audiometry";

// ponytail: hand-written one-page PDF (Helvetica, vector lines) instead of a PDF library — ASCII text ONLY, because the xref offsets count characters as bytes. Swap in a library if the report needs images or non-ASCII text.
const esc = (s: string) => s.replace(/[^\x20-\x7e]/g, "").replace(/([\\()])/g, "\\$1");

/** The short hearing-screening report attached to the chat when the in-app test finishes. */
export function hearingPdf(r: Result): Blob {
  const ops: string[] = [];
  const text = (x: number, y: number, size: number, s: string, bold = false) => ops.push(`BT /${bold ? "F2" : "F1"} ${size} Tf ${x} ${y} Td (${esc(s)}) Tj ET`);
  const line = (x1: number, y1: number, x2: number, y2: number) => ops.push(`${x1} ${y1} m ${x2} ${y2} l S`);
  const rgb = (c: string) => ops.push(`${c} RG ${c} rg`);

  text(56, 790, 20, "Auris hearing screening", true);
  text(56, 770, 10, `Date: ${r.date}    Duration: ${r.durationS} s    Calibration: ${r.calibration}`);
  text(56, 756, 10, "Screening result from an in-app test. Not a clinical audiogram and not a diagnosis.");

  // Audiogram: pitch across (octaves evenly spaced), dB HL DOWN the page — the clinical convention, worse hearing lower.
  const X0 = 90, Y0 = 400, W = 440, H = 320;
  const xOf = (f: number) => X0 + 30 + (AXIS.indexOf(f) * (W - 60)) / (AXIS.length - 1);
  const yOf = (db: number) => Y0 + H - ((db - MIN_HL) / (MAX_HL + 10 - MIN_HL)) * H;
  ops.push("0.5 w");
  rgb("0.85 0.85 0.85");
  for (let db = MIN_HL; db <= MAX_HL + 10; db += 10) line(X0, yOf(db), X0 + W, yOf(db));
  for (const f of AXIS) line(xOf(f), Y0, xOf(f), Y0 + H);
  rgb("0 0 0");
  ops.push(`${X0} ${Y0} ${W} ${H} re S`);
  for (let db = MIN_HL; db <= MAX_HL + 10; db += 10) text(X0 - 24, yOf(db) - 3, 8, String(db));
  for (const f of AXIS) text(xOf(f) - 10, Y0 + H + 8, 8, f >= 1000 ? `${f / 1000}k` : String(f));
  text(X0 + W / 2 - 30, Y0 + H + 22, 9, "Frequency (Hz)");
  text(X0 - 30, Y0 - 16, 9, "Hearing level (dB HL)");

  const k = 0.5523;
  const circle = (x: number, y: number, rr: number) =>
    ops.push(`${x + rr} ${y} m ${x + rr} ${y + k * rr} ${x + k * rr} ${y + rr} ${x} ${y + rr} c ${x - k * rr} ${y + rr} ${x - rr} ${y + k * rr} ${x - rr} ${y} c ${x - rr} ${y - k * rr} ${x - k * rr} ${y - rr} ${x} ${y - rr} c ${x + k * rr} ${y - rr} ${x + rr} ${y - k * rr} ${x + rr} ${y} c S`);
  const cross = (x: number, y: number, rr: number) => { line(x - rr, y - rr, x + rr, y + rr); line(x - rr, y + rr, x + rr, y - rr); };
  ops.push("1.2 w");
  for (const [ear, color, mark] of [["right", "0.8 0.1 0.1", circle], ["left", "0.1 0.25 0.8", cross]] as const) {
    rgb(color);
    const pts = AXIS.map((f) => [f, r.thresholds[ear][f]] as const);
    pts.forEach(([f, v], i) => {
      if (v === "nr") return text(xOf(f) - 7, yOf(MAX_HL) - 16, 8, "NR");
      mark(xOf(f), yOf(v), 5);
      const prev = pts[i - 1]?.[1];
      if (typeof prev === "number") line(xOf(AXIS[i - 1]), yOf(prev), xOf(f), yOf(v));
    });
  }
  rgb("0.8 0.1 0.1");
  text(X0 + W - 120, Y0 - 16, 9, "O  Right ear");
  rgb("0.1 0.25 0.8");
  text(X0 + W - 55, Y0 - 16, 9, "X  Left ear");
  rgb("0 0 0");

  // Table of the same numbers, for anyone who would rather read than plot.
  let y = 340;
  text(56, y, 9, "Hz", true);
  AXIS.forEach((f, i) => text(120 + i * 80, y, 9, String(f), true));
  for (const ear of ["right", "left"] as const) {
    y -= 16;
    text(56, y, 9, ear === "right" ? "Right" : "Left");
    AXIS.forEach((f, i) => text(120 + i * 80, y, 9, String(r.thresholds[ear][f]).toUpperCase()));
  }
  y -= 16;
  text(56, y, 8, `NR = no response at ${MAX_HL} dB HL. Tested in 10 dB steps.  Silent trials answered: ${r.catches.falseAlarms} of ${r.catches.presented}.`);

  y -= 30;
  text(56, y, 11, "Notes", true);
  const notes = flags(r);
  // ~100 chars of 9pt Helvetica fill the 483pt text width; PDF text never wraps by itself.
  for (const n of notes.length ? notes : ["No reliability or referral flags."])
    (`- ${n}`.match(/.{1,100}(\s|$)/g) ?? []).forEach((part, i) => text(i ? 64 : 56, (y -= i ? 12 : 16), 9, part.trim()));
  text(56, 60, 8, `Calibration ${r.calibration} assumes your headphones' output level; thresholds may be off by 10-20 dB. See an audiologist for a clinical test.`);

  const content = ops.join("\n");
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
  ];
  let out = "%PDF-1.4\n";
  const offsets = objs.map((o, i) => {
    const at = out.length;
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
    return at;
  });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return new Blob([out], { type: "application/pdf" });
}
