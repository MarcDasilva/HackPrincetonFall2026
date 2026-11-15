import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { localHead } from "./mockBackend";

// Catches a gallery view failing to build (a throw in one variant blanks its card) or the page losing a view.
test("sim gallery: ten technical views of one scene render around the head", async ({ page }) => {
  test.setTimeout(180_000); // ten live WebGL views are slow in headless Chromium's software renderer
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  const glb = localHead();
  await page.route("**/files/head/head_ears.glb", (route) => (glb ? route.fulfill({ contentType: "model/gltf-binary", body: fs.readFileSync(glb) }) : route.fulfill({ status: 404 })));
  await page.goto("/zz-preview/sim-gallery?pid=preview");
  await expect(page.getByTestId("gallery-card")).toHaveCount(10);
  await page.waitForTimeout(2500);
  expect(errors).toEqual([]);
  const cards = page.getByTestId("gallery-card");
  for (let i = 0; i < 10; i++) await cards.nth(i).screenshot({ path: test.info().outputPath(`view-${String(i + 1).padStart(2, "0")}.png`) });
  await page.screenshot({ path: test.info().outputPath("gallery.png"), fullPage: true });
});
