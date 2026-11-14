import { test, expect } from "@playwright/test";
import fs from "node:fs";

// The patient this scripted listener plays: sloping loss, left 4 kHz never heard.
const TRUTH = { right: { 500: 10, 1000: 20, 2000: 30, 4000: 50 }, left: { 500: 20, 1000: 20, 2000: 40, 4000: 999 } };

const openDashboard = async (page: import("@playwright/test").Page) => {
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
};

// Catches the full in-app test failing to finish, or finishing without a report attached to the chat.
test("Capture Hearing runs the test and attaches a PDF report", async ({ page }) => {
  await page.addInitScript((truth) => {
    const w = window as unknown as { __hearingSpeed: number };
    w.__hearingSpeed = 0.02; // hook in components/HearingTest.tsx: whole test in seconds
    // Scripted patient: press once per tone trial at or above the true threshold; never on silent trials.
    let last = "";
    setInterval(() => {
      const b = document.querySelector<HTMLButtonElement>('[aria-label="Heard beep"]');
      const d = b?.dataset;
      if (!b || !d || d.live !== "tone" || d.trial === last) return;
      if (Number(d.level) >= (truth as Record<string, Record<string, number>>)[d.ear!][d.freq!]) {
        last = d.trial!;
        b.click();
      }
    }, 3);
  }, TRUTH);
  await openDashboard(page);
  await expect(page.getByRole("button", { name: "Capture Hearing" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Upload hearing test" })).toBeVisible();
  await page.screenshot({ path: "test-results/hearing-buttons.png" });

  await page.getByRole("button", { name: "Capture Hearing" }).click();
  await page.getByRole("button", { name: "Start test" }).waitFor();
  await page.waitForTimeout(700); // panel grow animation
  await page.screenshot({ path: "test-results/hearing-intro.png" });
  await page.getByRole("button", { name: "Start test" }).click();
  await expect(page.getByRole("button", { name: "Heard beep" })).toBeVisible();
  await page.screenshot({ path: "test-results/hearing-running.png" });

  const chip = page.getByTestId("hearing-attachment");
  await expect(chip).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(700); // panel retract
  await page.screenshot({ path: "test-results/hearing-attached.png" });

  const href = await chip.locator("a").getAttribute("href");
  const pdf = await page.evaluate(async (u) => Array.from(new Uint8Array(await (await fetch(u!)).arrayBuffer())), href);
  fs.writeFileSync("test-results/hearing.pdf", Buffer.from(pdf));
  const txt = Buffer.from(pdf).toString("latin1");
  expect(txt.startsWith("%PDF")).toBe(true);
  expect(txt).toContain("(NR)"); // left 4 kHz never heard

  // A report alone cannot start a run (the arrow also needs an ear photo), and the chip is removable.
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await page.getByRole("button", { name: "Remove hearing test" }).click();
  await expect(chip).toHaveCount(0);
});

// Catches the red-flag path producing a test (or results) instead of a referral.
test("a red flag stops the test with a referral", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Capture Hearing" }).click();
  await page.getByRole("button", { name: "One of these applies" }).click();
  await expect(page.getByText("Please see a doctor first")).toBeVisible();
  await expect(page.getByRole("button", { name: "Heard beep" })).toHaveCount(0);
});

// Catches the + button not attaching an existing report (patients who already have a clinic audiogram).
test("+ uploads an existing hearing test", async ({ page }) => {
  await openDashboard(page);
  await page.getByTestId("hearing-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await expect(page.getByTestId("hearing-attachment")).toContainText("PDF");
});
