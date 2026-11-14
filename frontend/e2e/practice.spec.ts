import { test, expect } from "@playwright/test";
import { capsOn, mockBackend } from "./mockBackend";
import fs from "node:fs";

// Catches the dev shortcut breaking: Caps Lock ON must attach the ear photo and a fake hearing test in the real report format and NOT send; Enter then sends through the normal gate; turning Caps Lock OFF must not re-attach.
test("Caps Lock attaches the ear and a fake hearing test, Enter sends them", async ({ page }) => {
  let body = "";
  await mockBackend(page, { postDelayMs: 3000, onPost: (b) => (body = b) }); // sending starts a real run otherwise; the delay keeps the chips alive while the spec reads the PDF
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await capsOn(page);
  const ear = page.getByTestId("attachment");
  const report = page.getByTestId("hearing-attachment");
  await expect(ear).toBeVisible();
  await expect(report).toBeVisible();
  await page.screenshot({ path: "test-results/practice-attached.png" });
  // The fake report is the same PDF the in-app test makes.
  const href = await report.locator("a").getAttribute("href");
  const pdf = await page.evaluate(async (u) => Array.from(new Uint8Array(await (await fetch(u!)).arrayBuffer())), href);
  fs.writeFileSync("test-results/practice-hearing.pdf", Buffer.from(pdf));
  expect(Buffer.from(pdf).toString("latin1").startsWith("%PDF")).toBe(true);
  // Caps Lock alone never sends: the chips are still there a beat later.
  await page.waitForTimeout(1000);
  await expect(ear).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(ear).toHaveCount(0, { timeout: 8000 });
  await expect(report).toHaveCount(0);
  await page.waitForTimeout(1200);
  await page.screenshot({ path: "test-results/practice-sent.png" });
  // The practice photo is known (hand box, left ear), so it sends both and never triggers backend detection; both ears' audiograms go so the side can pick.
  expect(body).toMatch(/name="box"\r\n\r\n240,70,470,430/);
  expect(body).toMatch(/name="side"\r\n\r\nleft/);
  expect(body).toMatch(/name="audiogram"\r\n\r\n\{"right":\{[^}]*\},"left":\{/);
  // Caps Lock OFF (keydown with the modifier cleared) must not bring the practice attachments back.
  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "CapsLock", modifierCapsLock: false, cancelable: true })));
  await page.waitForTimeout(500);
  await expect(ear).toHaveCount(0);
});
