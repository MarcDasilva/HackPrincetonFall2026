import { test, expect } from "@playwright/test";

// /zz-preview renders Dashboard without the Supabase gate that redirects /dashboard when logged out.
test("captured picture auto-attaches to the chat", async ({ page }) => {
  await page.goto("/zz-preview");
  // toBeVisible ignores opacity, and the chat fades in after the dock animation — wait for it or screenshots are blank.
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await page.getByRole("button", { name: "Capture Ear" }).click();
  await page.getByRole("button", { name: "Take picture" }).click();
  const chip = page.getByTestId("attachment");
  await expect(chip.getByAltText("Captured ear attachment")).toBeVisible();
  await page.waitForTimeout(800); // camera panel retract animation
  await page.screenshot({ path: "test-results/capture-attached.png" });
  // A photo alone cannot start a run (the arrow also needs a hearing test), and the chip is removable.
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await page.getByRole("button", { name: "Remove attachment" }).click();
  await expect(chip).toHaveCount(0);
});
