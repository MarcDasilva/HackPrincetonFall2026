import { test, expect } from "@playwright/test";

// Catches a variant that throws or paints nothing: each canvas must have lit pixels, and they must change between frames (a frozen loop looks fine in one screenshot).
test("every orb variant draws and animates", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/zz-preview/orbs");
  const canvases = page.locator("main figure canvas");
  await expect(canvases).toHaveCount(5);
  await page.waitForTimeout(500);
  const lit = () => canvases.evaluateAll((cs) => cs.map((c) => {
    const d = (c as HTMLCanvasElement).getContext("2d")!.getImageData(0, 0, (c as HTMLCanvasElement).width, (c as HTMLCanvasElement).height).data;
    let sum = 0;
    for (let i = 3; i < d.length; i += 4) sum += d[i];
    return sum;
  }));
  const a = await lit();
  await page.waitForTimeout(300);
  const b = await lit();
  for (let i = 0; i < 5; i++) {
    expect(a[i]).toBeGreaterThan(0);
    expect(b[i]).not.toBe(a[i]);
  }
  expect(errors).toEqual([]);
  await page.screenshot({ path: "test-results/orb-variants.png" });
});
