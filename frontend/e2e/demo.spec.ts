import { test, expect, type Page } from "@playwright/test";

const step = (page: Page, name: string) => page.getByRole("navigation", { name: "Storyboard" }).getByRole("button", { name });
const shot = (page: Page, name: string) => page.screenshot({ path: `test-results/${name}.png`, fullPage: true });

// Catches a beat that throws or renders empty on the fake manifest — the demo must play end to end from the file alone.
test("demo plays all seven beats from the fake manifest", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/demo");
  await expect(page.getByTestId("fake-badge")).toBeVisible();

  // 1: ear mesh loads and the wave viewer iframe embeds from the manifest URL.
  await expect(page.getByTestId("mesh")).toHaveAttribute("data-state", "ok", { timeout: 15_000 });
  await expect(page.getByTestId("wave-iframe").or(page.getByTestId("wave-placeholder"))).toBeVisible();
  await page.waitForTimeout(1500);
  await shot(page, "demo-1-ear");

  // 2: all 96 tiles fill on the recorded timeline, and a showcase tile opens its neurogram pair.
  await step(page, "Launch").click();
  await expect(page.getByTestId("tile")).toHaveCount(96);
  await expect(page.getByTestId("launch-clock")).toContainText("96 / 96", { timeout: 20_000 });
  await page.waitForTimeout(400); // last tile's colour transition
  await page.getByTestId("tile").filter({ has: page.locator("i") }).first().click();
  await expect(page.getByRole("img", { name: /neurogram/ })).toHaveCount(2);
  await shot(page, "demo-2-launch");

  await step(page, "Target").click();
  await expect(page.getByText("Target insertion gain T(f)")).toBeVisible();
  await expect(page.getByText("normal range")).toBeVisible(); // charts draw after their width is measured
  await shot(page, "demo-3-target");

  await step(page, "Search").click();
  await expect(page.getByText("pick, design 3")).toBeVisible();
  await shot(page, "demo-4-search");

  // 5: the horn GLB from designs[pick].mesh loads and the snap-in animation finishes.
  await step(page, "Fit").click();
  await expect(page.getByTestId("mesh")).toHaveAttribute("data-state", "ok", { timeout: 15_000 });
  await expect(page.getByTestId("card")).toContainText("passive-suitable");
  await page.waitForTimeout(2000);
  await shot(page, "demo-5-fit");

  await step(page, "Proof").click();
  await expect(page.locator("audio")).toHaveCount(3);
  await shot(page, "demo-6-proof");

  await step(page, "Second patient").click();
  await expect(page.getByTestId("mesh")).toHaveCount(2);
  await expect(page.getByTestId("mesh").nth(1)).toHaveAttribute("data-state", "ok", { timeout: 15_000 });
  await page.waitForTimeout(2000);
  await shot(page, "demo-7-compare");
});

// Catches the demo depending on the backend: with it unreachable, beat 1 must fall back to a placeholder and the rest still render.
test("demo renders with the backend unreachable", async ({ page }) => {
  await page.route("http://localhost:8001/**", (r) => r.abort());
  await page.goto("/demo#1");
  await expect(page.getByTestId("wave-placeholder")).toBeVisible();
  await expect(page.getByTestId("mesh")).toHaveAttribute("data-state", "ok", { timeout: 15_000 });
});

// Catches phone layouts that overflow sideways — the 12-tile rows and the charts must fit a 400 px screen.
test("demo fits a phone screen", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 400, height: 860 });
  for (const beat of [2, 3, 4, 6]) {
    await page.goto(`/demo#${beat}`);
    await expect(page.getByTestId(`beat-${beat}`)).toBeVisible();
    await page.waitForTimeout(beat === 2 ? 12_500 : 500);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(400);
    await shot(page, `demo-phone-${beat}`);
  }
});
