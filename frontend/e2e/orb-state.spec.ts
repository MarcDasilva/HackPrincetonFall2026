import { test, expect } from "@playwright/test";

const box = async (l: import("@playwright/test").Locator) => (await l.boundingBox())!;

// Catches the orb's loading state misfiring: "Processing…" showing before the orb reaches the top, overlapping the Capture pills, or lingering after the run ends.
test("orb enters loading at the top while a run is busy, then leaves it", async ({ page }) => {
  // Fake backend: the run stays queued until the test flips it to done.
  let status = "queued";
  await page.route("**/api/patients", (r) => r.fulfill({ json: { id: "t1", status } }));
  await page.route("**/api/patients/t1", (r) => r.fulfill({ json: { id: "t1", status } }));

  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  const orb = page.getByTestId("orb");
  const capture = page.getByRole("button", { name: "Capture Ear" });
  await expect(orb).toHaveAttribute("data-state", "idle");

  await page.getByTestId("hearing-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await capture.click();
  await page.getByRole("button", { name: "Take picture" }).click();
  await expect(page.getByTestId("attachment")).toBeVisible();
  await page.waitForTimeout(800); // panel retract
  await page.getByRole("button", { name: "Send" }).click();

  // Mid-rise the orb is active, not loading — the sub text waits for the orb to land.
  await expect(orb).toHaveAttribute("data-state", "active");
  await expect(orb).toHaveAttribute("data-state", "loading", { timeout: 2000 });
  const sub = orb.getByRole("status");
  await expect(sub).toHaveText("Processing…");
  await page.waitForTimeout(700); // 0.6s rise-in
  // Under the sphere, above the Capture pills — the roomier gap is ABOVE the text, so it reads as the pills' caption rather than the sphere's.
  const o = await box(orb), t = await box(sub), cap = await box(capture);
  const above = t.y - (o.y + o.height * 0.9), below = cap.y - (t.y + t.height);
  expect(below).toBeGreaterThanOrEqual(4);
  expect(above).toBeGreaterThan(below);
  // SAME colour and font as the Capture Ear label, at 18px on screen even when the orb is scaled down to fit — the orb's scale must not shrink the text.
  const style = (l: import("@playwright/test").Locator) => l.evaluate((e) => { const c = getComputedStyle(e); return [c.color, c.fontFamily, (parseFloat(c.fontSize) * e.getBoundingClientRect().width / (e as HTMLElement).offsetWidth).toFixed(1)]; });
  const [color, font, size] = await style(sub), [capColor, capFont] = await style(capture);
  expect([color, font, size]).toEqual([capColor, capFont, "18.0"]);
  await page.screenshot({ path: "test-results/orb-loading.png" });

  status = "done";
  await expect(orb).toHaveAttribute("data-state", "active", { timeout: 4000 });
  await expect(sub).toHaveCount(0);
});

// Catches the shimmer going missing (static text) or breaking the grey: the text must animate its highlight band while showing, with the base colour still #757575.
test("Processing text shimmers", async ({ page }) => {
  await page.route("**/api/patients", (route) => route.fulfill({ status: 202, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ id: "abc123abc123" }) }));
  await page.route("**/api/patients/abc123abc123", (route) => route.fulfill({ contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ status: "running", step: "ear", files: {} }) }));
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await page.getByTestId("hearing-input").setInputFiles({ name: "audiogram.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") });
  await page.getByTestId("add-input").setInputFiles({ name: "ear.png", mimeType: "image/png", buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64") });
  await page.getByRole("button", { name: "Send" }).click();
  const sub = page.getByTestId("orb").getByRole("status");
  await expect(sub).toHaveText("Processing…", { timeout: 6000 });
  await page.waitForTimeout(800);
  const pos = () => sub.evaluate((e) => getComputedStyle(e).backgroundPosition);
  const a = await pos();
  await page.waitForTimeout(600);
  expect(await pos()).not.toBe(a);
  expect(await sub.evaluate((e) => getComputedStyle(e).color)).toBe("rgb(117, 117, 117)");
  await page.screenshot({ path: "test-results/processing-shimmer.png", clip: { x: 440, y: 380, width: 400, height: 120 } });
});
