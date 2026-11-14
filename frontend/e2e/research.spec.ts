import { test, expect } from "@playwright/test";
import { mockStudy } from "./mockBackend";

const KEYS = ["hearing_research", "use_context_research", "acoustic_design_research", "ear_fit_research"];

// Catches the agent orbs not flying out of the center orb (or landing off their slots), the boxes showing before the orbs land, key 5 not opening the research view, a box missing or not reaching the chat card's edge, or the chat card and pills keeping their black fill over the grid.
test("key 5 opens the research view: four see-through boxes flank the see-through chat card", async ({ page }) => {
  await mockStudy(page);
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await page.locator("body").click({ position: { x: 5, y: 400 } });
  await page.keyboard.press("5");

  // Mid-flight: some orb is still away from its slot (GSAP offset) and visible, while every box is still hidden. Polled, not timed — under load a fixed wait lands after the flight.
  await page.waitForFunction((keys) => keys.some((k) => {
    const f = document.querySelector<HTMLElement>(`[data-testid="flyer-${k}"]`);
    if (!f) return false;
    const m = new DOMMatrix(getComputedStyle(f).transform);
    return Math.hypot(m.m41, m.m42) > 40 && Number(getComputedStyle(f).opacity) > 0.3;
  }) && keys.every((k) => getComputedStyle(document.querySelector(`[data-testid="agent-${k}"]`)!).opacity === "0"), KEYS, { polling: "raf", timeout: 5000 });
  await page.screenshot({ path: "test-results/research-flight.png" });

  for (const key of KEYS) {
    await expect(page.getByTestId(`agent-${key}`)).toBeVisible();
    await expect(page.getByTestId(`agent-${key}`).getByTestId("traces").locator("> div")).not.toHaveCount(0);
  }
  await expect(page.getByTestId("orb").getByRole("status")).toHaveText("Four agents are researching your aid. Ask me anything.");
  await page.waitForTimeout(3000); // flight + border fade, then traces stream
  // Landed: each orb sits exactly on its box's slot, and the box has faded fully in.
  for (const key of KEYS) {
    const f = (await page.getByTestId(`flyer-${key}`).boundingBox())!;
    const slot = (await page.locator(`[data-orb-slot="${key}"]`).boundingBox())!;
    expect(Math.abs(f.x - slot.x) + Math.abs(f.y - slot.y)).toBeLessThan(1.5);
    expect(await page.getByTestId(`agent-${key}`).evaluate((el) => getComputedStyle(el).opacity)).toBe("1");
  }

  // Each orb is centered in its box with the title centered below it.
  for (const key of KEYS) {
    const box = (await page.getByTestId(`agent-${key}`).boundingBox())!;
    const slot = (await page.locator(`[data-orb-slot="${key}"]`).boundingBox())!;
    const title = (await page.getByTestId(`agent-${key}`).locator("header > div").last().boundingBox())!;
    expect(Math.abs(slot.x + slot.width / 2 - (box.x + box.width / 2))).toBeLessThan(1.5);
    expect(Math.abs(title.x + title.width / 2 - (box.x + box.width / 2))).toBeLessThan(1.5);
    expect(title.y).toBeGreaterThanOrEqual(slot.y + slot.height);
  }
  const form = (await page.locator("form").boundingBox())!;
  const left = (await page.getByTestId("agent-acoustic_design_research").boundingBox())!;
  const right = (await page.getByTestId("agent-ear_fit_research").boundingBox())!;
  expect(Math.abs(left.x + left.width + 16 - form.x)).toBeLessThan(2);
  expect(Math.abs(form.x + form.width + 16 - right.x)).toBeLessThan(2);
  const bg = (sel: string) => page.locator(sel).first().evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(await bg("form")).toBe("rgba(0, 0, 0, 0)");
  expect(await bg("[data-testid=drop-zone]")).toBe("rgba(0, 0, 0, 0)");
  const pill = page.getByRole("button", { name: "Capture Ears & Face" });
  expect(await pill.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  expect(await pill.evaluate((el) => getComputedStyle(el.closest("div[style*='border-radius: 20px']")!).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  await page.screenshot({ path: "test-results/research.png" });

  await page.keyboard.press("5");
  await expect(page.getByTestId("agent-hearing_research")).toHaveCount(0);
});
