// The final report as a PDF the dashboard downloads when the lead finishes (stage "done"): the session's numbers as
// figures, the earpiece rendered in the patient's own ear, the research findings with their sources, and the lead's
// written report. Charts are drawn on a 2D canvas at 2× and placed as images — ONE drawing API for every figure.
import { jsPDF } from "jspdf";
import type { LeadReply, StudyEvent } from "@/lib/lead";
import { designFile, fetchGrid } from "@/app/sim/lib/api";
import { snapAid } from "@/app/sim/lib/aidSnap";
import { DEFAULT_VIEW, snapHead } from "@/app/sim/HeadSnap";
import { SII_FREQS } from "@/app/sim/lib/hearing";

const C = { normal: "#9aa0a8", you: "#d95926", aided: "#2a78d6", ink: "#1b1d21", muted: "#6b7079", grid: "#e4e2de", piece: "#f38c28" };
const PW = 595, PH = 842, M = 48, CW = PW - 2 * M;
const AG_F = [250, 500, 1000, 2000, 4000, 6000];
const hz = (f: number) => (f >= 1000 ? `${f / 1000}k` : `${f}`);
const pct = (v: number | null | undefined) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "-");
const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
/** jsPDF's built-in Helvetica is WinAnsi: anything past it (arrows, emoji, CJK) prints as garbage, so it is mapped or dropped. */
const ascii = (s: string) => s.replace(/[→⟶]/g, "->").replace(/[←]/g, "<-").replace(/[≥]/g, ">=").replace(/[≤]/g, "<=").replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/[^\x09\x0a\x0d\x20-\xff–—•°±×µ…]/g, "");

type Res = NonNullable<LeadReply["sims"]>["results"][number];
export type ReportInput = { runId: string; view: LeadReply; events: StudyEvent[] };

/** A canvas at 2× for a figure `w`×`h` pt; `draw` paints in pt. */
function figure(w: number, h: number, draw: (g: CanvasRenderingContext2D) => void) {
  const c = document.createElement("canvas");
  c.width = w * 2; c.height = h * 2;
  const g = c.getContext("2d")!;
  g.scale(2, 2);
  g.fillStyle = "#fff"; g.fillRect(0, 0, w, h);
  g.font = "9px Helvetica, Arial, sans-serif"; g.textBaseline = "middle";
  draw(g);
  return c.toDataURL("image/png");
}

function audiogramFig(ags: Partial<Record<"left" | "right", Record<string, number>>>, aided: string) {
  const W = CW, H = 230, x0 = 52, y0 = 18, w = W - 80, h = H - 58;
  return figure(W, H, (g) => {
    const xOf = (f: number) => x0 + (AG_F.indexOf(f) / (AG_F.length - 1)) * w, yOf = (db: number) => y0 + ((db + 10) / 100) * h;
    g.strokeStyle = C.grid; g.fillStyle = C.muted; g.textAlign = "right";
    for (let db = -10; db <= 90; db += 10) { g.beginPath(); g.moveTo(x0, yOf(db)); g.lineTo(x0 + w, yOf(db)); g.stroke(); g.fillText(`${db}`, x0 - 6, yOf(db)); }
    g.textAlign = "center";
    for (const f of AG_F) { g.beginPath(); g.moveTo(xOf(f), y0); g.lineTo(xOf(f), y0 + h); g.stroke(); g.fillText(hz(f), xOf(f), y0 + h + 12); }
    g.fillText("Frequency (Hz)", x0 + w / 2, y0 + h + 28);
    g.save(); g.translate(14, y0 + h / 2); g.rotate(-Math.PI / 2); g.fillText("Hearing level (dB HL)", 0, 0); g.restore();
    // normal hearing band: 0-20 dB HL
    g.fillStyle = "rgba(42,120,214,0.06)"; g.fillRect(x0, yOf(-10), w, yOf(20) - yOf(-10));
    for (const [ear, col] of [["right", "#c0392b"], ["left", "#2a5bd6"]] as const) {
      const a = ags[ear]; if (!a) continue;
      const pts = AG_F.filter((f) => a[f] !== undefined).map((f) => [xOf(f), yOf(Number(a[f]))] as const);
      g.strokeStyle = col; g.fillStyle = col; g.lineWidth = ear === aided ? 2.2 : 1.2;
      g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.stroke();
      for (const [x, y] of pts) {
        g.beginPath();
        if (ear === "right") g.arc(x, y, 4, 0, 2 * Math.PI); else { g.moveTo(x - 4, y - 4); g.lineTo(x + 4, y + 4); g.moveTo(x + 4, y - 4); g.lineTo(x - 4, y + 4); }
        g.stroke();
      }
    }
    g.textAlign = "left"; g.font = "10px Helvetica, Arial, sans-serif";
    const lx = x0 + w - 150;
    for (const [i, [ear, col, mark]] of ([["right", "#c0392b", "O"], ["left", "#2a5bd6", "X"]] as const).entries()) {
      g.fillStyle = col; g.fillText(`${mark}  ${ear === "left" ? "Left" : "Right"} ear${ear === aided ? " (aided)" : ""}`, lx, y0 + h - 30 + i * 14);
    }
  });
}

function sceneBarsFig(res: Res[], aided: (number | null)[]) {
  const rowH = 16, W = CW, H = 34 + res.length * rowH, x0 = 190, w = W - x0 - 46;
  return figure(W, H, (g) => {
    const xOf = (v: number) => x0 + v * w;
    g.strokeStyle = C.grid; g.fillStyle = C.muted; g.textAlign = "center";
    for (let v = 0; v <= 1.0001; v += 0.25) { g.beginPath(); g.moveTo(xOf(v), 18); g.lineTo(xOf(v), H - 6); g.stroke(); g.fillText(`${v * 100}%`, xOf(v), 9); }
    res.forEach((r, i) => {
      const y = 22 + i * rowH;
      g.fillStyle = C.ink; g.textAlign = "right"; g.fillText(ascii(r.name).slice(0, 34), x0 - 8, y + rowH / 2 - 1);
      const bars: [number, string][] = [[r.sii_healthy, C.normal], [r.sii_unaided, C.you], ...(aided[i] != null ? [[aided[i]!, C.aided] as [number, string]] : [])];
      bars.forEach(([v, col], k) => { g.fillStyle = col; g.fillRect(x0, y + k * 4, Math.max(1, v * w), 3.5); });
      if (aided[i] != null) { const d = aided[i]! - r.sii_unaided; g.fillStyle = d >= 0 ? C.aided : C.you; g.textAlign = "left"; g.fillText(`${d >= 0 ? "+" : ""}${Math.round(d * 100)}`, xOf(1) + 6, y + rowH / 2 - 1); }
    });
  });
}

function deficitFig(res: Res[]) {
  const rowH = 11, W = CW, H = 40 + res.length * rowH, x0 = 190, cw = (W - x0 - 8) / SII_FREQS.length;
  return figure(W, H, (g) => {
    g.textAlign = "center"; g.fillStyle = C.muted;
    SII_FREQS.forEach((f, b) => b % 2 === 0 && g.fillText(hz(f), x0 + (b + 0.5) * cw, 10));
    res.forEach((r, i) => {
      const y = 20 + i * rowH;
      g.fillStyle = C.ink; g.textAlign = "right"; g.font = "8px Helvetica, Arial, sans-serif"; g.fillText(ascii(r.name).slice(0, 36), x0 - 6, y + rowH / 2);
      r.deficit_db.forEach((d, b) => {
        const t = Math.min(1, Math.max(0, d / 30));
        g.fillStyle = `rgb(${Math.round(255 - t * 38)},${Math.round(255 - t * 166)},${Math.round(255 - t * 217)})`;
        g.fillRect(x0 + b * cw + 0.5, y + 0.5, cw - 1, rowH - 1);
      });
    });
    g.fillStyle = C.muted; g.textAlign = "left"; g.font = "9px Helvetica, Arial, sans-serif";
    g.textAlign = "right"; g.fillText("white: nothing lost   ->   deep orange: 30 dB or more lost", W - 8, H - 8);
  });
}

function gainFig(options: NonNullable<LeadReply["options"]>, picked: string | null | undefined, measured?: number[]) {
  const W = CW, H = 210, x0 = 44, y0 = 14, w = W - 64, h = H - 54;
  const all = options.flatMap((o) => o.gain_mean_db).concat(measured ?? []);
  const lo = Math.min(-6, Math.floor(Math.min(...all) / 3) * 3), hi = Math.max(9, Math.ceil(Math.max(...all) / 3) * 3);
  return figure(W, H, (g) => {
    const xOf = (b: number) => x0 + (b / (SII_FREQS.length - 1)) * w, yOf = (v: number) => y0 + ((hi - v) / (hi - lo)) * h;
    g.strokeStyle = C.grid; g.fillStyle = C.muted; g.textAlign = "right";
    for (let v = lo; v <= hi; v += 3) { g.beginPath(); g.moveTo(x0, yOf(v)); g.lineTo(x0 + w, yOf(v)); g.stroke(); g.fillText(`${v}`, x0 - 6, yOf(v)); }
    g.strokeStyle = "#b9b6b0"; g.beginPath(); g.moveTo(x0, yOf(0)); g.lineTo(x0 + w, yOf(0)); g.stroke();
    g.textAlign = "center";
    SII_FREQS.forEach((f, b) => b % 2 === 0 && g.fillText(hz(f), xOf(b), y0 + h + 12));
    g.fillText("Frequency (Hz)", x0 + w / 2, y0 + h + 28);
    g.save(); g.translate(12, y0 + h / 2); g.rotate(-Math.PI / 2); g.fillText("Gain over the open ear (dB)", 0, 0); g.restore();
    const line = (ys: number[], col: string, lw: number, dash: number[] = []) => {
      g.strokeStyle = col; g.lineWidth = lw; g.setLineDash(dash); g.beginPath();
      ys.forEach((v, b) => (b ? g.lineTo(xOf(b), yOf(v)) : g.moveTo(xOf(b), yOf(v)))); g.stroke(); g.setLineDash([]);
    };
    const greys = ["#c9c6c0", "#b3b0aa", "#9d9a94", "#87847e"];
    options.forEach((o, i) => o.id !== picked && line(o.gain_mean_db, greys[i % 4], 1.1));
    const p = options.find((o) => o.id === picked);
    if (p) line(p.gain_mean_db, C.piece, 2.4);
    if (measured) line(measured, C.aided, 1.6, [5, 3]);
    g.textAlign = "left"; g.font = "10px Helvetica, Arial, sans-serif"; g.lineWidth = 1;
    const items: [string, string][] = [["Your earpiece", C.piece], ["Other options", "#9d9a94"], ...(measured ? [["Measured in the 3D wave simulation", C.aided] as [string, string]] : [])];
    items.forEach(([t, col], i) => { g.fillStyle = col; g.fillRect(x0 + 8, y0 + 8 + i * 14, 14, 3); g.fillStyle = C.ink; g.fillText(t, x0 + 28, y0 + 10 + i * 14); });
  });
}

/** Renders through the dashboard's shared WebGL snapshotters; a failed render leaves its slot out, never the report. */
async function render(make: (c: HTMLCanvasElement) => Promise<unknown>, w: number, h: number) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  try { await make(c); } catch { return null; }
  const out = document.createElement("canvas");
  out.width = w; out.height = h;
  const g = out.getContext("2d")!;
  g.fillStyle = "#14161a"; g.fillRect(0, 0, w, h);
  g.drawImage(c, 0, 0);
  return out.toDataURL("image/jpeg", 0.9);
}

/** The lead's written report, split on its CAPITALISED section titles (agents lead._REPORT), keyed by title. */
function sections(text: string) {
  const out: Record<string, string[]> = {};
  let cur = "";
  for (const block of text.split(/\n+/).map((x) => x.trim()).filter(Boolean)) {
    if (/^[A-Z][A-Z0-9 ,'&:()/-]{3,}$/.test(block)) { cur = block.replace(/:$/, ""); out[cur] = []; }
    else (out[cur] ??= []).push(block);
  }
  return out;
}

export async function buildReport({ runId, view, events }: ReportInput): Promise<Blob> {
  const ear = (view.ear ?? "left") as "left" | "right";
  const res = view.sims?.results ?? [];
  const aided = (view.validation as { aided?: (number | null)[] } | null | undefined)?.aided ?? [];
  const options = view.options ?? [];
  const pick = options.find((o) => o.id === view.picked) ?? options[0];
  // the validation's gain is the 3D wave check's ONLY when it differs from the design's own curve: after a failed
  // check it IS that curve, and labelling it "measured" would claim a simulation that never ran
  const vg = (view.validation as { gain_db?: number[] } | null | undefined)?.gain_db;
  const measured = vg && pick && vg.some((v, b) => Math.abs(v - pick.gain_mean_db[b]) > 0.05) ? vg : undefined;
  const pickN = pick ? options.indexOf(pick) + 1 : 0;
  const skin = `/api/patients/${runId}/files/${ear}/ear_skin.glb`, piece = (id: string) => designFile(runId, id, "earpiece.glb", ear);
  const [left, right] = await Promise.all((["left", "right"] as const).map((e) => fetchGrid(runId, e).then((g) => g.patient?.audiogram_db_hl, () => undefined)));
  const ags = { left, right };
  const design = (o: (typeof options)[number]) => (o.recommended ? "Recommended design" : "Alternative design");
  const plain = (r: string) => r.replace(/(:\s*)?\b[Mm]eets \d+ of \d+ key bands,?\s*/g, (_, c) => (c ? ", " : ""));
  const ws = sections(view.report ?? "");
  const llm = (...keys: string[]) => Object.entries(ws).find(([k]) => keys.some((x) => k.includes(x)))?.[1] ?? [];

  // renders: the picked piece in the ear, each option, and the scenes the earpiece changed most
  const inEar = pick ? await render((c) => snapAid(c, runId, ear, skin, piece(pick.id)), 1120, 600) : null;
  const optImgs: (string | null)[] = [];
  for (const o of options) optImgs.push(await render((c) => snapAid(c, runId, ear, skin, piece(o.id)), 560, 300));
  const order = res.map((_, i) => i).sort((a, b) => ((aided[b] ?? 0) - res[b].sii_unaided) - ((aided[a] ?? 0) - res[a].sii_unaided));
  const sceneImgs: { i: number; img: string }[] = [];
  for (const i of order.slice(0, 4)) {
    const sc = view.scenes?.find((x) => x.id === res[i].id);
    if (!sc) continue;
    const img = await render((c) => snapHead(runId, ear === "left", sc.sources, c, DEFAULT_VIEW, pick ? piece(pick.id) : undefined), 560, 400);
    if (img) sceneImgs.push({ i, img });
  }

  // references: each distinct source a finding cites, numbered in order of first citation
  const findings = events.filter((e) => e.type === "research.finding_added");
  const refs: { title: string; url: string }[] = [];
  const cite = (e: StudyEvent) => {
    const d = (e.data ?? {}) as { source_title?: string; source_url?: string };
    if (!d.source_url && !d.source_title) return "";
    let k = refs.findIndex((r) => r.url === (d.source_url ?? "") && r.title === (d.source_title ?? ""));
    if (k < 0) k = refs.push({ title: d.source_title ?? "", url: d.source_url ?? "" }) - 1;
    return ` [${k + 1}]`;
  };

  // ---------------------------------------------------------------- the document
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const L = 58, R = PW - 58, W = R - L, TOP = 74, BOT = PH - 62, SERIF = "times", SANS = "helvetica", LEAD = 14.2, BODY = 10.6;
  const ACCENT = "#1f4e8c";
  const hex = (h: string) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)] as const;
  const ink = (h: string) => doc.setTextColor(...hex(h));
  const fill = (h: string) => doc.setFillColor(...hex(h));
  const stroke = (h: string) => doc.setDrawColor(...hex(h));
  let y = TOP, figN = 0, tabN = 0, secN = 0, subN = 0;
  const toc: { label: string; page: number; level: number }[] = [];
  const page = () => doc.getNumberOfPages();
  const newPage = () => { doc.addPage(); y = TOP; };
  const need = (h: number) => { if (y + h > BOT) newPage(); };

  const para = (t: string, opt: { size?: number; gap?: number; indent?: number; color?: string; font?: string } = {}) => {
    const size = opt.size ?? BODY, x = L + (opt.indent ?? 0), w = W - (opt.indent ?? 0), lead = size * 1.36;
    doc.setFont(opt.font ?? SERIF, "normal"); doc.setFontSize(size); ink(opt.color ?? C.ink);
    const lines = doc.splitTextToSize(ascii(t), w) as string[];
    lines.forEach((ln, i) => {
      need(lead);
      // justified like a printed report, except a paragraph's last line
      if (i < lines.length - 1 && ln.includes(" ")) doc.text(ln, x, y + size, { align: "justify", maxWidth: w }); else doc.text(ln, x, y + size);
      y += lead;
    });
    y += opt.gap ?? 7;
  };
  const bullet = (t: string, ref = "") => {
    doc.setFont(SERIF, "normal"); doc.setFontSize(BODY); ink(C.ink);
    const lines = doc.splitTextToSize(ascii(t + ref), W - 16) as string[];
    lines.forEach((ln, i) => { need(LEAD); if (i === 0) doc.text("•", L + 4, y + BODY); doc.text(ln, L + 16, y + BODY); y += LEAD; });
    y += 3;
  };
  /** A numbered section on a fresh line; `keep` holds what follows with it so a title never ends a page. */
  const h1 = (title: string, keep = 130) => {
    secN++; subN = 0;
    need(46 + keep); y += 14;
    doc.setFont(SANS, "bold"); doc.setFontSize(15); ink(ACCENT); doc.text(`${secN}.  ${title}`, L, y + 15);
    y += 22; stroke(ACCENT); doc.setLineWidth(0.8); doc.line(L, y, R, y); y += 12;
    toc.push({ label: `${secN}.  ${title}`, page: page(), level: 0 });
  };
  const h2 = (title: string, keep = 60) => {
    subN++;
    need(30 + keep); y += 6;
    doc.setFont(SANS, "bold"); doc.setFontSize(11.5); ink(C.ink); doc.text(`${secN}.${subN}  ${ascii(title)}`, L, y + 11.5);
    y += 20;
    toc.push({ label: `${secN}.${subN}  ${ascii(title)}`, page: page(), level: 1 });
  };
  const caption = (kind: "Figure" | "Table", n: number, t: string) => {
    doc.setFont(SANS, "bold"); doc.setFontSize(8.6); ink(C.ink);
    const lab = `${kind} ${n}.  `, lw = doc.getTextWidth(lab);
    doc.text(lab, L, y + 9);
    doc.setFont(SANS, "normal"); ink(C.muted);
    const lines = doc.splitTextToSize(ascii(t), W - lw) as string[];
    lines.forEach((ln, i) => doc.text(ln, L + lw, y + 9 + i * 11));
    y += lines.length * 11 + 4;
  };
  const fig = (src: string, w: number, h: number, cap: string, x = L + (W - w) / 2) => {
    need(h + 34);
    doc.addImage(src, src.startsWith("data:image/jpeg") ? "JPEG" : "PNG", x, y, w, h);
    y += h + 6; caption("Figure", ++figN, cap); y += 8;
  };
  /** A ruled table with a shaded header that repeats on a new page; numbers right-aligned. */
  const table = (cols: { h: string; w: number; right?: boolean }[], rows: string[][], cap: string) => {
    const tw = cols.reduce((a, c) => a + c.w, 0), sc = W / tw, rh = 15, hh = 19;
    need(hh + rh * Math.min(rows.length, 4) + 26);
    caption("Table", ++tabN, cap); y += 2;
    const head = () => {
      fill("#e9edf3"); doc.rect(L, y, W, hh, "F");
      doc.setFont(SANS, "bold"); doc.setFontSize(8.4); ink(C.ink);
      let x = L;
      for (const c of cols) { const cw = c.w * sc; doc.text(ascii(c.h), c.right ? x + cw - 5 : x + 5, y + 12.5, c.right ? { align: "right" } : undefined); x += cw; }
      y += hh;
    };
    head();
    rows.forEach((r, k) => {
      if (y + rh > BOT) { stroke("#c9ced6"); doc.line(L, y, R, y); newPage(); head(); }
      if (k % 2) { fill("#f7f8fa"); doc.rect(L, y, W, rh, "F"); }
      doc.setFont(SANS, "normal"); doc.setFontSize(8.4); ink(C.ink);
      let x = L;
      cols.forEach((c, j) => { const cw = c.w * sc; const t = ascii(r[j] ?? ""); doc.text(doc.splitTextToSize(t, cw - 10)[0] as string, c.right ? x + cw - 5 : x + 5, y + 10.5, c.right ? { align: "right" } : undefined); x += cw; });
      y += rh;
    });
    stroke("#c9ced6"); doc.setLineWidth(0.6); doc.line(L, y, R, y); y += 16;
  };
  const writeup = (ps: string[]) => ps.forEach((p) => (/^[-•*]\s/.test(p) ? bullet(p.replace(/^[-•*]\s+/, "")) : para(p)));

  const meanN = mean(res.map((r) => r.sii_healthy)), meanU = mean(res.map((r) => r.sii_unaided)), meanA = aided.length ? mean(aided.map((v) => v ?? 0)) : null;
  const date = new Date().toLocaleDateString("en-GB", { year: "numeric", month: "long", day: "numeric" });
  const pts = (v: number) => `${v >= 0 ? "+" : ""}${Math.round(v * 100)} pts`;

  // ---- title page
  fill(ACCENT); doc.rect(0, 0, 14, PH, "F");
  doc.setFont(SANS, "normal"); doc.setFontSize(10); ink(C.muted); doc.text("AURIS  ·  DESIGN AND SIMULATION REPORT", L, 110);
  doc.setFont(SERIF, "bold"); doc.setFontSize(30); ink(C.ink);
  doc.text(doc.splitTextToSize("Personalised Passive Hearing Aid", W) as string[], L, 158);
  doc.setFont(SERIF, "normal"); doc.setFontSize(16); ink("#3d424a");
  doc.text(`Design, simulation and validation for the ${ear} ear`, L, 186);
  stroke(ACCENT); doc.setLineWidth(1.2); doc.line(L, 206, L + 120, 206);
  y = 232;
  const meta: [string, string][] = [["Session", runId], ["Date", date], ["Aided ear", ear === "left" ? "Left" : "Right"],
    ["Selected design", pick ? `Option ${pickN}, ${design(pick).replace(/^\w/, (c) => c.toUpperCase())}` : "None"],
    ["Scenes simulated", String(res.length)]];
  meta.forEach(([k, v]) => { doc.setFont(SANS, "bold"); doc.setFontSize(9.5); ink(C.muted); doc.text(k.toUpperCase(), L, y); doc.setFont(SANS, "normal"); doc.setFontSize(11); ink(C.ink); doc.text(ascii(v), L + 130, y); y += 19; });
  y += 14;
  // key results panel
  fill("#f4f6f9"); doc.rect(L, y, W, 92, "F");
  doc.setFont(SANS, "bold"); doc.setFontSize(9); ink(ACCENT); doc.text("KEY RESULTS: SPEECH AUDIBILITY (SII), MEAN OVER ALL SCENES", L + 14, y + 20);
  const stats: [string, string, string][] = [["Normal hearing", pct(meanN), C.normal], ["Without the earpiece", pct(meanU), C.you], ...(meanA !== null ? [["With the earpiece", pct(meanA), C.aided] as [string, string, string]] : [])];
  stats.forEach(([label, v, col], i) => {
    const x = L + 14 + i * ((W - 28) / stats.length);
    doc.setFont(SANS, "bold"); doc.setFontSize(26); ink(col); doc.text(v, x, y + 58);
    doc.setFont(SANS, "normal"); doc.setFontSize(9); ink(C.muted); doc.text(label, x, y + 76);
  });
  y += 110;
  if (inEar) { const ih = (W * 600) / 1120; doc.addImage(inEar, "JPEG", L, y, W, ih); y += ih + 8; doc.setFont(SANS, "normal"); doc.setFontSize(8.5); ink(C.muted); doc.text("The selected earpiece seated in the patient's reconstructed ear (left) and on its own (right).", L, y + 6); }
  doc.setFont(SANS, "italic"); doc.setFontSize(8.5); ink(C.muted);
  doc.text(doc.splitTextToSize("All results in this report come from computer simulations of the patient's ear, head and listening scenes. They are not clinical measurements and are not a diagnosis. Consult an audiologist before relying on any hearing device.", W) as string[], L, PH - 70);

  // ---- contents (filled once every page number is known)
  newPage();
  const tocPage = page();

  // ---- 1 summary
  newPage();
  h1("Executive summary");
  writeup(llm("SUMMARY").length ? llm("SUMMARY") : [view.sims?.summary ?? ""]);
  table([{ h: "Measure", w: 3 }, { h: "Result", w: 2, right: true }], [
    ["Listening scenes simulated", String(res.length)],
    ["Speech audibility, normal hearing", pct(meanN)],
    ["Speech audibility, patient without the earpiece", pct(meanU)],
    ...(meanA !== null ? [["Speech audibility, patient with the earpiece", pct(meanA)], ["Change from the earpiece", pts(meanA - meanU)]] : []),
    ["Selected design", pick ? `Option ${pickN} of ${options.length}` : "-"],
  ], "Headline results. Speech audibility is the ANSI S3.5 Speech Intelligibility Index, averaged over every simulated scene.");

  // ---- 2 hearing
  h1("Hearing assessment", 250);
  fig(audiogramFig(ags, ear), W, (W * 230) / CW, "Pure-tone thresholds by ear. Lower on the chart is worse hearing; the shaded band (0 to 20 dB HL) is the normal range.");
  writeup(llm("HEARING TEST"));
  table([{ h: "Frequency (Hz)", w: 2 }, { h: "Left ear (dB HL)", w: 2, right: true }, { h: "Right ear (dB HL)", w: 2, right: true }],
    AG_F.map((f) => [String(f), left?.[f] !== undefined ? String(left[f]) : "-", right?.[f] !== undefined ? String(right[f]) : "-"]),
    "Hearing thresholds used for every simulation in this report.");

  // ---- 3 context
  const told = llm("TOLD US");
  if (told.length) { h1("Patient context"); writeup(told); }

  // ---- 4 research
  if (findings.length || llm("RESEARCH").length) {
    h1("Research review");
    writeup(llm("RESEARCH"));
    const by = new Map<string, StudyEvent[]>();
    for (const e of findings) by.set(e.component, [...(by.get(e.component) ?? []), e]);
    if (findings.length) para(`Four research agents reviewed the literature for this patient; ${findings.length} sourced findings were recorded. Each is listed below with its reference.`, { gap: 6 });
    for (const [who, es] of by) {
      h2(who.replace(/_/g, " ").replace(/\bresearch\b/i, "").trim().replace(/^\w/, (c) => c.toUpperCase()) + " research", 40);
      for (const e of es) bullet(`${e.summary.trim()}${/[.!?)]$/.test(e.summary.trim()) ? "" : "…"}`, cite(e));
    }
  }

  // ---- 5 methods (what the pipeline does, from the code, not the model)
  h1("Methods");
  h2("Ear and head reconstruction");
  para("Each ear was reconstructed in 3D from a photograph, and the head was modelled from a face photograph, giving a head that wears both of the patient's own ears. The earpiece is built on the same ear mesh, so the renders in this report show the device exactly where it would sit.");
  h2("Listening simulations");
  para(`${res.length} everyday listening scenes were simulated. In each, recorded sounds (a talker and, in some scenes, background noise) play from set directions and distances around the head. A finite-difference time-domain wave simulation of the head and both ears gives the sound reaching each eardrum, band by band.`);
  h2("Speech audibility");
  para("Audibility is scored with the Speech Intelligibility Index (ANSI S3.5-1997) on one-third-octave bands, using the patient's own thresholds for the impaired ear and 0 dB HL for normal hearing. A score of 100% means every speech band is fully audible.");
  h2("Earpiece design");
  para("Thousands of passive horn geometries were swept and scored with a one-dimensional acoustic model over the sampled ear-canal lengths, against the gain the scenes call for, weighted by where speech is lost. The four best buildable designs, distinct in shape, were built on the ear mesh and offered.");
  h2("Validation");
  para(measured
    ? "The selected earpiece was voxelised into a 3D wave simulation of the ear to measure its insertion gain, and every scene was scored again with that gain applied."
    : "Every scene was scored again with the selected earpiece's insertion gain applied, as predicted by the acoustic model.");

  // ---- 6 results
  if (res.length) {
    h1("Listening simulation results", 200);
    writeup(llm("LISTENING SIMULATIONS", "SIMULATIONS"));
    fig(sceneBarsFig(res, aided), W, ((34 + res.length * 16) * W) / CW, "Speech audibility per scene: normal hearing (grey), the patient without the earpiece (orange) and with it (blue). The figure at the right is the change in points.");
    table([{ h: "Scene", w: 5 }, { h: "Weight", w: 1.1, right: true }, { h: "Normal", w: 1.2, right: true }, { h: "Without", w: 1.2, right: true }, { h: "With", w: 1.2, right: true }, { h: "Change", w: 1.3, right: true }],
      res.map((r, i) => [r.name, String(r.weight), pct(r.sii_healthy), pct(r.sii_unaided), pct(aided[i]), aided[i] != null ? pts(aided[i]! - r.sii_unaided) : "-"]),
      "Speech audibility per scene. Weight is how much the scene matters to the patient (1 to 5).");
    fig(deficitFig(res), W, ((40 + res.length * 11) * W) / CW, "Audibility lost to the hearing loss, per scene and frequency band. The design targets the deepest-coloured regions.");
  }

  // ---- 7 options
  if (options.length) {
    h1("Design options", 220);
    writeup(llm("FOUR DESIGNS", "DESIGNS"));
    fig(gainFig(options, pick?.id, measured), W, (W * 210) / CW, "Insertion gain of each design by frequency, averaged over the sampled ear canals. The selected design is in orange" + (measured ? "; the dashed line is its gain measured in the 3D wave simulation." : "."));
    const at = (o: (typeof options)[number], f: number) => { const b = SII_FREQS.indexOf(f); return `${o.gain_mean_db[b] >= 0 ? "+" : ""}${o.gain_mean_db[b].toFixed(1)}`; };
    table([{ h: "Option", w: 1.4 }, { h: "Design", w: 4.2 }, { h: "1 kHz", w: 1.1, right: true }, { h: "2 kHz", w: 1.1, right: true }, { h: "4 kHz", w: 1.1, right: true }, { h: "8 kHz", w: 1.1, right: true }],
      options.map((o, i) => [`${i + 1}${o.id === pick?.id ? " (selected)" : ""}`, design(o), at(o, 1000), at(o, 2000), at(o, 4000), at(o, 8000)]),
      "Insertion gain (dB) of each option at representative frequencies. Positive values are gain over the open ear.");
    const cw = (W - 14) / 2, ch = (cw * 300) / 560;
    need(ch * 2 + 60);
    optImgs.forEach((img, i) => {
      const x = L + (i % 2) * (cw + 14), yy = y + Math.floor(i / 2) * (ch + 20);
      if (img) doc.addImage(img, "JPEG", x, yy, cw, ch);
      doc.setFont(SANS, i + 1 === pickN ? "bold" : "normal"); doc.setFontSize(8.5); ink(i + 1 === pickN ? ACCENT : C.ink);
      doc.text(`Option ${i + 1}${i + 1 === pickN ? " (selected)" : ""}`, x, yy + ch + 11);
    });
    y += Math.ceil(optImgs.length / 2) * (ch + 20) + 4;
    caption("Figure", ++figN, "Each option seated in the patient's reconstructed ear (left of each panel) and on its own (right)."); y += 8;
  }

  // ---- 8 selected design
  if (pick) {
    h1("Selected design", 200);
    writeup(llm("PICKED"));
    if (inEar) fig(inEar, W, (W * 600) / 1120, "The selected earpiece in the patient's ear and on its own, from the printable 3D model.");
    para(plain(pick.reason), { font: SANS, size: 9.5, color: "#3d424a" });
  }

  // ---- 9 validation
  if (aided.length) {
    h1("Validation", 200);
    writeup(llm("HOW MUCH", "HELPS"));
    if (sceneImgs.length) {
      const cw = (W - 14) / 2, ch = (cw * 400) / 560;
      need(ch * 2 + 70);
      sceneImgs.forEach(({ i, img }, k) => {
        const x = L + (k % 2) * (cw + 14), yy = y + Math.floor(k / 2) * (ch + 32);
        doc.addImage(img, "JPEG", x, yy, cw, ch);
        doc.setFont(SANS, "bold"); doc.setFontSize(8.5); ink(C.ink); doc.text(ascii(res[i].name).slice(0, 52), x, yy + ch + 11);
        doc.setFont(SANS, "normal"); ink(C.muted); doc.text(`without ${pct(res[i].sii_unaided)}  ->  with ${pct(aided[i])}  (normal ${pct(res[i].sii_healthy)})`, x, yy + ch + 22);
      });
      y += Math.ceil(sceneImgs.length / 2) * (ch + 32) + 4;
      caption("Figure", ++figN, "The scenes the earpiece changes most: the measurement setup with the patient's head and ears, the sound sources, and the earpiece (orange) in the aided ear."); y += 8;
    }
  }

  // ---- 10, 11
  h1("Limitations");
  writeup(llm("LIMIT").length ? llm("LIMIT") : ["These results are simulations, not clinical measurements. A passive device cannot add energy; it can only redirect sound, so its gain is small and narrow. Fit, canal shape and placement vary from the model."]);
  h1("Recommendations and next steps");
  writeup(llm("NEXT"));

  // ---- references
  if (refs.length) {
    h1("References", 40);
    refs.forEach((r, k) => {
      doc.setFont(SERIF, "normal"); doc.setFontSize(9.6); ink(C.ink);
      const lines = doc.splitTextToSize(ascii(r.title || r.url), W - 26) as string[];
      need(lines.length * 12.5 + 14);
      doc.text(`[${k + 1}]`, L, y + 9.6);
      lines.forEach((ln, i) => doc.text(ln, L + 26, y + 9.6 + i * 12.5));
      y += lines.length * 12.5;
      if (r.url) { doc.setFont(SANS, "normal"); doc.setFontSize(8); ink(ACCENT); doc.textWithLink(ascii(r.url).slice(0, 110), L + 26, y + 8, { url: r.url }); y += 12; }
      y += 5;
    });
  }

  // ---- appendix: the full gain table, on its own page
  if (options.length) {
    newPage();
    h1("Appendix A: insertion gain by band", 120);
    table([{ h: "Band (Hz)", w: 1.6 }, ...options.map((o, i) => ({ h: `Option ${i + 1}${o.id === pick?.id ? " *" : ""}`, w: 1.4, right: true }))],
      SII_FREQS.map((f, b) => [String(f), ...options.map((o) => o.gain_mean_db[b].toFixed(1))]),
      "Mean insertion gain (dB) of every option on each one-third-octave band. * the selected design.");
  }

  // ---- contents, headers and footers now that pages are known
  const n = page();
  doc.setPage(tocPage); y = TOP;
  doc.setFont(SANS, "bold"); doc.setFontSize(18); ink(ACCENT); doc.text("Contents", L, y + 18); y += 40;
  for (const t of toc) {
    const x = L + (t.level ? 18 : 0);
    doc.setFont(t.level ? SERIF : SANS, t.level ? "normal" : "bold"); doc.setFontSize(t.level ? 10 : 10.5); ink(C.ink);
    doc.text(t.label, x, y);
    const pn = String(t.page), pw = doc.getTextWidth(pn), lw = doc.getTextWidth(t.label);
    doc.setTextColor(170, 170, 170); doc.text(".".repeat(Math.max(0, Math.floor((R - pw - 6 - (x + lw + 6)) / doc.getTextWidth(".")))), x + lw + 4, y);
    ink(C.ink); doc.text(pn, R, y, { align: "right" });
    y += t.level ? 15 : 20;
    if (y > BOT) break;
  }
  for (let p = 2; p <= n; p++) {
    doc.setPage(p);
    doc.setFont(SANS, "normal"); doc.setFontSize(8); ink(C.muted);
    doc.text("Personalised passive hearing aid  ·  design and simulation report", L, 40);
    doc.text(`Session ${runId}`, R, 40, { align: "right" });
    stroke("#d5d9df"); doc.setLineWidth(0.5); doc.line(L, 47, R, 47);
    doc.line(L, PH - 44, R, PH - 44);
    doc.text("Auris  ·  simulation results, not a clinical measurement", L, PH - 30);
    doc.text(`Page ${p} of ${n}`, R, PH - 30, { align: "right" });
  }
  return doc.output("blob");
}

/** Saves a blob under `name` through a temporary link (the browser's own download, no dialog). */
export function save(blob: Blob, name: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}
