import { test, expect } from "@playwright/test";

// Catches the 3D moving-source trial going silent or stuck: every head run must land, play must start the loop, and
// grabbing the source and dragging it up must raise its elevation — a broken pick would orbit the camera instead. The
// meters catch a silent output, the reload a lost cache, and a source on the listener's LEFT louder on the right means the channels are swapped.
test("move-source trial: head runs land, play starts, dragging the source in 3D moves it", async ({ page }) => {
  test.setTimeout(900_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/zz-preview/move-source");
  await expect(page.locator("[data-testid=move-progress][data-ready]")).toBeVisible({ timeout: 800_000 });
  // a reload must reuse the cached runs, not redo ~3 min of head simulation
  await page.reload();
  await expect(page.locator("[data-testid=move-progress][data-ready]")).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  const meter = async (e: "L" | "R") => Number(await page.getByTestId(`meter-${e}`).getAttribute("data-level"));
  await expect.poll(() => meter("L"), { timeout: 30_000 }).toBeGreaterThan(0.001);
  const view = page.getByTestId("move-3d");
  const sx = Number(await view.getAttribute("data-sx")), sy = Number(await view.getAttribute("data-sy"));
  await page.mouse.move(sx, sy);
  await page.mouse.down();
  await page.mouse.move(sx + 160, sy - 140, { steps: 12 });
  await page.mouse.up();
  await expect(page.getByTestId("move-pos")).not.toHaveText("az 0° · el 0°");
  const el = Number((await page.getByTestId("move-pos").textContent())!.match(/el (-?\d+)/)![1]);
  expect(el).toBeGreaterThan(10);
  // average over the clip's loudness swings: sample both ears for 3 s
  let l = 0, r = 0;
  for (let i = 0; i < 30; i++) { l += await meter("L"); r += await meter("R"); await page.waitForTimeout(100); }
  expect(l).toBeGreaterThan(r);
  await page.screenshot({ path: "test-results/move-source.png" });
});
