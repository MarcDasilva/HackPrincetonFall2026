import { test, expect } from "@playwright/test";

// /zz-preview renders Dashboard without the Supabase gate that redirects /dashboard when logged out.
// Catches the camera filling the wrong slot or closing early: the first shot is the LEFT ear, the camera stays live and says so for the RIGHT, then for the FACE, and closes once all three are in.
test("the camera captures the left ear, the right ear, then the face, into their own chips", async ({ page }) => {
  await page.goto("/zz-preview");
  // toBeVisible ignores opacity, and the chat fades in after the dock animation — wait for it or screenshots are blank.
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await page.getByRole("button", { name: "Capture Ears & Face" }).click();
  await expect(page.getByTestId("cam-ear")).toHaveText("Left ear");
  await page.getByRole("button", { name: "Take picture" }).click();
  const chip = page.getByTestId("attachment-left");
  await expect(chip.getByAltText("Left ear photo")).toBeVisible();
  await expect(page.getByTestId("cam-ear")).toHaveText("Right ear");
  await page.screenshot({ path: "test-results/capture-right-next.png" });
  await page.getByRole("button", { name: "Take picture" }).click();
  await expect(page.getByTestId("attachment-right").getByAltText("Right ear photo")).toBeVisible();
  await expect(page.getByTestId("cam-ear")).toHaveText("Face");
  await page.waitForTimeout(300);
  await page.screenshot({ path: "test-results/capture-face-next.png" });
  await page.getByRole("button", { name: "Take picture" }).click();
  const face = page.getByTestId("attachment-selfie");
  await expect(face.getByAltText("Face photo")).toBeVisible();
  await expect(face).toContainText("F");
  // The face is a camera capture too, so its chip is mirrored like the live feed.
  await expect(face.locator("img")).toHaveCSS("transform", /matrix\(-1/);
  await expect(page.getByTestId("cam-ear")).toHaveCount(0, { timeout: 3000 });
  await page.waitForTimeout(800); // camera panel retract animation
  await page.screenshot({ path: "test-results/capture-attached.png" });
  // Photos alone cannot start a run (the arrow also needs a hearing test), and each chip is removable.
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await page.getByRole("button", { name: "Remove left ear photo" }).click();
  await expect(chip).toHaveCount(0);
  await page.getByRole("button", { name: "Remove face photo" }).click();
  await expect(face).toHaveCount(0);
  await expect(page.getByTestId("attachment-right")).toBeVisible();
});
