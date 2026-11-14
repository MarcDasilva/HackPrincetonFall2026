import { test, expect, type Page } from "@playwright/test";
import { capsOn, mockBackend, mockStudy, PID } from "./mockBackend";

const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "*" };
const session = (run_id: string, reply: string, launched: boolean, updated_at: number) =>
  ({ run_id, reply, stage: launched ? "launched" : "begin", awaiting_launch: !launched, launch_requested: launched, study_id: launched ? `${run_id}-1` : null, status: launched ? "running" : "none", updated_at });
const SESSIONS = [
  session("aaaaaaaaaaaa", "Four agents are researching your aid. Ask me anything.", true, 1794690000),
  session("bbbbbbbbbbbb", "Noted. May I begin?", false, 1794680000),
];

async function mockAgents(page: Page, posted: string[]) {
  await mockStudy(page);
  await page.route("**/sessions", (route) => route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify(SESSIONS) }));
  await page.route("**/lead/*", async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers: CORS });
    const id = route.request().url().split("/").pop()!;
    if (route.request().method() === "POST") posted.push(`${id}:${route.request().postDataJSON().message}`);
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify(SESSIONS.find((x) => x.run_id === id)) });
  });
  // Backend: the saved runs are finished; a 404 keeps the wave viewers from loading.
  await page.route(/\/api\/patients\/[a-f0-9]{12}$/, (route) => route.fulfill({ status: 404, headers: CORS, contentType: "application/json", body: "{}" }));
}

// Catches the picker under the chat card not listing saved sessions, a switch not restoring that session's line and research view (or leaking the previous one's), a reopen being sent as a patient message, or "New session" not returning to a fresh upload.
test("the session picker switches between saved sessions and back to a new one", async ({ page }) => {
  const posted: string[] = [];
  await mockAgents(page, posted);
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  const picker = page.getByTestId("session-picker");
  await expect(picker.locator("option")).toHaveCount(3);
  await expect(picker).toHaveValue("new");
  // Under the card, not overlapping it.
  const card = (await page.getByTestId("drop-zone").boundingBox())!;
  expect((await picker.boundingBox())!.y).toBeGreaterThanOrEqual(card.y + card.height);

  const line = page.getByTestId("orb").getByRole("status");
  await picker.selectOption("aaaaaaaaaaaa");
  await expect(line).toHaveText("Four agents are researching your aid. Ask me anything.");
  await expect(page.getByTestId("agent-ear_fit_research").getByTestId("summary")).toHaveText("A concha lock holds while running.");
  // Research is still running: the orb opens ONLY once the simulations run.
  await expect(page.getByRole("button", { name: "Start simulation" })).toHaveCount(0);
  await expect(page).toHaveURL(/\?session=aaaaaaaaaaaa$/);
  await expect(page.getByTestId("session-id")).toHaveText("aaaaaaaaaaaa");
  await page.waitForTimeout(3500); // orb rise, agent flight and fade
  // The picker stays inside the screen once the card has dropped to the bottom.
  const vp = page.viewportSize()!;
  const pb = (await picker.boundingBox())!;
  expect(pb.y + pb.height).toBeLessThan(vp.height);
  await page.screenshot({ path: "test-results/sessions-launched.png" });

  await picker.selectOption("bbbbbbbbbbbb");
  await expect(line).toHaveText("Noted. May I begin?");
  await expect(page.getByTestId("agent-ear_fit_research")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Start simulation" })).toHaveCount(0);
  expect(posted).toEqual(["aaaaaaaaaaaa:", "bbbbbbbbbbbb:"]);

  await picker.selectOption("new");
  await expect(line).toHaveCount(0);
  await expect(page).toHaveURL(/\/zz-preview$/);
  await expect(page.getByTestId("session-id")).toHaveCount(0);
  await expect(picker).toHaveValue("new");
  await page.waitForTimeout(1200); // card back to center
  await page.screenshot({ path: "test-results/sessions-new.png" });
});

// Catches a started run not becoming its own session until the lead speaks, or a session left mid-processing coming back as "done" — no polling, so its ear rows never fill and its lead never opens.
test("starting a run creates its session, and leaving and returning resumes the run", async ({ page }) => {
  test.setTimeout(75_000); // the ear rows reveal twice: on return and after the reload
  await mockBackend(page);
  const created: string[] = [];
  const list: object[] = [];
  await page.route(`**/sessions/${PID}`, (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers: CORS });
    created.push(PID);
    const s = { ...session(PID, "", false, 1794700000), stage: "new", awaiting_launch: false };
    if (!list.length) list.push(s);
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify(s) });
  });
  await page.route("**/sessions", (route) => route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify(list) }));
  // Reopening asks the server for the session: still "new", the lead has not spoken.
  await page.route(`**/lead/${PID}`, (route) => route.request().method() === "GET"
    ? route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify(list[0] ?? {}) })
    : route.fallback());
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await capsOn(page);
  // ALL practice attachments, or Enter lands before the send is allowed and no run starts.
  for (const id of ["attachment-left", "attachment-right", "hearing-attachment"]) await expect(page.getByTestId(id)).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();
  await page.keyboard.press("Enter");

  const picker = page.getByTestId("session-picker");
  await expect(picker).toHaveValue(PID);
  await expect.poll(() => created).toEqual([PID]);
  await expect(picker.locator(`option[value="${PID}"]`)).toHaveText(/processing$/);

  // Leave mid-processing, then come back: the run is polled again and its ear rows return.
  await picker.selectOption("new");
  await expect(page.getByTestId("ear-row-left")).toHaveCount(0);
  await picker.selectOption(PID);
  await expect(page.getByTestId("ear-row-left").getByTestId("ear-view-2")).toBeVisible({ timeout: 15_000 });
  await expect(page).toHaveURL(new RegExp(`\\?session=${PID}$`));
  await page.screenshot({ path: "test-results/sessions-resume.png" });

  // A refresh mid-processing keeps the session: same address, same run, polled again.
  await page.reload();
  await expect(picker).toHaveValue(PID);
  await expect(page.getByTestId("ear-row-left").getByTestId("ear-view-2")).toBeVisible({ timeout: 15_000 });
  expect(created).toEqual([PID]);
});

// Catches a refresh (or an opened link) losing the session: the address alone must bring back the chat line, the research view and the ID at the bottom, without sending anything to the lead as a new message.
test("a session's address reopens it after a refresh", async ({ page }) => {
  const posted: string[] = [];
  await mockAgents(page, posted);
  await page.goto("/zz-preview?session=aaaaaaaaaaaa");
  const line = page.getByTestId("orb").getByRole("status");
  await expect(line).toHaveText("Four agents are researching your aid. Ask me anything.", { timeout: 15_000 });
  await expect(page.getByTestId("session-picker")).toHaveValue("aaaaaaaaaaaa");
  await expect(page.getByTestId("session-id")).toHaveText("aaaaaaaaaaaa");
  await expect(page.getByTestId("agent-ear_fit_research").getByTestId("summary")).toHaveText("A concha lock holds while running.");
  await page.reload();
  await expect(line).toHaveText("Four agents are researching your aid. Ask me anything.", { timeout: 15_000 });
  // Only re-reads ("" is a reopen on the server, never a note).
  expect(posted.every((p) => p.endsWith(":"))).toBe(true);
  await page.waitForTimeout(3500); // orb rise, agent flight and fade
  await page.screenshot({ path: "test-results/sessions-refresh.png" });
});

// Catches an unreachable or outdated agents server looking like an empty history — the bug where saved sessions "vanished" because :8010 still ran a build without /sessions.
test("the picker says when saved sessions cannot load", async ({ page }) => {
  await page.route("**/sessions", (route) => route.fulfill({ status: 404, headers: CORS, contentType: "application/json", body: "{}" }));
  await page.goto("/zz-preview");
  await expect(page.getByTestId("session-picker").locator("option[disabled]")).toHaveText("Saved sessions unavailable: agents server is outdated, restart it");
});
