import { test, expect } from "@playwright/test";
import { capsOn, mockBackend, PID } from "./mockBackend";

const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "*" };

// Catches the lead never taking over after the ear cards vanish, its reply landing anywhere but the orb line, or the chat box still starting runs instead of talking to it.
test("after the ear cards vanish, the lead speaks in the orb line and the chat box talks to it", async ({ page }) => {
  await mockBackend(page);
  const sent: string[] = [];
  await page.route(`**/lead/${PID}`, async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers: CORS });
    const { message } = route.request().postDataJSON();
    sent.push(message);
    const reply = message ? "Running and restaurants noted. Launch the research agents?" : "Your ear is ready. What do you want to hear better?";
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ reply, awaiting_launch: !!message, launch_requested: false }) });
  });

  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await capsOn(page);
  await expect(page.getByTestId("hearing-attachment")).toBeVisible();
  await expect(page.getByTestId("attachment")).toBeVisible();
  await page.keyboard.press("Enter");

  const line = page.getByTestId("orb").getByRole("status");
  await expect(page.getByTestId("ear-view-2")).toBeVisible({ timeout: 15_000 });
  await expect(line).toHaveText("Your ear is ready. What do you want to hear better?", { timeout: 15_000 });
  expect(sent).toEqual([""]);
  await expect(page.getByTestId("ear-view-0")).toHaveCount(0);

  await page.locator("textarea").fill("I run and eat out a lot");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(line).toHaveText("Running and restaurants noted. Launch the research agents?");
  expect(sent).toEqual(["", "I run and eat out a lot"]);
  await expect(page.locator("textarea")).toHaveValue("");
  await page.waitForTimeout(500);
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
  await expect(page.getByTestId("ear-views")).toHaveCount(0);
  await page.waitForTimeout(1200); // 0.9 s card drop / orb rise
  await page.screenshot({ path: "test-results/lead-skip.png" });
});
