import { test, expect } from "@playwright/test";
import { capsOn, mockBackend } from "./mockBackend";

// Catches the views landing together instead of one by one 3 s apart, stacking in the wrong order, or never fanning into a row as wide as the chat box.
test("ear views appear 3 s apart, stacked, then fan into a row over the orb", async ({ page }) => {
  await mockBackend(page);
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await capsOn(page);
  await expect(page.getByTestId("hearing-attachment")).toBeVisible(); // the attachments land asynchronously; Enter before then is ignored by the gate
  await expect(page.getByTestId("attachment")).toBeVisible();
  await page.keyboard.press("Enter"); // step 2: send

  const view = (i: number) => page.getByTestId(`ear-view-${i}`);
  await expect(view(0)).toBeVisible({ timeout: 15_000 });
  const t0 = Date.now();
  await expect(view(1)).toHaveCount(0);
  await expect(view(1)).toBeVisible({ timeout: 6000 });
  const t1 = Date.now() - t0;
  await expect(view(2)).toBeVisible({ timeout: 6000 });
  const t2 = Date.now() - t0;
  expect(t1).toBeGreaterThan(2500);
  expect(t2 - t1).toBeGreaterThan(2500);
  await page.waitForTimeout(700);
  await page.screenshot({ path: "test-results/views-stacked.png" });

  // Row: after the hold + 0.9 s fan, the three cards tile the chat box width side by side, centered on the orb.
  await page.waitForTimeout(2500);
  const box = async (l: ReturnType<typeof view>) => (await l.boundingBox())!;
  const [a, b, c] = [await box(view(0)), await box(view(1)), await box(view(2))];
  const form = (await page.locator("form").boundingBox())!;
  expect(Math.abs(a.x - form.x)).toBeLessThan(3);
  expect(Math.abs(c.x + c.width - (form.x + form.width))).toBeLessThan(3);
  expect(b.x).toBeGreaterThan(a.x + a.width);
  expect(Math.abs(a.y - b.y)).toBeLessThan(2);
  const orb = (await page.getByTestId("orb").boundingBox())!;
  expect(Math.abs(a.y + a.height / 2 - (orb.y + orb.height / 2))).toBeLessThan(4);
  await page.screenshot({ path: "test-results/views-row.png" });
});
