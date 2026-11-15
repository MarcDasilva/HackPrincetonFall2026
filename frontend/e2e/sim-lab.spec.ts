import { test, expect } from "@playwright/test";

// Catches the lab-report sim view losing a figure: the rig tiles, then on click the head's 3D wave field, the ear's 2D wave slices and the pixel field, in that order.
// The two viewers are the backend's own pages (localhost:8000); without that backend they load empty, and the structure below still holds.
test("sim lab preview: rig figures open into 3D waves, 2D slices and the pixel field", async ({ page }) => {
  test.setTimeout(240_000);
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
  const order = await detail.locator("[data-testid=sim-3d], [data-testid=sim-2d-lab], [data-testid=sim-slice]").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(order).toEqual(["sim-3d", "sim-2d-lab", "sim-slice"]);
  // Busy cafe's talker is at 45°: the viewers show the 45° run.
  await expect(detail.getByTestId("sim-3d")).toHaveAttribute("src", /run=az045_el%2B00/);
  await page.waitForTimeout(8000); // the viewers fetch and decode their wave frames
  await page.screenshot({ path: test.info().outputPath("detail.png"), fullPage: true });
  await detail.getByTestId("sim-3d").screenshot({ path: test.info().outputPath("fig-3d.png") });
});
