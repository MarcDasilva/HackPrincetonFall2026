import { test, expect, type Locator, type Page } from "@playwright/test";
import sharp from "sharp";

/** Pixels whose colour moved by more than 60 (sum over RGB) between two screenshots. */
async function changed(a: Buffer, b: Buffer) {
  const [x, y] = await Promise.all([a, b].map((p) => sharp(p).raw().toBuffer()));
  let n = 0;
  for (let i = 0; i < x.length; i += 4) if (Math.abs(x[i] - y[i]) + Math.abs(x[i + 1] - y[i + 1]) + Math.abs(x[i + 2] - y[i + 2]) > 60) n++;
  return n;
}

// Catches a preview ignoring middle-drag, or a middle-drag on a tile opening the scene: every preview (tile rigs, the
// pixel fields, the backend's 3D viewers) moves with a middle-button drag. The viewers need this repo's backend
// (SIM_BACKEND, default localhost:8001); every /api call is routed there when it is up.
const BACKEND = process.env.SIM_BACKEND ?? "http://localhost:8001";

async function middleDrag(page: Page, el: Locator) {
  const b = (await el.boundingBox())!;
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  await page.mouse.down({ button: "middle" });
  await page.mouse.move(b.x + b.width / 2 + 60, b.y + b.height / 2 + 40, { steps: 8 });
  await page.mouse.up({ button: "middle" });
  await page.waitForTimeout(800);
}

test("middle-drag moves every preview", async ({ page, request }) => {
  test.setTimeout(300_000);
  const up = await request.get(`${BACKEND}/api/patients/63dc5db647b1/waves/right/runs.json`).then((r) => r.ok(), () => false);
  if (up) await page.route(/\/api\//, async (route) => {
    const u = new URL(route.request().url());
    route.fulfill({ response: await route.fetch({ url: `${BACKEND}${u.pathname}${u.search}` }) });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/zz-preview/sim-lab?pid=63dc5db647b1&ear=right");
  await expect(page.locator("[data-testid=sim-tile][data-done]")).toHaveCount(3, { timeout: 180_000 });

  // tile: the rig moves and the scene does NOT open
  const rig = page.getByTestId("sim-tile").nth(2).locator("canvas");
  const before = await rig.screenshot();
  await middleDrag(page, rig);
  expect((await rig.screenshot()).equals(before)).toBe(false);
  await expect(page.getByTestId("sim-detail")).toHaveCount(0);

  await page.getByTestId("sim-tile").nth(2).click();
  const d = page.getByTestId("sim-detail");
  // pixel field c: its window slides over the slice (stopped clock, so only the pan can change it)
  const c = d.getByTestId("sim-slice");
  await expect(c).toBeVisible({ timeout: 120_000 });
  const field = () => c.evaluate((el: HTMLCanvasElement) => el.toDataURL());
  await expect.poll(async () => { const x = await field(); await page.waitForTimeout(1500); return x === (await field()); }, { timeout: 180_000 }).toBe(true);
  const f0 = await field();
  await middleDrag(page, c);
  expect(await field()).not.toEqual(f0);

  // the backend's 3D viewers: the camera pans
  test.skip(!up, `no sim backend with patient 63dc5db647b1 at ${BACKEND}`);
  for (const id of ["sim-3d", "sim-ear"]) {
    const frame = d.getByTestId(id);
    await expect(page.frameLocator(`[data-testid=${id}]`).locator("#time")).toHaveText(/into the clip/, { timeout: 60_000 });
    // A viewer inside the page flickers a scatter of pixels frame to frame, so count changed pixels: the pan must move
    // far more of the picture than sitting still does.
    await page.waitForTimeout(1500);
    const v0 = await frame.screenshot();
    await page.waitForTimeout(800);
    const idle = await changed(v0, await frame.screenshot());
    await middleDrag(page, frame);
    const moved = await changed(v0, await frame.screenshot());
    expect(moved, `${id}: pixels changed by the pan vs ${idle} sitting still`).toBeGreaterThan(Math.max(5 * idle, 2000));
  }
  await page.screenshot({ path: test.info().outputPath("panned.png") });
});
