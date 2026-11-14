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

// Catches the composer "+" staying inert or misfiling: images fill the LEFT then the RIGHT ear slot (never the hearing test), un-mirrored, and the arrow wakes only with both ears and a hearing test.
test("+ picks an ear image and a hearing PDF", async ({ page }) => {
  await open(page);
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Add" }).click();
  await (await chooser).setFiles({ name: "ear.png", mimeType: "image/png", buffer: EAR });
  const ear = page.getByTestId("attachment-left");
  await expect(ear).toBeVisible();
  await expect(ear.locator("img")).not.toHaveCSS("transform", /matrix\(-1/); // a camera capture is mirrored; a picked file must not be
  await expect(page.getByTestId("hearing-attachment")).toHaveCount(0);
  await expect(page.getByTestId("attachment-right")).toHaveCount(0);
  await page.getByTestId("add-input").setInputFiles({ name: "ear2.png", mimeType: "image/png", buffer: EAR });
  await expect(page.getByTestId("attachment-right")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await page.getByTestId("add-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
  // The face photo is OPTIONAL: both ears and a hearing test are enough, and the button says a face photo would add a head model.
  const send = page.getByRole("button", { name: "Send" });
  await expect(send).toBeEnabled();
  await expect(send).toHaveAttribute("title", /face photo for a head model \(optional\)/);
  // A third image is the face.
  await page.getByTestId("add-input").setInputFiles({ name: "face.png", mimeType: "image/png", buffer: EAR });
  await expect(page.getByTestId("attachment-selfie").getByAltText("Face photo")).toBeVisible();
  await expect(send).not.toHaveAttribute("title", /.+/);
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
  await expect(page.getByTestId("attachment-left")).toBeVisible();
  await expect(zone).toHaveCSS("outline-style", "none");
  await page.screenshot({ path: "test-results/drop-attached.png" });
});

// Catches the app guessing a box again or mislabeling sides: each picked photo goes in ITS ear's field, WITHOUT a box, so the backend detects the ear (a fixed guess clipped the ear before).
test("picked ear photos are sent per ear without a box", async ({ page }) => {
  let body = "";
  await mockBackend(page, { onPost: (b) => (body = b) });
  await open(page);
  await page.getByTestId("add-input").setInputFiles([{ name: "ear.png", mimeType: "image/png", buffer: EAR }, { name: "ear2.png", mimeType: "image/png", buffer: EAR }]);
  await page.getByTestId("hearing-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("attachment-left")).toHaveCount(0);
  expect(body).toContain('name="photo_left"');
  expect(body).toContain('name="photo_right"');
  expect(body).not.toMatch(/name="box/);
  expect(body).not.toContain('name="side"');
  // No face taken: the field is ABSENT, so the backend fits its average head instead of choking on an empty file.
  expect(body).not.toContain('name="photo_selfie"');
});

// Catches the face photo never reaching the backend: a third picked image is sent as photo_selfie next to both ears, so the run builds THIS patient's head instead of the average one.
test("a picked face photo is sent as photo_selfie", async ({ page }) => {
  let body = "";
  await mockBackend(page, { onPost: (b) => (body = b) });
  await open(page);
  await page.getByTestId("add-input").setInputFiles(["ear.png", "ear2.png", "face.png"].map((name) => ({ name, mimeType: "image/png", buffer: EAR })));
  await expect(page.getByTestId("attachment-selfie")).toBeVisible();
  await page.getByTestId("hearing-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await page.screenshot({ path: "test-results/addfiles-three.png" });
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("attachment-selfie")).toHaveCount(0);
  expect(body).toMatch(/name="photo_selfie"; filename="selfie\.jpg"/);
  expect(body).toContain('name="photo_left"');
  expect(body).toContain('name="photo_right"');
});
