import { test, expect } from "@playwright/test";
import fs from "node:fs";

const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "*" };
const RUN = "d60d88e7550d"; // the dev chord's run (Dashboard DEV_RUN_ID)
// A real earpiece (preview.png, earpiece*.glb) when this checkout has one; AID_FIXTURE_DIR points at another build.
const DIR = process.env.AID_FIXTURE_DIR ?? "../backend/data/patients/8e0c9758fead/aid/cone";
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const OPTIONS = [1, 2, 3, 4].map((i) => ({ id: `grid${i}`, reason: `Reason for option ${i}.`, key_met: "3 of 4", gain_mean_db: Array(18).fill(4 + i), files: { "preview.png": "x" }, recommended: i === 1 }));

// Catches the four designs drifting off the orb (one row in front of it, centred on it), a card that does not lift on hover, an expanded view missing a model, or a select that never reaches the lead.
test("the four designs sit in front of the orb, lift on hover, expand into both models and select", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const posted: unknown[] = [];
  await page.route(`**/lead/${RUN}`, (route) => {
    const req = route.request();
    if (req.method() === "OPTIONS") return route.fulfill({ headers: CORS });
    if (req.method() === "POST") posted.push(req.postDataJSON());
    const picked = posted.some((p) => (p as { event?: string }).event === "picked");
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ run_id: RUN, stage: picked ? "validating" : "options", reply: "Here are four options, each with its reasoning. Pick the one you want.", ear: "left", options: OPTIONS, launch_requested: true, status: "completed" }) });
  });
  await page.route("**/api/sim/patients/**/files/**", (route) => {
    const name = route.request().url().split("/").pop()!.split("?")[0], real = `${DIR}/${name}`;
    return route.fulfill({ contentType: name.endsWith(".png") ? "image/png" : "model/gltf-binary", body: fs.existsSync(real) ? fs.readFileSync(real) : PNG });
  });
  await page.route(/\/api\/patients\/[a-f0-9]{12}$/, (route) => route.fulfill({ status: 404, headers: CORS, contentType: "application/json", body: "{}" }));
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await page.locator("body").click({ position: { x: 5, y: 400 } });
  const t0 = Date.now();
  await page.keyboard.down("1");
  await page.keyboard.down("2");
  await page.keyboard.up("2");
  await page.keyboard.up("1");

  const cards = page.getByTestId("aid-option");
  await expect(cards).toHaveCount(4);
  // ONLY the designer's top performer carries the badge — catches the flag dropped between backend and card.
  await expect(page.getByTestId("aid-recommended")).toHaveCount(1);
  await expect(cards.nth(0).getByTestId("aid-recommended")).toBeVisible();
  // The cards wait for the orb's 0.9 s rise — catches them popping in before the orb they sit in front of.
  expect(Date.now() - t0).toBeGreaterThan(800);
  await page.waitForTimeout(2000); // orb rise, then the cards re-measure around it
  const orb = (await page.getByTestId("orb").boundingBox())!;
  const cx = orb.x + orb.width / 2, cy = orb.y + orb.height / 2;
  const boxes = await Promise.all([0, 1, 2, 3].map((i) => cards.nth(i).boundingBox()));
  // One row in front of the orb, 1 to 4 left to right, its centre on the orb's centre.
  for (let i = 1; i < 4; i++) {
    expect(boxes[i]!.x).toBeGreaterThan(boxes[i - 1]!.x + boxes[i - 1]!.width);
    expect(Math.abs(boxes[i]!.y - boxes[0]!.y)).toBeLessThan(2);
  }
  expect(Math.abs((boxes[0]!.x + boxes[3]!.x + boxes[3]!.width) / 2 - cx)).toBeLessThan(8);
  expect(Math.abs(boxes[0]!.y + boxes[0]!.height / 2 - cy)).toBeLessThan(8);
  // In front: the topmost element at the orb's centre is a card's gap or a card, never the orb above them.
  expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest("[data-testid=aid-options]"), [cx, cy])).toBe(true);
  await page.screenshot({ path: test.info().outputPath("around.png") });

  const before = boxes[1]!.y;
  await cards.nth(1).hover();
  await page.waitForTimeout(400);
  expect((await cards.nth(1).boundingBox())!.y).toBeLessThan(before - 4);
  await page.screenshot({ path: test.info().outputPath("hover.png") });

  await cards.nth(1).click({ position: { x: 40, y: 40 } });
  const expanded = page.getByTestId("aid-expanded");
  await expect(expanded.getByTestId("aid-model")).toHaveCount(2);
  await expect(expanded).toContainText("Reason for option 2.");
  // Reason centred UNDER the models in the standard grey — catches it drifting back beside Select or above the models.
  const panel = (await expanded.boundingBox())!, reason = expanded.getByText("Reason for option 2.");
  const rb = (await reason.boundingBox())!, mb = (await expanded.getByTestId("aid-model").first().boundingBox())!;
  expect(Math.abs(rb.x + rb.width / 2 - (panel.x + panel.width / 2))).toBeLessThan(4);
  expect(rb.y).toBeGreaterThan(mb.y + mb.height);
  await expect(reason).toHaveCSS("color", "rgb(154, 160, 168)");
  await page.waitForTimeout(1500); // meshes load
  await page.screenshot({ path: test.info().outputPath("expanded.png") });
  await expanded.getByRole("button", { name: "Select option 2" }).click();
  await expect.poll(() => posted.at(-1)).toEqual({ event: "picked", data: { design_id: "grid2" } });
});
