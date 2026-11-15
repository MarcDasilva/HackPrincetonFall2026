import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import { localHead, mockStudy } from "./mockBackend";

const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "*" };
const RUN = "d60d88e7550d"; // the dev chord's run (Dashboard DEV_RUN_ID)
// A real earpiece (preview.png, earpiece*.glb) when this checkout has one (backend/data is local); otherwise a 1x1 PNG.
const PREVIEW_DIR = process.env.AID_FIXTURE_DIR ?? "../backend/data/patients/8e0c9758fead/aid/cone";
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
// Two directions (front, aided side) shared by three scenes: the real FDTD runs in the workers, kept short.
const SCENES = [
  { id: "s1", name: "Dinner table", sound: "family talking", why: "They eat with family daily.", weight: 3, sources: [{ role: "talker", az: 0, el: 0, level_db: 65 }] },
  { id: "s2", name: "Friend on the right", sound: "friend talking", why: "Aided side.", weight: 2, sources: [{ role: "talker", az: 90, el: 0, level_db: 60 }] },
  { id: "s3", name: "Busy cafe", sound: "cafe chatter", why: "Noise at the front.", weight: 1, sources: [{ role: "talker", az: 90, el: 0, level_db: 65 }, { role: "babble", az: 0, el: 0, level_db: 60 }] },
];
const WAVE = JSON.parse(fs.readFileSync("public/sim/wave_check_example.json", "utf8"));
const OPTIONS = [1, 2, 3, 4].map((i) => ({ id: `grid${i}`, reason: `Reason for option ${i}.`, key_met: `${5 - i} of 4`, objective: i, gain_mean_db: Array(18).fill(4 + i), files: { "preview.png": `aid/grid${i}/preview.png`, "earpiece_print.stl": `aid/grid${i}/earpiece_print.stl` } }));

/** The agents server's lead (agents/src/horn_study/server.py), as a small stage machine with the real copy. */
async function mockLead(page: Page, log: string[]) {
  const s: Record<string, unknown> = { run_id: RUN, stage: "launched", reply: "Four agents are researching your aid. Ask me anything.", ear: "left", status: "running" };
  let polls = 0;
  const go = (stage: string, reply: string, extra: Record<string, unknown> = {}) => Object.assign(s, { stage, reply, launch_requested: true }, extra);
  await page.route(`**/lead/${RUN}`, async (route) => {
    const req = route.request();
    if (req.method() === "OPTIONS") return route.fulfill({ headers: CORS });
    if (req.method() === "GET") {
      // Moving stages: research finishes on the 1st poll, the scene picker on the next.
      polls++;
      if (s.stage === "launched") go("sim_ready", "Great, all done. Ready to run the simulation?", { status: "completed" });
      else if (s.stage === "sim_prep") go("sim_running", "The simulation is running. Click the orb to watch.", { scenes: SCENES });
    } else {
      const { message, event, data } = req.postDataJSON();
      log.push(event ?? message);
      if (event === "sims_done") go("design_ready", "Great, I have enough data to develop a hearing aid. Ready to see it?", { sims: data });
      else if (event === "options") go("options", "Here are four options, each with its reasoning. Pick the one you want.", { options: data.options });
      else if (event === "picked") go("validating", "Let's check it really helps you: your simulations are running again with that earpiece in your ear.", { picked: data.design_id });
      else if (event === "validated") go("final", `${data.summary} Want your final report and the file to print?`, { validation: data });
      else if (message === "yes" && s.stage === "sim_ready") go("sim_count", "How many simulations should I run? Pick a number from 1 to 100.");
      else if (message === "3" && s.stage === "sim_count") go("sim_prep", "Setting up 3 simulations from your profile and the research.");
      else if (message === "yes" && s.stage === "design_ready") go("designing", "Designing your hearing aid. Four options are on the way.");
      else if (message === "yes" && s.stage === "final") go("done", "Your report is ready, with the file to print.", { report: "Your hearing test shows a high-frequency loss.\n\nOption 2 helped in every scene." });
    }
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ ...s, polls }) });
  });
}

/** backend/app/sim_api.py: the average-ear grid the repo ships, a design that finishes on its first poll, and stub files. */
async function mockSim(page: Page, asked: string[]) {
  const grid = JSON.parse(fs.readFileSync("public/sim/ear_grid.json", "utf8"));
  grid.patient = { id: RUN, average_ear: false, side: "left", audiogram_db_hl: { "250": 15, "500": 20, "1000": 30, "2000": 45, "4000": 55, "6000": 55 }, audiogram_is_example: false };
  let picked: string | null = null;
  await page.route("**/api/sim/patients/**", (route) => {
    const url = route.request().url();
    asked.push(`${route.request().method()} ${url.replace(/^.*\/patients\//, "")}`);
    // /files/ first: "files/grid1/preview.png" also contains "/grid".
    if (url.includes("/files/")) {
      // Real renders and meshes when this checkout has them; a .glb that fails to load only shows the viewer's error line.
      const name = url.split("/").pop()!.split("?")[0], real = `${PREVIEW_DIR}/${name}`;
      const body = fs.existsSync(real) ? fs.readFileSync(real) : PNG;
      return route.fulfill({ contentType: name.endsWith(".png") ? "image/png" : name.endsWith(".glb") ? "model/gltf-binary" : "model/stl", body });
    }
    // The picked earpiece's 3D wave check: done on its first poll, for whichever design was asked for.
    if (url.includes("/wave_check")) {
      if (route.request().method() === "POST") { picked = route.request().postDataJSON().design_id; return route.fulfill({ status: 202, contentType: "application/json", body: "{}" }); }
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(picked ? { status: "done", design_id: picked, result: { ...WAVE, design_id: picked } } : { status: "none" }) });
    }
    if (url.includes("/grid")) return route.fulfill({ contentType: "application/json", body: JSON.stringify(grid) });
    if (route.request().method() === "POST") return route.fulfill({ status: 202, contentType: "application/json", body: "{}" });
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ status: "done", result: { design: OPTIONS[0], options: OPTIONS } }) });
  });
}

const send = async (page: Page, text: string) => {
  await page.locator("textarea").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
};

// Catches the lead skipping a gate the patient must pass after research: ready? -> how many -> watch the runs -> ready to see it? -> four options -> pick -> validate in the orb -> report with the print file. Also that the runs keep going with the orb closed, and that the research boxes fade once the patient says yes.
test("after research the lead runs the simulations, offers four aids, validates the pick and hands over the print file", async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const said: string[] = [], asked: string[] = [];
  await mockStudy(page);
  await mockLead(page, said);
  await mockSim(page, asked);
  // A real reconstructed head when this checkout has one (backend/data is local); otherwise the tiles draw the average head.
  const headGlb = localHead();
  if (headGlb) await page.route("**/files/head/head_ears.glb", (route) => route.fulfill({ contentType: "model/gltf-binary", body: fs.readFileSync(headGlb) }));
  await page.route(/\/api\/patients\/[a-f0-9]{12}$/, (route) => route.fulfill({ status: 404, headers: CORS, contentType: "application/json", body: "{}" }));
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await page.locator("body").click({ position: { x: 5, y: 400 } });
  await page.keyboard.down("1");
  await page.keyboard.down("2");
  await page.keyboard.up("2");
  await page.keyboard.up("1");

  const line = page.getByTestId("orb").getByRole("status");
  const start = page.getByRole("button", { name: "Start simulation" });
  await expect(page.getByTestId("agent-hearing_research")).toBeVisible();
  await expect(line).toHaveText("Great, all done. Ready to run the simulation?", { timeout: 10_000 });
  await expect(start).toHaveCount(0);

  await send(page, "yes");
  await expect(line).toHaveText("How many simulations should I run? Pick a number from 1 to 100.");
  await expect(page.getByTestId("agent-hearing_research")).toHaveCount(0, { timeout: 5_000 });
  await send(page, "3");
  await expect(line).toHaveText("The simulation is running. Click the orb to watch.", { timeout: 10_000 });

  await page.waitForTimeout(1000); // orb rise
  await start.click();
  const sims = page.getByTestId("sims");
  await expect(sims).toHaveCSS("opacity", "1", { timeout: 10_000 });
  await expect(sims.getByTestId("sim-tile")).toHaveCount(3);
  await expect(sims.locator("[data-testid=sim-tile][data-done]")).toHaveCount(3, { timeout: 150_000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: test.info().outputPath("runs.png") });
  // A tile opens its run: the 3D wave field on the head, the ear's 2D wave slices, the live pixel field, and the run's numbers. Catches the detail view losing a figure or its way back.
  await sims.getByTestId("sim-tile").first().click();
  const detail = page.getByTestId("sim-detail");
  await expect(detail.getByTestId("sim-3d")).toHaveAttribute("src", /\/head\/viewer\.html\?embed=1&run=az000_el%2B00&rig=1&ear=left(&|$)/);
  await expect(detail.getByTestId("sim-ear")).toHaveAttribute("src", /\/waves\/left\/index\.html\?embed=1&run=az000_el%2B00&disp=slices$/);
  // No head grid in this mock: c says so instead of painting a field.
  await expect(detail.getByText(/No head grid for this patient/).first()).toBeVisible({ timeout: 10_000 });
  await expect(detail.getByTestId("sim-info")).toContainText("Speech heard");
  await expect(detail.getByTestId("sim-deficit")).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: test.info().outputPath("detail.png") });
  await detail.getByRole("button", { name: "All simulations" }).click();
  await expect(sims.getByTestId("sim-tile")).toHaveCount(3);
  await page.getByRole("button", { name: "Exit simulation" }).click();
  await expect(line).toHaveText("Great, I have enough data to develop a hearing aid. Ready to see it?");
  await page.waitForTimeout(2500); // zoom out, then the chrome fades back in
  await page.screenshot({ path: test.info().outputPath("ready.png") });

  await send(page, "yes");
  const options = page.getByTestId("aid-option");
  await expect(options).toHaveCount(4, { timeout: 15_000 });
  await page.waitForTimeout(800); // metal rings draw
  await page.screenshot({ path: test.info().outputPath("options.png") });
  // Hover lifts the card; the expanded view holds BOTH models and the reason. Catches a card that never lifts, or an expanded view missing a model.
  const before = (await options.nth(1).boundingBox())!.y;
  await options.nth(1).hover();
  await page.waitForTimeout(400);
  expect((await options.nth(1).boundingBox())!.y).toBeLessThan(before - 4);
  await page.screenshot({ path: test.info().outputPath("options-hover.png") });
  // The design request carried every scene's deficit, for the study's (left) ear.
  expect(asked).toContain("POST d60d88e7550d/design?ear=left");

  await options.nth(1).click({ position: { x: 40, y: 40 } });
  const expanded = page.getByTestId("aid-expanded");
  await expect(expanded.getByTestId("aid-model")).toHaveCount(2);
  await expect(expanded).toContainText("Reason for option 2.");
  await page.waitForTimeout(1500); // meshes load
  await page.screenshot({ path: test.info().outputPath("options-expanded.png") });
  await expanded.getByRole("button", { name: "Select option 2" }).click();
  // Picking reopens the orb on the same runs, now scored with the aid. Visible, not just opaque: the hidden layer keeps its old opacity.
  await expect(sims).toBeVisible({ timeout: 10_000 });
  await expect(sims).toHaveCSS("opacity", "1");
  // The SAME scenes, now normal hearing against the aid — from the PICKED earpiece in the wave sim. Catches the reopen never asking for the wave check, or for the wrong design (the mock answers only the design asked for).
  await expect(sims.getByTestId("sim-sii").first()).toContainText("aid", { timeout: 15_000 });
  await expect(sims.getByTestId("sim-sii").first()).toContainText("normal");
  expect(asked).toContain("POST d60d88e7550d/design/wave_check?ear=left");
  await page.screenshot({ path: test.info().outputPath("validate.png") });
  await page.getByRole("button", { name: "Exit simulation" }).click();
  await expect(line).toContainText("With option 2 you hear");
  await expect(line).toContainText("Want your final report and the file to print?");

  // the report is a downloaded PDF and the PICKED design's print file, never a pop-up (e2e/report-download.spec.ts checks the PDF)
  const downloads: string[] = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  const stl = page.waitForRequest((r) => r.url().includes("/design/files/grid2/earpiece_print.stl?ear=left"), { timeout: 60_000 });
  await send(page, "yes");
  await stl;
  await expect.poll(() => downloads.length, { timeout: 60_000 }).toBe(2);
  expect(downloads.some((n) => n.endsWith(".pdf")) && downloads.some((n) => n.endsWith(".stl"))).toBe(true);
  await expect(page.getByTestId("final-report")).toHaveCount(0);
  await page.waitForTimeout(800);
  await page.screenshot({ path: test.info().outputPath("report.png") });
  expect(said).toEqual(["", "yes", "3", "sims_done", "yes", "options", "picked", "validated", "yes"]);
});
