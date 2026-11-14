import { test, expect } from "@playwright/test";

// The tab must carry the Auris name and the logo's A — a stale default favicon.ico shadows app/icon.svg in some browsers.
test("tab shows Auris title and A icon", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Auris");
  const href = await page.locator('link[rel="icon"]').first().getAttribute("href");
  expect(href).toContain("icon.svg");
  await page.goto(href!);
  await page.screenshot({ path: "test-results/brand-icon.png" });
});
