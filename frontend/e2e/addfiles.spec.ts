import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import { mockBackend } from "./mockBackend";

const open = async (page: Page) => {
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
};
const EAR = fs.readFileSync("public/dev/ear.png");

// Catches the composer "+" staying inert: it must open the file picker and file an image as the EAR photo (not the hearing test), un-mirrored.
test("+ picks an ear image and a hearing PDF", async ({ page }) => {
  await open(page);
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Add" }).click();
  await (await chooser).setFiles({ name: "ear.png", mimeType: "image/png", buffer: EAR });
  const ear = page.getByTestId("attachment");
  await expect(ear).toBeVisible();
  await expect(ear.locator("img")).not.toHaveCSS("transform", /matrix\(-1/); // a camera capture is mirrored; a picked file must not be
  await expect(page.getByTestId("hearing-attachment")).toHaveCount(0);
  await page.getByTestId("add-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();
});

// Catches drop not reaching the card: a dragged ear image must attach, and the card must show it is a drop target while hovering.
test("dragging an ear image onto the chat box attaches it", async ({ page }) => {
  await open(page);
  const zone = page.getByTestId("drop-zone");
  // Playwright cannot drag from the OS, so build the DataTransfer in the page.
  const dt = await page.evaluateHandle((b64) => {
    const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const d = new DataTransfer();
    d.items.add(new File([bin], "ear.png", { type: "image/png" }));
    return d;
  }, EAR.toString("base64"));
  await zone.dispatchEvent("dragover", { dataTransfer: dt });
  await expect(zone).toHaveCSS("outline-style", "dashed");
  await page.screenshot({ path: "test-results/drop-hover.png" });
  await zone.dispatchEvent("drop", { dataTransfer: dt });
  await expect(page.getByTestId("attachment")).toBeVisible();
  await expect(zone).toHaveCSS("outline-style", "none");
  await page.screenshot({ path: "test-results/drop-attached.png" });
});

// Catches the app guessing a box or side again: a picked photo must go to the backend WITHOUT them, so the backend detects the ear (a fixed guess clipped the ear before).
test("a picked ear photo is sent without a box or side", async ({ page }) => {
  let body = "";
  await mockBackend(page, { onPost: (b) => (body = b) });
  await open(page);
  await page.getByTestId("add-input").setInputFiles({ name: "ear.png", mimeType: "image/png", buffer: EAR });
  await page.getByTestId("hearing-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("attachment")).toHaveCount(0);
  expect(body).toContain('name="photo"');
  expect(body).not.toContain('name="box"');
  expect(body).not.toContain('name="side"');
});
