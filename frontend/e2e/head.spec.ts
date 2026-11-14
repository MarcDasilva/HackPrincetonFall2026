import { test, expect, type Page } from "@playwright/test";
import { capsOn, mockBackend, PID } from "./mockBackend";

const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "*" };

const open = async (page: Page) => {
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
};
/** Counts the lead's opening calls, so a spec can tell WHEN the lead opened. */
const leadCalls = async (page: Page) => {
  const sent: string[] = [];
  await page.route(`**/lead/${PID}`, async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers: CORS });
    sent.push(route.request().postDataJSON().message);
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: "Your ears and head are ready.", awaiting_launch: false, launch_requested: false }) });
  });
  return sent;
};

// Catches the head row never showing, landing on the ear rows or the Capture pills, or the lead opening while the head row is still on screen.
test("the head row reveals between the ear rows and the lead opens only once it is gone", async ({ page }) => {
  test.setTimeout(60_000);
  await mockBackend(page);
  const sent = await leadCalls(page);
  await open(page);
  await capsOn(page);
  await expect(page.getByTestId("attachment-left")).toBeVisible();
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
  // Practice attaches the dev face (public/dev/face.png) when the file is there; the run starts either way.
  await page.keyboard.press("Enter");

  const headRow = page.getByTestId("ear-row-head");
  await expect(headRow.getByTestId("ear-view-1")).toBeVisible({ timeout: 15_000 });
  // The run is busy, but "Processing…" stays hidden while the cards are on screen — it sat on top of them.
  await expect(page.getByTestId("orb").getByRole("status")).toHaveCount(0);
  await expect(headRow).toContainText("Head");
  // The small cards carry NO caption (only an expanded view names itself).
  await expect(headRow.getByTestId("ear-view-0").getByAltText("Face points")).toBeVisible();
  await expect(headRow.getByTestId("ear-view-0")).not.toContainText("Face points");
  // The row containers never animate (GSAP moves the cards), so they give the resting layout: the head in the MIDDLE, between the left ear above and the right ear below, all clear of the Capture pills.
  const l = (await page.getByTestId("ear-row-left").boundingBox())!;
  const r = (await page.getByTestId("ear-row-right").boundingBox())!;
  const h = (await headRow.boundingBox())!;
  const pill = (await page.getByRole("button", { name: "Capture Ears & Face" }).boundingBox())!;
  expect(h.y).toBeGreaterThan(l.y + l.height);
  expect(r.y).toBeGreaterThan(h.y + h.height);
  expect(r.y + r.height).toBeLessThan(pill.y);
  await page.waitForTimeout(2000); // the fan into the row
  await page.screenshot({ path: "test-results/head-row.png" });

  await expect(page.getByTestId("orb").getByRole("status")).toHaveText("Your ears and head are ready.", { timeout: 15_000 });
  await expect(headRow).toHaveCount(0);
  expect(sent).toEqual([""]);
  await page.waitForTimeout(1200);
  await page.screenshot({ path: "test-results/head-lead.png" });
});

// Catches a patient without a head (a backend from before the head stage) stranding the lead: no files.head, so once the ear rows are gone the lead opens and no head row ever shows.
test("without files.head the lead still opens after the ear rows", async ({ page }) => {
  test.setTimeout(60_000);
  await mockBackend(page, { head: false });
  const sent = await leadCalls(page);
  await open(page);
  await capsOn(page);
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
  await expect(page.getByTestId("attachment-right")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("ear-row-right").getByTestId("ear-view-2")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("ear-row-head").getByTestId("ear-view-0")).toHaveCount(0);
  await expect(page.getByTestId("orb").getByRole("status")).toHaveText("Your ears and head are ready.", { timeout: 15_000 });
  expect(sent).toEqual([""]);
});

/** Zooms into the orb for the dev run with the given patient files, and returns the sims overlay. */
const zoomIn = async (page: Page, files: Record<string, unknown>) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.route(/\/api\/patients\/[a-f0-9]{12}$/, (route) => route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ status: "done", ears: ["left", "right"], files }) }));
  await page.route("**/waves/*/runs.json", (route) => route.fulfill({ path: "e2e/fixtures/runs.json", headers: CORS }));
  // Stub viewers: the spec checks the bento's boxes and URLs, not live WebGL.
  await page.route("**/waves/*/index.html*", (route) => route.fulfill({ contentType: "text/html", body: "<body style='margin:0;background:#fbfaf8'>ear viewer</body>" }));
  await page.route("**/head/viewer.html*", (route) => route.fulfill({ contentType: "text/html", body: "<body style='margin:0;background:#e8eef4;font:24px system-ui;display:grid;place-items:center;height:100vh'>head viewer</body>" }));
  await page.route("**/api/patients", (route) => route.abort());
  await page.route("**/lead/*", (route) =>
    route.request().method() === "OPTIONS" ? route.fulfill({ headers: CORS })
      : route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ reply: "Ready.", awaiting_launch: false, launch_requested: false }) }));
  await open(page);
  await page.locator("body").click({ position: { x: 5, y: 400 } });
  await page.keyboard.down("3");
  await page.keyboard.down("4");
  await page.keyboard.up("4");
  await page.keyboard.up("3");
  const start = page.getByRole("button", { name: "Start simulation" });
  await expect(start).toBeVisible();
  await page.waitForTimeout(1000); // orb rise
  await start.click();
  const sims = page.getByTestId("sims");
  await expect(sims).toHaveCSS("opacity", "1", { timeout: 20_000 });
  return sims;
};
const waves = Object.fromEntries(["left", "right"].map((ear) => [ear, { waves: `/api/patients/d60d88e7550d/waves/${ear}/index.html` }]));

// Catches a head patient still getting two separate ear viewers per box (twice the WebGL contexts, and no head), or the direction tag arriving unescaped so every box shows the same default view.
test("a patient with a head model gets ONE head viewer per direction box", async ({ page }) => {
  test.setTimeout(90_000);
  const sims = await zoomIn(page, { ...waves, head: { "head_ears.glb": "/api/patients/d60d88e7550d/files/head/head_ears.glb", "head.json": "/api/patients/d60d88e7550d/files/head/head.json", viewer: "/api/patients/d60d88e7550d/head/viewer.html" } });
  const boxes = sims.getByTestId("wave-box");
  await expect(boxes).toHaveCount(5);
  for (const box of await boxes.all()) await expect(box.locator("iframe")).toHaveCount(1);
  const first = boxes.first().locator("iframe");
  await expect(first).toHaveAttribute("src", /\/api\/patients\/d60d88e7550d\/head\/viewer\.html\?embed=1&run=az000_el%2B00$/);
  await expect(first).toHaveAttribute("title", "Head, Front 0°");
  await expect(boxes.first()).toContainText("Both ears");
  await expect(boxes.nth(2)).toContainText("Head, Side 90°");
  // One viewer per box: the boxes fit ~4:3, not the 2:1 two ear viewers need.
  const b = (await boxes.first().boundingBox())!;
  expect(b.width / b.height).toBeLessThan(1.8);
  // The gain panel is unchanged: both ears' lines.
  await expect(sims.getByTestId("wave-panel").locator("svg path")).toHaveCount(2);
  await page.waitForTimeout(500);
  await page.screenshot({ path: "test-results/sims-head.png" });
});

// Catches an older patient (no files.head) losing its viewers: each box keeps the left and right ear's wave viewers side by side.
test("a patient without a head model keeps two ear viewers per box", async ({ page }) => {
  test.setTimeout(90_000);
  const sims = await zoomIn(page, waves);
  const views = sims.getByTestId("wave-box").first().locator("iframe");
  await expect(views).toHaveCount(2);
  await expect(views.nth(0)).toHaveAttribute("src", /\/waves\/left\/index\.html\?embed=1&run=az000_el%2B00$/);
  await expect(views.nth(1)).toHaveAttribute("src", /\/waves\/right\/index\.html\?embed=1&run=az000_el%2B00$/);
  await expect(sims.getByTestId("wave-box").first()).not.toContainText("Both ears");
  await page.screenshot({ path: "test-results/sims-ears.png" });
});

// Catches the raw selfie showing in the head row: when MediaPipe finds no face (selfie.jpg but no landmarks.jpg), the row is the head model ALONE — never the plain photo.
test("the head row never shows the raw selfie", async ({ page }) => {
  test.setTimeout(60_000);
  await mockBackend(page);
  const files = Object.fromEntries(["left", "right"].map((ear) => [ear, Object.fromEntries(["overlay.jpg", "mask.png", "ear.glb"].map((f) => [f, `/api/patients/${PID}/files/${ear}/${f}`]))]));
  const head = Object.fromEntries(["selfie.jpg", "head.glb", "head_ears.glb", "head.json"].map((f) => [f, `/api/patients/${PID}/files/head/${f}`]));
  await page.route(`**/api/patients/${PID}`, (route) => route.fulfill({ contentType: "application/json", headers: { "access-control-allow-origin": "*" },
    body: JSON.stringify({ status: "running", step: "left:context", files: { ...files, head } }) }));
  await leadCalls(page);
  await open(page);
  await capsOn(page);
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
  await page.keyboard.press("Enter");
  const headRow = page.getByTestId("ear-row-head");
  await expect(headRow.getByTestId("ear-view-0")).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(800);
  await expect(headRow.getByTestId("ear-view-1")).toHaveCount(0);
  await expect(headRow.locator("img")).toHaveCount(0);
});
