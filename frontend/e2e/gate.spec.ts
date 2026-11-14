import { test, expect } from "@playwright/test";

// Catches a run starting without every input: the up arrow must stay dead until BOTH ear photos AND a hearing test are attached.
test("the up arrow needs both ear photos and a hearing test", async ({ page }) => {
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  const send = page.getByRole("button", { name: "Send" });
  await expect(send).toBeDisabled();
  await page.screenshot({ path: "test-results/gate-disabled.png" });

  await page.getByTestId("hearing-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await expect(send).toBeDisabled(); // hearing test alone

  await page.getByRole("button", { name: "Capture Ears & Face" }).click();
  await page.getByRole("button", { name: "Take picture" }).click();
  await expect(page.getByTestId("attachment-left")).toBeVisible();
  await expect(send).toBeDisabled(); // one ear alone
  await page.getByRole("button", { name: "Take picture" }).click();
  await expect(page.getByTestId("attachment-right")).toBeVisible();
  await page.waitForTimeout(800); // panel retract
  await expect(send).toBeEnabled();
  await page.screenshot({ path: "test-results/gate-enabled.png" });

  // Enter in the textarea submits too, so the guard must also hold there — covered by removing one input and pressing Enter.
  await page.getByRole("button", { name: "Remove right ear photo" }).click();
  await expect(send).toBeDisabled();
  await page.locator("textarea").press("Enter");
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
});
