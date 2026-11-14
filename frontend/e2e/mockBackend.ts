import type { Page } from "@playwright/test";

const CORS = { "access-control-allow-origin": "*" };
export const PID = "abc123abc123";
// 1x1 PNG: the views only need an image that decodes.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

/** Stands in for backend/app/main.py: POST starts a job, GET reports it running with the ear stage's three files already written. A spec that sends WITHOUT this would hit whatever is on :8000. */
export async function mockBackend(page: Page, opts: { onPost?: (body: string) => void; postDelayMs?: number } = {}) {
  const files = Object.fromEntries(["overlay.jpg", "mask.png", "ear.glb"].map((f) => [f, `/api/patients/${PID}/files/${f}`]));
  await page.route("**/api/patients", async (route) => {
    opts.onPost?.(route.request().postDataBuffer()?.toString("latin1") ?? "");
    // The attachments are only consumed once the POST resolves; a delay keeps them (and their blob URLs) readable.
    if (opts.postDelayMs) await new Promise((r) => setTimeout(r, opts.postDelayMs));
    return route.fulfill({ status: 202, contentType: "application/json", headers: CORS, body: JSON.stringify({ id: PID }) });
  });
  await page.route(`**/api/patients/${PID}`, (route) =>
    route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ status: "running", step: "context", files }) }));
  await page.route(`**/api/patients/${PID}/files/*`, (route) =>
    route.request().url().endsWith(".glb") ? route.fulfill({ status: 404, headers: CORS }) : route.fulfill({ contentType: "image/png", headers: CORS, body: PNG }));
}

/** Dev shortcut, step 1: turn Caps Lock ON (attaches the practice ear and fake hearing test). Playwright's keyboard cannot toggle Caps Lock, so send the keydown with that modifier state. */
export const capsOn = (page: Page) =>
  page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "CapsLock", modifierCapsLock: true, cancelable: true })));
