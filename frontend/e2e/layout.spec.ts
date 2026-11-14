import { test, expect } from "@playwright/test";
import { mockBackend } from "./mockBackend";

// GSAP writes rotation into the transform matrix; atan2(b, a) reads the angle back.
const angle = (l: import("@playwright/test").Locator) =>
  l.evaluate((e) => { const m = new DOMMatrix(getComputedStyle(e).transform); return Math.round((Math.atan2(m.b, m.a) * 180) / Math.PI); });
const box = async (l: import("@playwright/test").Locator) => (await l.boundingBox())!;

// Catches the orb and chat failing to split on send, splitting before any send, or the orb drifting into the dock.
test("orb and chat start centered together, then split apart on send", async ({ page }) => {
  await mockBackend(page); // sending starts a real run otherwise
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
  // Idle behind the card: the element is never CSS-rotated.
  expect(await angle(orb)).toBe(0);
  await page.screenshot({ path: "test-results/layout-before.png" });

  // Sending now needs an ear photo AND a hearing test (see gate.spec.ts).
  await page.getByTestId("hearing-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await capture.click();
  await page.getByRole("button", { name: "Take picture" }).click();
  await expect(page.getByTestId("attachment")).toBeVisible();
  await page.waitForTimeout(800); // panel retract
  // Trace the orb's screen centre every frame through the split.
  await orb.evaluate((o) => {
    const w = window as unknown as { orbTrace: number[] };
    w.orbTrace = [];
    const t0 = performance.now();
    const f = () => { const r = o.getBoundingClientRect(); w.orbTrace.push(r.y + r.height / 2); if (performance.now() - t0 < 1100) requestAnimationFrame(f); };
    f();
  });
  await page.getByRole("button", { name: "Send" }).click();
  await page.waitForTimeout(1200); // 0.9s split tween

  // The orb only ever rises: the card and orb tweens on different eases make it rise, dip back down, then rise again.
  const trace: number[] = await page.evaluate(() => (window as unknown as { orbTrace: number[] }).orbTrace);
  for (let i = 1; i < trace.length; i++) expect(trace[i]).toBeLessThanOrEqual(trace[i - 1] + 1);

  // After: the visible sphere (80% of the canvas) clears the Capture Ear button, and stays below the dock.
  c = await box(card); o = await box(orb);
  const cap = await box(capture);
  const sphereTop = o.y + o.height * 0.1, sphereBottom = o.y + o.height * 0.9;
  expect(sphereBottom).toBeLessThanOrEqual(cap.y);
  expect(sphereTop).toBeGreaterThanOrEqual(100);
  expect(c.y + c.height).toBeLessThanOrEqual(vh);
  // Card drops to 64px above the bottom edge.
  expect(Math.abs(vh - (c.y + c.height) - 64)).toBeLessThan(4);
  // Orb is centered between the dock icons' bottom edge (100px) and the Capture Ear button, less the 48px kept for the loading sub text (ORB_SUB).
  expect(Math.abs(o.y + o.height / 2 - (100 + cap.y - 48) / 2)).toBeLessThan(4);
  // Active: the spin is a 3D yaw drawn inside the canvas — a flat CSS rotation of the element means the 2D turn came back.
  expect(await angle(orb)).toBe(0);
  await page.screenshot({ path: "test-results/layout-after.png" });
});
