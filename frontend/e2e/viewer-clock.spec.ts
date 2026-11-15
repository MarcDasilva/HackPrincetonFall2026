import { test, expect, type Page } from "@playwright/test";

// Catches the backend's wave viewers drifting off the sim page's timeline. Driven by a clip (postMessage), a viewer must
// show the clip at the page's t and NOTHING else: the same t repaints the same picture, a different t a different one,
// and its own animation loop stays off. Needs this repo's backend (SIM_BACKEND, default localhost:8001) with patient 63dc5db647b1.
const BACKEND = process.env.SIM_BACKEND ?? "http://localhost:8001";
const PID = "63dc5db647b1";

async function drive(page: Page, url: string) {
  await page.goto(url);
  await page.locator("canvas").first().waitFor();
  await page.waitForTimeout(4000);      // frames fetched and decoded
  // a 2 s two-tone clip at 24 kHz, sent the way Analysis does
  await page.evaluate(() => {
    const sr = 24000, u = new Float32Array(sr * 2);
    for (let i = 0; i < u.length; i++) u[i] = Math.sin((2 * Math.PI * 2000 * i) / sr) + 0.5 * Math.sin((2 * Math.PI * 4500 * i) / sr);
    window.postMessage({ type: "auris-clip", u, sr, t: 0.5 }, "*");
  });
  // embedded viewers hide their caption, so read its text rather than look for it
  await expect(page.locator("#time")).toHaveText(/ms into the clip/, { timeout: 30_000 });
  const at = async (t: number) => { await page.evaluate((x) => window.postMessage({ type: "auris-t", t: x }, "*"), t); await page.waitForTimeout(700); return page.locator("canvas").first().screenshot(); };
  const a = await at(0.5), b = await at(0.50013), c = await at(0.5);
  expect(c.equals(a), "the same t repaints the same picture").toBe(true);
  expect(b.equals(a), "a different t paints a different picture").toBe(false);
  await page.screenshot({ path: test.info().outputPath(`${url.includes("head") ? "head" : "ear"}.png`) });
}

test.beforeAll(async ({ request }) => {
  const ok = await request.get(`${BACKEND}/api/patients/${PID}/waves/right/runs.json`).then((r) => r.ok(), () => false);
  test.skip(!ok, `no sim backend with patient ${PID} at ${BACKEND}`);
});

test("one-ear slices follow the clip clock", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 700, height: 700 });
  await drive(page, `${BACKEND}/api/patients/${PID}/waves/right/index.html?embed=1&run=az045_el%2B00&disp=slices`);
});

test("head wavefronts follow the clip clock", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 700, height: 700 });
  await drive(page, `${BACKEND}/api/patients/${PID}/head/viewer.html?embed=1&run=az045_el%2B00&rig=1&ear=right`);
});
