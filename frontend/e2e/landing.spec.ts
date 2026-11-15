import { test, expect } from "@playwright/test";

// Catches the landing title or Google button breaking after a merge that touched both: a hydration mismatch from metal-fx mounting too early, or a stale import path.
test("landing renders the metal title and LangChain credit and sign-in button without hydration errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && /hydrat/i.test(m.text()) && errors.push(m.text()));

  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in with Google" })).toBeVisible();
  // The LangChain credit under the subtitle — catches the logo file going missing (a broken image still has its alt text).
  const logo = page.getByAltText("LangChain");
  await expect(logo).toBeVisible();
  expect(await logo.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0)).toBe(true);
  await page.waitForTimeout(1500); // let the metal shader settle so the screenshot shows the finished page
  await page.screenshot({ path: test.info().outputPath("landing.png") });
  expect(errors).toEqual([]);
});
