import { test, expect } from "@playwright/test";

// Catches any figure of the opened scene leaving the timeline. Moves the clip playhead and requires every backend viewer
// (a head wavefronts, b and d one-ear slices) to report EXACTLY the page's t, with the pixel fields c and e alongside.
// Needs this repo's backend (SIM_BACKEND, default localhost:8001) with patient 63dc5db647b1; every /api call is routed there.
const BACKEND = process.env.SIM_BACKEND ?? "http://localhost:8001";

test("every figure follows the clip timeline", async ({ page, request }) => {
  test.setTimeout(300_000);
  const ok = await request.get(`${BACKEND}/api/patients/63dc5db647b1/waves/right/runs.json`).then((r) => r.ok(), () => false);
  test.skip(!ok, `no sim backend with patient 63dc5db647b1 at ${BACKEND}`);
  await page.route(/\/api\//, async (route) => {
    const u = new URL(route.request().url());
    route.fulfill({ response: await route.fetch({ url: `${BACKEND}${u.pathname}${u.search}` }) });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/zz-preview/sim-lab?pid=63dc5db647b1&ear=right");
  await expect(page.locator("[data-testid=sim-tile][data-done]")).toHaveCount(3, { timeout: 180_000 });
  await page.getByTestId("sim-tile").nth(2).click();     // Busy cafe: talker at 45° on the right
  const d = page.getByTestId("sim-detail");
  for (const id of ["sim-3d", "sim-ear"]) await expect(d.getByTestId(id)).toBeVisible();
  await expect(d.getByTestId("sim-slice")).toBeVisible({ timeout: 120_000 });

  const label = d.getByText(/^t = [\d.]+ ms/);
  const viewers = ["sim-3d", "sim-ear"].map((id) => page.frameLocator(`[data-testid=${id}]`).locator("#time"));
  for (const v of viewers) await expect(v).toHaveText(/into the clip/, { timeout: 60_000 });
  const clip = d.getByTestId("clip-timeline"), box = (await clip.boundingBox())!;
  for (const f of [0.35, 0.7]) {
    await page.mouse.click(box.x + box.width * f, box.y + box.height / 2);
    const ms = (await label.textContent())!.match(/t = ([\d.]+) ms/)![1];
    for (const v of viewers) await expect(v).toHaveText(`t = ${ms} ms into the clip`);
  }
  // slow motion: still the SAME instant everywhere, a moment later
  await d.getByTestId("play-slow").click();
  await page.waitForTimeout(2500);
  await d.getByTestId("play-slow").click();
  const ms = (await label.textContent())!.match(/t = ([\d.]+) ms/)![1];
  for (const v of viewers) await expect(v).toHaveText(`t = ${ms} ms into the clip`);
  await page.waitForTimeout(1500);
  await page.screenshot({ path: test.info().outputPath("synced.png") });
});
