import fs from "node:fs";
import type { Page } from "@playwright/test";

const CORS = { "access-control-allow-origin": "*" };
export const PID = "abc123abc123";
// 1x1 PNG: the views only need an image that decodes.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

/** Stands in for backend/app/main.py: POST starts a job, GET reports it running with the ear stage's three files and the head stage's files already written. `head: false` is a patient from before the head stage (no files.head). A spec that sends WITHOUT this would hit whatever is on :8000. */
export async function mockBackend(page: Page, opts: { onPost?: (body: string) => void; postDelayMs?: number; head?: boolean } = {}) {
  // Grouped by ear, as GET /api/patients/{id} returns them for a two-ear patient.
  const files: Record<string, Record<string, string>> = Object.fromEntries(["left", "right"].map((ear) => [ear, Object.fromEntries(["overlay.jpg", "mask.png", "ear.glb"].map((f) => [f, `/api/patients/${PID}/files/${ear}/${f}`]))]));
  if (opts.head !== false) files.head = { ...Object.fromEntries(["landmarks.jpg", "head.glb", "head_ears.glb", "head.json"].map((f) => [f, `/api/patients/${PID}/files/head/${f}`])), viewer: `/api/patients/${PID}/head/viewer.html` };
  await page.route("**/api/patients", async (route) => {
    opts.onPost?.(route.request().postDataBuffer()?.toString("latin1") ?? "");
    // The attachments are only consumed once the POST resolves; a delay keeps them (and their blob URLs) readable.
    if (opts.postDelayMs) await new Promise((r) => setTimeout(r, opts.postDelayMs));
    return route.fulfill({ status: 202, contentType: "application/json", headers: CORS, body: JSON.stringify({ id: PID }) });
  });
  await page.route(`**/api/patients/${PID}`, (route) =>
    route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ status: "running", step: "context", files }) }));
  // The lead opens when the ear cards vanish; WITHOUT this stub every spec that sends would call the real agents server (and the model) on :8010. lead.spec.ts registers its own handler after this one, which wins.
  await page.route(`**/lead/${PID}`, (route) =>
    route.request().method() === "OPTIONS"
      ? route.fulfill({ headers: { ...CORS, "access-control-allow-headers": "*" } })
      : route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: "stub", awaiting_launch: false, launch_requested: false }) }));
  await page.route(`**/api/patients/${PID}/files/**`, (route) =>
    route.request().url().endsWith(".glb") ? route.fulfill({ status: 404, headers: CORS }) : route.fulfill({ contentType: "image/png", headers: CORS, body: PNG }));
}

/** Dev shortcut, step 1: turn Caps Lock ON (attaches the practice ear and fake hearing test). Playwright's keyboard cannot toggle Caps Lock, so send the keydown with that modifier state. */
export const capsOn = (page: Page) =>
  page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "CapsLock", modifierCapsLock: true, cancelable: true })));

const AGENT_KEYS = ["hearing_research", "use_context_research", "acoustic_design_research", "ear_fit_research"];

/** Stands in for GET /lead/{id}/events on the agents server: every investigator has started, searched, read and recorded a finding; ear fit has finished. Without it the boxes would poll the real agents server on :8010. */
export async function mockStudy(page: Page) {
  let seq = 0;
  const at = (s: number) => new Date(Date.UTC(2026, 10, 14, 12, 0, s)).toISOString();
  const ev = (component: string, type: string, summary: string, data?: object) => ({ sequence: ++seq, timestamp: at(seq), type, component, summary, data });
  const events = AGENT_KEYS.flatMap((k) => [
    ev(k, "research.agent_started", `The ${k} investigator started`),
    ev(k, "research.searched", `${k} search query (6 results)`),
    ev(k, "research.source_read", `Read: A paper for ${k}`),
    ev(k, "research.finding_added", `Finding from ${k}`),
    ev(k, "research.board_posted", `Board post from ${k}`, { investigator: k, headline: `Board post from ${k}`, detail: "Why it matters." }),
    ...(k === "ear_fit_research" ? [ev(k, "research.agent_completed", "The ear-fit investigator finished with 1 finding(s).", { summary: "A concha lock holds while running." })] : []),
  ]);
  await page.route("**/lead/*/events", (route) => route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ status: "running", events }) }));
}

/** Any reconstructed head in this checkout's backend/data (local, never committed); null without one. */
export function localHead() {
  const dir = "../backend/data/patients";
  const pid = fs.existsSync(dir) ? fs.readdirSync(dir).find((p) => fs.existsSync(`${dir}/${p}/head/head_ears.glb`)) : undefined;
  return pid ? `${dir}/${pid}/head/head_ears.glb` : null;
}
