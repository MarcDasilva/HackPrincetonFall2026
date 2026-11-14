import { test, expect, type Page } from "@playwright/test";
import { capsOn, mockBackend } from "./mockBackend";

/** Send with the practice attachments and wait until the three views have fanned into their row (last reveal + 1.6 s hold + 0.9 s fan). */
const toRow = async (page: Page) => {
  await mockBackend(page);
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await capsOn(page);
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
  await expect(page.getByTestId("attachment")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("ear-view-2")).toBeVisible({ timeout: 25_000 });
  await page.waitForTimeout(2700);
};

// Catches a click on a view doing nothing, the modal not growing UP out of the row (or covering the dock), or closing leaving the card hidden.
test("clicking a view expands it upward into a modal; Esc puts it back", async ({ page }) => {
  test.setTimeout(60_000);
  await toRow(page);
  const card = page.getByTestId("ear-view-0");
  const c = (await card.boundingBox())!;
  await card.click();
  const modal = page.getByTestId("ear-view-modal");
  await expect(modal).toBeVisible();
  await page.waitForTimeout(250);
  await page.screenshot({ path: "test-results/views-modal-mid.png" });
  await page.waitForTimeout(500);
  const m = (await modal.boundingBox())!;
  expect(m.width).toBeGreaterThan(c.width * 1.5);
  expect(m.y).toBeLessThan(c.y); // grew upward out of the row...
  expect(m.y).toBeGreaterThanOrEqual(100); // ...but stops at the dock
  expect(m.y + m.height).toBeGreaterThanOrEqual(c.y + c.height - 3);
  await page.screenshot({ path: "test-results/views-modal-open.png" });

  // Open views never time out: the row survives well past the 3 s idle window.
  await page.waitForTimeout(3500);
  await expect(modal).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(modal).toHaveCount(0);
  await expect(card).toHaveCSS("opacity", "1");
});

// Catches the row lingering forever, or vanishing before the 3 s idle window, or not shrinking toward the orb.
test("with no click for 3 s the views shrink into the orb and disappear", async ({ page }) => {
  test.setTimeout(60_000);
  await toRow(page);
  await page.waitForTimeout(1500);
  await expect(page.getByTestId("ear-views")).toBeVisible(); // still there inside the idle window
  // Frames through the 0.7 s shrink: each card's center must move toward the orb's center while it shrinks.
  const orb = (await page.getByTestId("orb").boundingBox())!;
  const oc = { x: orb.x + orb.width / 2, y: orb.y + orb.height / 2 };
  const dist = async () => {
    const b = await page.getByTestId("ear-view-0").boundingBox().catch(() => null);
    return b && b.width > 4 ? { d: Math.hypot(b.x + b.width / 2 - oc.x, b.y + b.height / 2 - oc.y), w: b.width } : null;
  };
  const start = (await dist())!;
  let mid = null;
  for (let i = 0; i < 40 && !mid; i++) {
    await page.waitForTimeout(100);
    const now = await dist();
    if (now && now.w < start.w * 0.6) {
      mid = now;
      await page.screenshot({ path: "test-results/views-collapsing.png" });
    }
  }
  expect(mid).not.toBeNull();
  expect(mid!.d).toBeLessThan(start.d);
  await expect(page.getByTestId("ear-views")).toHaveCount(0, { timeout: 3000 });
  await page.screenshot({ path: "test-results/views-gone.png" });
});
