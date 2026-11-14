import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test, expect } from "@playwright/test";
import { capsOn, mockBackend, PID } from "./mockBackend";

const CORS = { "access-control-allow-origin": "*" };
// The AudioEar AVERAGE ear run through backend ear_world.skin — not a patient's ear.
const SKIN = readFileSync(process.env.SKIN_GLB ?? join(__dirname, "fixtures", "ear_skin.glb"));   // SKIN_GLB: look at a real run locally

// Catches the homepage falling back to the mask or the raw ear.glb when the backend has written depth.png and ear_skin.glb, or the skin failing to load.
test("the cards show the depth map and ear_skin.glb when the backend provides them", async ({ page }) => {
  await mockBackend(page);
  const files = Object.fromEntries(["overlay.jpg", "mask.png", "depth.png", "ear.glb", "ear_skin.glb"].map((f) => [f, `/api/patients/${PID}/files/${f}`]));
  const asked: string[] = [];
  // registered after mockBackend, so these win
  await page.route(`**/api/patients/${PID}`, (route) =>
    route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ status: "running", step: "context", files }) }));
  await page.route(`**/api/patients/${PID}/files/*.glb`, (route) => {
    asked.push(route.request().url().split("/").pop()!);
    return route.fulfill({ contentType: "model/gltf-binary", headers: CORS, body: SKIN });
  });
  if (process.env.DEPTH_PNG) await page.route(`**/api/patients/${PID}/files/depth.png`, (route) =>
    route.fulfill({ contentType: "image/png", headers: CORS, body: readFileSync(process.env.DEPTH_PNG!) }));

  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await capsOn(page);
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
  await expect(page.getByTestId("attachment")).toBeVisible();
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("ear-view-1").getByAltText("Depth map")).toBeVisible({ timeout: 15_000 });
  const card = page.getByTestId("ear-view-2");
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(card.getByTestId("mesh")).toHaveAttribute("data-state", "ok", { timeout: 15_000 });
  expect(asked).toEqual(["ear_skin.glb"]);
  await page.waitForTimeout(3500); // let the cards fan into the row
  await card.screenshot({ path: "test-results/ear-skin-card.png" });
  await page.screenshot({ path: "test-results/ear-skin-row.png" });
});
