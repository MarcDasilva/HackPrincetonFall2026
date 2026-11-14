import { test, expect } from "@playwright/test";
import { capsOn, mockBackend } from "./mockBackend";

// Catches the views landing together instead of one by one 3 s apart, piling on top of each other (the old tilted stack read as jagged overlap), or the ear rows overlapping the dock, each other or the Capture pills.
test("ear views appear 3 s apart, each straight into its own slot in the row", async ({ page }) => {
  await mockBackend(page);
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await capsOn(page);
  await expect(page.getByTestId("hearing-attachment")).toBeVisible(); // the attachments land asynchronously; Enter before then is ignored by the gate
  await expect(page.getByTestId("attachment-left")).toBeVisible();
  await page.keyboard.press("Enter"); // step 2: send

  const view = (i: number) => page.getByTestId("ear-row-left").getByTestId(`ear-view-${i}`);
  await expect(view(0)).toBeVisible({ timeout: 15_000 });
  const t0 = Date.now();
  await expect(view(1)).toHaveCount(0);
  await expect(view(1)).toBeVisible({ timeout: 6000 });
  const t1 = Date.now() - t0;
  // Mid-reveal, the second card already sits BESIDE the first, never on it.
  await page.waitForTimeout(150);
  const [p0, p1] = [(await view(0).boundingBox())!, (await view(1).boundingBox())!];
  expect(p1.x).toBeGreaterThanOrEqual(p0.x + p0.width - 1);
  await expect(view(2)).toBeVisible({ timeout: 6000 });
  const t2 = Date.now() - t0;
  expect(t1).toBeGreaterThan(2500);
  expect(t2 - t1).toBeGreaterThan(2500);
  await page.waitForTimeout(700);
  await page.screenshot({ path: "test-results/views-revealed.png" });

  // Rows: each ear's three cards sit side by side, centered on screen — left ear above right, both between the dock and the Capture pills.
  const right = (i: number) => page.getByTestId("ear-row-right").getByTestId(`ear-view-${i}`);
  await expect(right(2)).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(1000); // cards land in 0.6 s; well inside the shared 3 s before the rows close
  const box = async (l: ReturnType<typeof view>) => (await l.boundingBox())!;
  const [a, b, c] = [await box(view(0)), await box(view(1)), await box(view(2))];
  const vp = page.viewportSize()!;
  expect(b.x).toBeGreaterThan(a.x + a.width);
  expect(Math.abs(a.y - b.y)).toBeLessThan(2);
  expect(Math.abs((a.x + c.x + c.width) / 2 - vp.width / 2)).toBeLessThan(3);
  const r0 = await box(right(0));
  expect(Math.abs(r0.x - a.x)).toBeLessThan(3);
  expect(r0.y).toBeGreaterThan(a.y + a.height); // right row BELOW the left, not overlapping
  const dock = (await page.getByRole("button", { name: "Profile" }).first().boundingBox())!;
  expect(a.y).toBeGreaterThan(dock.y + dock.height); // clear of the dock
  const pill = (await page.getByRole("button", { name: "Capture Ears & Face" }).first().boundingBox())!;
  expect(r0.y + r0.height).toBeLessThan(pill.y); // clear of the Capture pills
  await page.screenshot({ path: "test-results/views-row.png" });
});
