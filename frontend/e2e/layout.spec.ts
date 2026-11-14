import { test, expect } from "@playwright/test";

const box = async (l: import("@playwright/test").Locator) => (await l.boundingBox())!;

// Catches the orb and chat failing to split on send, splitting before any send, or the orb drifting into the dock.
test("orb and chat start centered together, then split apart on send", async ({ page }) => {
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  const vh = page.viewportSize()!.height;
  const orb = page.getByTestId("orb");
  const card = page.locator("form");
  const capture = page.getByRole("button", { name: "Capture Ear" });

  // Before sending: the card sits at screen center with the orb behind it.
  let c = await box(card), o = await box(orb);
  expect(Math.abs(c.y + c.height / 2 - vh / 2)).toBeLessThan(4);
  expect(Math.abs(o.y + o.height / 2 - vh / 2)).toBeLessThan(4);
  await page.screenshot({ path: "test-results/layout-before.png" });

  await page.getByRole("textbox").fill("hello");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(1200); // 0.9s split tween

  // After: the visible sphere (80% of the canvas) clears the Capture Ear button, and stays below the dock.
  c = await box(card); o = await box(orb);
  const cap = await box(capture);
  const sphereTop = o.y + o.height * 0.1, sphereBottom = o.y + o.height * 0.9;
  expect(sphereBottom).toBeLessThanOrEqual(cap.y);
  expect(sphereTop).toBeGreaterThanOrEqual(100);
  expect(c.y + c.height).toBeLessThanOrEqual(vh);
  // Card drops to 64px above the bottom edge.
  expect(Math.abs(vh - (c.y + c.height) - 64)).toBeLessThan(4);
  // Orb is centered between the dock icons' bottom edge (100px) and the Capture Ear button.
  expect(Math.abs(o.y + o.height / 2 - (100 + cap.y) / 2)).toBeLessThan(4);
  await page.screenshot({ path: "test-results/layout-after.png" });
});
