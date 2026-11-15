import { test, expect } from "@playwright/test";

// Catches the opened scene losing its analysis: the clip's two timelines, the wave field that follows the clip, and the
// charts that read the playhead. Also the tiles' whole-clip strip. Runs on the preview's average ear (no backend needed).
test("sim analysis: clip and slow-motion timelines drive the field and the charts", async ({ page }) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/zz-preview/sim-lab");
  await expect(page.locator("[data-testid=sim-tile][data-done]")).toHaveCount(3, { timeout: 180_000 });
  // every tile carries the whole clip's speech-heard trace, not just one number
  await expect(page.getByTestId("sim-strip")).toHaveCount(3, { timeout: 30_000 });
  await page.screenshot({ path: test.info().outputPath("tiles.png") });

  await page.getByTestId("sim-tile").nth(2).click();
  const a = page.getByTestId("sim-analysis");
  await expect(a.getByTestId("sim-slice")).toBeVisible({ timeout: 120_000 });   // the head run finishes in the browser
  for (const id of ["clip-timeline", "wave-timeline", "chart-sii", "chart-spectrogram", "chart-now", "sim-deficit"]) await expect(a.getByTestId(id)).toBeVisible();

  // a click on the clip timeline moves the playhead: the time label follows
  const clip = a.getByTestId("clip-timeline"), box = (await clip.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.4, box.y + box.height / 2);
  const label = a.getByText(/^t = [\d.]+ ms/);
  const t0 = await label.textContent();
  expect(parseFloat(t0!.slice(4))).toBeGreaterThan(300);

  // slow motion advances the SAME clock, slowly: a second later t has moved, but by well under a millisecond
  await a.getByTestId("speed").selectOption("2000");
  await a.getByTestId("play-slow").click();
  await page.waitForTimeout(1500);
  const t1 = await label.textContent();
  const dt = parseFloat(t1!.slice(4)) - parseFloat(t0!.slice(4));
  expect(dt).toBeGreaterThan(0.1);
  expect(dt).toBeLessThan(2);
  await expect(label).toContainText("slowed");

  // the field is drawn, not blank: more than a couple of colours on the canvas
  const colours = await a.getByTestId("sim-slice").evaluate((c: HTMLCanvasElement) => {
    const d = c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data, seen = new Set<number>();
    for (let i = 0; i < d.length; i += 4) seen.add((d[i] << 16) | (d[i + 1] << 8) | d[i + 2]);
    return seen.size;
  });
  expect(colours).toBeGreaterThan(20);
  await page.screenshot({ path: test.info().outputPath("analysis.png"), fullPage: true });

  // real time plays the clip with audio and moves the clock at clip speed
  await a.getByTestId("play-real").click();
  await page.waitForTimeout(600);
  await expect(label).toContainText("real time");
  await a.getByTestId("play-real").click();

  // ONE view: the head and ear figures sit in the same view as the clip, every one of them ABOVE the timelines, and the
  // timelines still fit on the screen (no tab, no scrolling to reach them)
  const tl = (await a.getByTestId("wave-timeline").boundingBox())!, clipTop = (await a.getByTestId("clip-timeline").boundingBox())!.y;
  expect(tl.y + tl.height).toBeLessThanOrEqual(1000);
  for (const id of ["sim-3d", "sim-ear", "sim-slice", "sim-ear-other", "sim-slice-other"]) {
    const b = await a.getByTestId(id).boundingBox();
    expect(b, id).not.toBeNull();
    expect(b!.y + b!.height, id).toBeLessThan(clipTop);
  }
  await expect(page.getByRole("tab")).toHaveCount(0);
  // the backend viewers are on the page's clock (e2e/sim-sync.spec.ts checks their t against the playhead)

  // EXACT sync: every figure is a pure function of t — leave an instant, come back, and all three repaint identically;
  // a different instant paints differently
  await expect(label).not.toContainText("slowed");   // stopped: only a seek moves t
  const snap = () => Promise.all(["sim-slice", "sim-slice-other"].map((id) =>
    a.getByTestId(id).evaluate((c: HTMLCanvasElement) => c.toDataURL())));
  const seekTo = async (f: number) => { await page.mouse.click(box.x + box.width * f, box.y + box.height / 2); await page.waitForTimeout(150); };
  // the head run streams frames for a while: wait until the same instant repaints identically twice in a row
  await seekTo(0.3);
  await expect.poll(async () => { const x = await snap(); await page.waitForTimeout(1500); return JSON.stringify(x) === JSON.stringify(await snap()); }, { timeout: 180_000 }).toBe(true);
  const first = await snap();
  await seekTo(0.62); const other = await snap();
  await seekTo(0.3); const again = await snap();
  expect(again).toEqual(first);
  expect(other).not.toEqual(first);
  expect(errors).toEqual([]);
});
