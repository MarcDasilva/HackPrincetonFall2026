import { test, expect } from "@playwright/test";
import { capsOn, mockBackend, mockStudy, PID } from "./mockBackend";

// The real opening line (agents/src/horn_study/lead.py OPENING): two lines under the orb.
const OPENING = "Anything I should know before I launch research based on your audiogram?";
const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "*" };

// Catches the lead never taking over after the ear cards vanish, its reply landing anywhere but the orb line, or the chat box still starting runs instead of talking to it.
test("after the ear cards vanish, the lead speaks in the orb line and the chat box talks to it", async ({ page }) => {
  await mockBackend(page);
  const sent: string[] = [];
  await page.route(`**/lead/${PID}`, async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers: CORS });
    const { message } = route.request().postDataJSON();
    sent.push(message);
    const reply = message ? "Noted. May I begin?" : OPENING;
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ reply, awaiting_launch: !!message, launch_requested: false }) });
  });

  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await capsOn(page);
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
  await expect(page.getByTestId("attachment-left")).toBeVisible();
  await page.keyboard.press("Enter");

  const line = page.getByTestId("orb").getByRole("status");
  await expect(page.getByTestId("ear-row-left").getByTestId("ear-view-2")).toBeVisible({ timeout: 15_000 });
  await expect(line).toHaveText(OPENING, { timeout: 15_000 });
  expect(sent).toEqual([""]);
  await expect(page.getByTestId("ear-row-left").getByTestId("ear-view-0")).toHaveCount(0);

  await page.locator("textarea").fill("I run and eat out a lot");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(line).toHaveText("Noted. May I begin?");
  expect(sent).toEqual(["", "I run and eat out a lot"]);
  await expect(page.locator("textarea")).toHaveValue("");
  await page.waitForTimeout(1200); // orb makes room for the reply (0.9 s)
  // The reply is plain text — the shimmer belongs to "Processing…" only — and sits centered between the sphere and the Capture pills.
  expect(await line.evaluate((el) => getComputedStyle(el).animationName)).not.toContain("shimmer");
  const text = (await line.boundingBox())!;
  const pills = (await page.getByRole("button", { name: "Capture Ears & Face" }).boundingBox())!;
  const orb = (await page.getByTestId("orb").boundingBox())!;
  const sphereBottom = orb.y + orb.height / 2 + (orb.height * 0.8) / 2; // the sphere fills 80% of the orb canvas (ORB_FILL)
  expect(Math.abs(text.y + text.height / 2 - (sphereBottom + pills.y) / 2)).toBeLessThan(3);
  expect(text.y + text.height).toBeLessThan(pills.y);
  await page.screenshot({ path: "test-results/lead.png" });
});

// Catches the 1 + 2 chord not skipping straight to the lead: no upload, no run, no ear cards — the lead opens the conversation for the dev run, and typing "12" in the chat box must NOT trigger it.
test("holding 1 and 2 skips the upload and opens the lead", async ({ page }) => {
  const posted: string[] = [];
  await page.route("**/api/patients", (route) => (posted.push("run"), route.abort()));
  const asked: string[] = [];
  await page.route("**/lead/*", async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers: CORS });
    asked.push(route.request().url().split("/").pop()!);
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: "Your ear is ready. What do you want to hear better?", awaiting_launch: false, launch_requested: false }) });
  });
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  // Typing 1 then 2 INSIDE the chat box is just text.
  await page.locator("textarea").click();
  await page.keyboard.down("1");
  await page.keyboard.down("2");
  await page.keyboard.up("2");
  await page.keyboard.up("1");
  await page.waitForTimeout(500);
  expect(asked).toEqual([]);
  await page.locator("textarea").fill("");
  await page.locator("body").click({ position: { x: 5, y: 400 } });

  await page.keyboard.down("1");
  await page.keyboard.down("2");
  const line = page.getByTestId("orb").getByRole("status");
  await expect(line).toHaveText("Your ear is ready. What do you want to hear better?", { timeout: 10_000 });
  await page.keyboard.up("2");
  await page.keyboard.up("1");
  expect(asked).toEqual(["d60d88e7550d"]);
  expect(posted).toEqual([]);
  await expect(page.getByTestId("ear-row-left")).toHaveCount(0);
  await page.waitForTimeout(1200); // 0.9 s card drop / orb rise
  await page.screenshot({ path: "test-results/lead-skip.png" });
});

// Catches the orb being clickable before the simulations run (a launched study is NOT enough), the zoom leaving the dock or chat on screen, or the X / Escape failing to bring them back.
test("once the simulations run, clicking the orb zooms in and X or Escape zooms back out", async ({ page }) => {
  await page.route("**/api/patients", (route) => route.abort());
  // This spec is about the zoom, not the sims: an unknown patient keeps the wave viewers from loading and starving the animation.
  await page.route(/\/api\/patients\/[a-f0-9]{12}$/, (route) => route.fulfill({ status: 404, headers: CORS, contentType: "application/json", body: "{}" }));
  let launched = false;
  await mockStudy(page);
  await page.route("**/lead/*", async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers: CORS });
    // A poll (GET) after launch finds the simulations running; no scenes, so the orb shows the wave bento.
    const polled = route.request().method() === "GET";
    launched ||= !polled && route.request().postDataJSON().message === "yes";
    const stage = !launched ? "begin" : polled ? "sim_running" : "launched";
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ stage, reply: launched ? "Research is running." : "Launch the research agents?", awaiting_launch: !launched, launch_requested: launched }) });
  });
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
  const orb = page.getByTestId("orb");
  await expect(orb.getByRole("status")).toHaveText("Launch the research agents?", { timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Start simulation" })).toHaveCount(0);

  await page.locator("textarea").fill("yes");
  await page.getByRole("button", { name: "Send" }).click();
  const start = page.getByRole("button", { name: "Start simulation" });
  // The yes launches the study: the investigator boxes open without key 5, and the orb waits for the simulations.
  await expect(page.getByTestId("agent-hearing_research").getByTestId("traces")).toContainText("Finding from hearing_research");
  await expect(start).toHaveCount(0);
  await expect(start).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(1000); // orb rise
  await start.click();

  // toBeHidden ignores opacity, and MetalFx forces visibility: visible — so check the fade and that the chrome is inert.
  const card = page.getByTestId("drop-zone");
  await expect(card).toHaveCSS("opacity", "0");
  await expect(page.locator("[inert] textarea")).toHaveCount(1);
  await expect(page.locator('[inert] [aria-label="Profile"]')).toHaveCount(1);
  await expect(orb.getByRole("status")).toHaveCount(0);
  await page.waitForTimeout(1100); // 0.9 s zoom
  const box = (await orb.boundingBox())!;
  const vp = page.viewportSize()!;
  expect(Math.abs(box.y + box.height / 2 - vp.height / 2)).toBeLessThan(4);
  // The camera ends INSIDE the orb: far past the screen edges and faded out.
  expect(box.height).toBeGreaterThan(4 * vp.height);
  await expect(orb).toHaveCSS("opacity", "0");
  await page.screenshot({ path: "test-results/orb-zoomed.png" });

  await page.getByRole("button", { name: "Exit simulation" }).click();
  await expect(card).toHaveCSS("opacity", "1");
  await expect(page.locator("[inert]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Exit simulation" })).toHaveCount(0);

  await start.click();
  await expect(card).toHaveCSS("opacity", "0");
  await page.keyboard.press("Escape");
  await expect(card).toHaveCSS("opacity", "1");
  await expect(page.locator("[inert]")).toHaveCount(0);
  await expect(orb).toHaveCSS("opacity", "1");
  await page.locator("textarea").fill("back");
  await page.waitForTimeout(1200);
  await page.screenshot({ path: "test-results/orb-unzoomed.png" });
});

// Catches the 3 + 4 chord not landing on the clickable orb: no run, the lead opened for the dev run, and one click zooms in.
test("holding 3 and 4 skips to the clickable orb", async ({ page }) => {
  test.setTimeout(90_000);
  const posted: string[] = [];
  // Desktop width: the sims take 4/5 and the gain panel 1/5.
  await page.setViewportSize({ width: 1920, height: 1080 });
  // A two-ear patient with waves for both ears: five directions (fixtures/runs.json, cut from a real run) and a stub viewer page, so the spec checks the bento without ten live WebGL viewers.
  await page.route(/\/api\/patients\/[a-f0-9]{12}$/, (route) => route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ status: "done", ears: ["left", "right"],
    files: Object.fromEntries(["left", "right"].map((ear) => [ear, { waves: `/api/patients/d60d88e7550d/waves/${ear}/index.html` }])) }) }));
  await page.route("**/waves/*/runs.json", (route) => route.fulfill({ path: "e2e/fixtures/runs.json", headers: CORS }));
  await page.route("**/waves/*/index.html*", (route) => route.fulfill({ contentType: "text/html", body: "<body style='margin:0;background:#fbfaf8'>viewer</body>" }));
  await page.route("**/api/patients", (route) => (posted.push("run"), route.abort()));
  await page.route("**/lead/*", async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers: CORS });
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: "Your ear is ready.", awaiting_launch: false, launch_requested: false }) });
  });
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await page.locator("body").click({ position: { x: 5, y: 400 } });
  await page.keyboard.down("3");
  await page.keyboard.down("4");
  await page.keyboard.up("4");
  await page.keyboard.up("3");
  const start = page.getByRole("button", { name: "Start simulation" });
  await expect(start).toBeVisible();
  await page.waitForTimeout(1000); // orb rise
  // A drag spins the orb and must NOT count as the click that zooms in.
  const orb = page.getByTestId("orb");
  const b = (await orb.boundingBox())!;
  await page.mouse.move(b.x + b.width / 2 - 100, b.y + b.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2 + 100, b.y + b.height / 2, { steps: 10 });
  await page.screenshot({ path: "test-results/orb-drag.png" });
  await page.mouse.up();
  await page.waitForTimeout(300);
  await expect(orb).not.toHaveAttribute("data-zoomed");
  await expect(page.getByTestId("drop-zone")).toHaveCSS("opacity", "1");
  await start.click();
  await page.waitForTimeout(600); // mid-flight, before the fade finishes
  await page.screenshot({ path: "test-results/chord-34-mid.png" });
  await expect(page.getByTestId("drop-zone")).toHaveCSS("opacity", "0");
  await expect(page.getByRole("button", { name: "Exit simulation" })).toBeVisible();
  expect(posted).toEqual([]);

  // Inside the orb: one box per speaker direction, sized by the picker, each with the LEFT and RIGHT ear's viewer side by side; the gain panel on the right.
  const sims = page.getByTestId("sims");
  await expect(sims).toHaveCSS("opacity", "1", { timeout: 20_000 });
  const boxes = sims.getByTestId("wave-box");
  await expect(boxes).toHaveCount(5);
  await sims.locator("select").selectOption("3");
  await expect(boxes).toHaveCount(3);
  const views = boxes.first().locator("iframe");
  await expect(views).toHaveCount(2);
  // The direction rides in the query, + escaped — a raw "+" would arrive as a space and the viewer would fall back to the side view.
  await expect(views.nth(0)).toHaveAttribute("src", /\/waves\/left\/index\.html\?embed=1&run=az000_el%2B00$/);
  await expect(views.nth(1)).toHaveAttribute("src", /\/waves\/right\/index\.html\?embed=1&run=az000_el%2B00$/);
  const vp = page.viewportSize()!;
  // The boxes fill the section: their bottom edge reaches the bottom of the screen.
  const last = (await boxes.last().boundingBox())!;
  expect(last.y + last.height).toBeGreaterThan(vp.height - 40);
  const panel = sims.getByTestId("wave-panel");
  expect((await panel.boundingBox())!.x).toBeGreaterThan(vp.width * 0.75);
  await expect(panel.locator("svg path")).toHaveCount(2);
  await expect(panel.locator("tbody tr")).toHaveCount(3);
  await page.waitForTimeout(500);
  await page.screenshot({ path: "test-results/sims.png" });
  await page.keyboard.press("Escape");
  await expect(sims).toHaveCount(0);
  await page.waitForTimeout(1100);
  await page.screenshot({ path: "test-results/chord-34.png" });
});
