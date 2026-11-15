import { test, expect } from "@playwright/test";

// Catches the lab-report sim view losing a figure: the rig tiles, then on click the head's wavefronts, the ear's slices and the pixel field, in that order, and the other ear's slices and field below.
// The two viewers are the backend's own pages (localhost:8000); without that backend they load empty, and the structure below still holds.
test("sim lab preview: rig figures open into head wavefronts, both ears' slices and pixel fields", async ({ page }) => {
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/zz-preview/sim-lab");
  const tiles = page.getByTestId("sim-tile");
  await expect(tiles).toHaveCount(3, { timeout: 30_000 });
  await expect(page.locator("[data-testid=sim-tile][data-done]")).toHaveCount(3, { timeout: 180_000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: test.info().outputPath("overview.png") });

  // A drag turns the tile's rig and does NOT open the scene — the patient explores the setup before choosing.
  const rig = tiles.nth(2).locator("canvas");
  const before = await rig.screenshot();
  const box = (await rig.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 + 30, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect((await rig.screenshot()).equals(before)).toBe(false);
  await expect(page.getByTestId("sim-detail")).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("turned.png") });

  await tiles.nth(2).click();
  const detail = page.getByTestId("sim-detail");
  // a the head's wavefronts, b this ear's slices, c the pixel field, in that order.
  await expect(detail.getByTestId("sim-slice")).toBeVisible({ timeout: 120_000 });
  const order = await detail.locator("[data-testid=sim-3d], [data-testid=sim-ear], [data-testid=sim-slice]").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(order).toEqual(["sim-3d", "sim-ear", "sim-slice"]);
  // The talker is at 45° on the RIGHT: for the left ear it is behind the head. Its own runs cannot show that, so d shows the
  // left ear with NO wave in it — catches the far-side text note coming back, or a near-side run's wave drawn on the wrong side.
  const d = detail.getByTestId("sim-ear-other");
  await expect(d).toHaveAttribute("src", /\/waves\/left\/index\.html\?.*&silent=1$/);
  await expect(detail).not.toContainText("far side of the head");
  await page.screenshot({ path: test.info().outputPath("detail.png"), fullPage: true });
});

// Catches the reopened scenes losing the comparison the patient came for: normal hearing against hearing with the earpiece.
test("sim lab preview ?aid=1: the same scenes, normal hearing against the earpiece", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/zz-preview/sim-lab?aid=1");
  await expect(page.getByRole("heading", { name: "With your earpiece" })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("[data-testid=sim-tile][data-done]")).toHaveCount(3, { timeout: 180_000 });
  await expect(page.getByTestId("sim-sii").first()).toContainText(/normal \d+% · aid \d+%/);
  await page.waitForTimeout(500);
  await page.screenshot({ path: test.info().outputPath("aid.png") });
  await page.getByTestId("sim-tile").first().click();
  // The full head model (a) is the wide figure, half again a slice's width. Catches the layout falling back to three equal columns.
  const detail = page.getByTestId("sim-detail");
  const figs = detail.locator("figure");
  await expect(figs).toHaveCount(5, { timeout: 30_000 });
  const [a, b] = [(await figs.nth(0).boundingBox())!, (await figs.nth(1).boundingBox())!];
  expect(a.width / b.width).toBeGreaterThan(1.4);
  // The scene title sits on the Exit X's row, centred on the SAME line, with no pressure legend beside it.
  const [x, title] = [(await page.getByRole("button", { name: "Exit simulation" }).boundingBox())!, (await detail.getByRole("heading").first().boundingBox())!];
  expect(Math.abs(x.y + x.height / 2 - (title.y + title.height / 2))).toBeLessThan(2);
  await expect(detail).not.toContainText("pressure, top view");
  // The info column leads with speech heard; the scene's sound, sources, reason and the per-listener list are gone.
  await expect(detail.getByTestId("sim-info")).not.toContainText("Scene weight");
  await expect(detail.getByTestId("sim-info")).not.toContainText("family talking");
  // Speech is longer than the simulated box, so ±iso wavefronts never formed and a showed only the speaker. Clip mode tints
  // every cell by its pressure: a must carry BOTH pressure colours over a real area, not a dot. Needs the backend viewer (:8001).
  await page.waitForTimeout(6000);
  const png = (await detail.getByTestId("sim-3d").screenshot()).toString("base64");
  // Coloured area, as a share of the figure: the old surfaces were a shell at the speaker; the tint fills the air from the
  // speaker to the ear. The legend row at the bottom is left out.
  const area = await page.evaluate(async (b64) => {
    const img = new Image(); img.src = `data:image/png;base64,${b64}`; await img.decode();
    const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
    const g = c.getContext("2d")!; g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data; let n = 0;
    for (let y = 0; y < c.height * 0.85; y++) for (let x = 0; x < c.width; x++) { const i = (y * c.width + x) * 4; if (Math.abs(d[i] - d[i + 2]) > 40) n++; }
    return n / (c.width * c.height);
  }, png);
  expect(area).toBeGreaterThan(0.018); // measured: surfaces 0.011, tint 0.026 (Dinner table, 1440×900)
  // Figures carry a title only, and the whole detail fits ONE screen: nothing scrolls.
  await expect(detail).not.toContainText("Its own run");
  await page.waitForTimeout(3000);
  const sims = page.getByTestId("sims");
  expect(await sims.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: test.info().outputPath("aid-detail.png") });
});

// Catches the tiles scoring a textbook speech spectrum instead of the clip that plays: with the clips unreachable a tile
// must NOT produce a number, however long its wave runs take.
test("sim lab preview: a tile scores only once its own audio clips have loaded", async ({ page }) => {
  test.setTimeout(240_000);
  await page.route("**/sim/clips/**", (r) => r.abort());
  await page.goto("/zz-preview/sim-lab");
  await expect(page.getByTestId("sim-tile")).toHaveCount(3, { timeout: 60_000 });
  await page.waitForTimeout(60_000);   // the wave runs finish well inside this on a quiet machine
  await expect(page.locator("[data-testid=sim-tile][data-done]")).toHaveCount(0);
});
