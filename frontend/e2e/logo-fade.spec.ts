import { test, expect } from "@playwright/test";

const logoAnimating = (page: import("@playwright/test").Page) =>
  page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="auris-logo"]');
    return el ? { n: el.getAnimations().length } : null; // object, not the bare count — 0 is falsy and would make waitForFunction spin
  }).then(async (h) => (await h.jsonValue())!.n);

// Catches the title popping in abruptly after sign-in, or replaying its fade on every refresh.
test("title fades in after client-side nav from landing, not on refresh", async ({ page }) => {
  // /zz-preview stands in for /dashboard (no Supabase session in tests); the landing outro reaches it the same way, via router.push.
  await page.goto("/");
  await page.waitForFunction(() => !!(window as unknown as { next?: { router?: unknown } }).next?.router);
  await page.evaluate(() => (window as unknown as { next: { router: { push: (h: string) => void } } }).next.router.push("/zz-preview"));
  expect(await logoAnimating(page)).toBeGreaterThan(0);

  await page.reload();
  expect(await logoAnimating(page)).toBe(0);
  await page.waitForTimeout(1500); // let the metal shader and dock intro finish so the screenshot shows the settled page
  await page.screenshot({ path: "test-results/logo-refresh.png" });
});
