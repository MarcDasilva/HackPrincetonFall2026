import { test, expect } from "@playwright/test";

const CORS = { "access-control-allow-origin": "*" };
const at = (s: number) => new Date(Date.UTC(2026, 10, 14, 12, 0, s)).toISOString();
const ev = (sequence: number, component: string, type: string, summary: string) => ({ sequence, timestamp: at(sequence), type, component, summary, data: {} });

// Catches a submit_finding post not reaching the center orb on screen: each NEW post sends one white dot from its agent's orb onto one of the center orb's own dots, while posts already on the board when the view opens (a reopened session's history) send none.
test("a new info-board post flies a dot from its agent's orb onto a dot of the center orb", async ({ page }) => {
  const base = [ev(1, "hearing_research", "research.agent_started", "start"), ev(2, "hearing_research", "research.board_posted", "Old post")];
  // The new post appears 2.5 s after the first poll — by time, NOT poll count: dev React mounts twice, so the first two polls land together.
  let polls = 0, first = 0;
  await page.route("**/lead/*/events", (route) => {
    polls++;
    first ||= Date.now();
    const events = Date.now() - first < 2500 ? base : [...base, ev(3, "use_context_research", "research.board_posted", "New post")];
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ status: "running", events }) });
  });
  await page.goto("/zz-preview/research");
  const dot = page.getByTestId("board-dot");
  await expect.poll(() => polls).toBeGreaterThan(0);
  // The backlog post fired nothing.
  await expect(dot).toHaveCount(0);

  await expect(dot).toHaveCount(1, { timeout: 5000 });
  // It targets one of the center orb's own dots, not the orb's middle.
  expect(Number(await dot.getAttribute("data-node"))).toBeGreaterThanOrEqual(0);
  const flyer = (await page.getByTestId("flyer-use_context_research").boundingBox())!;
  const lead = (await page.getByTestId("lead").locator("canvas").boundingBox())!;
  const center = { x: lead.x + lead.width / 2, y: lead.y + lead.height / 2 };
  const pos = async () => {
    const b = await dot.boundingBox();
    return b && { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  };
  const start = Math.hypot(flyer.x + flyer.width / 2 - center.x, flyer.y + flyer.height / 2 - center.y);
  await page.waitForTimeout(500);
  const mid = (await pos())!;
  expect(Math.hypot(mid.x - center.x, mid.y - center.y)).toBeLessThan(start - 40);
  await page.screenshot({ path: "test-results/board-dot.png" });
  // Landing (1.1 s flight): ON the sphere, which fills 80% of the canvas.
  await page.waitForTimeout(700);
  const end = (await pos())!;
  expect(Math.hypot(end.x - center.x, end.y - center.y)).toBeLessThan(lead.width * 0.4 + 4);
  await page.screenshot({ path: "test-results/board-dot-landed.png" });
  // Removed after landing; later polls (same post) fire nothing new.
  await expect(dot).toHaveCount(0, { timeout: 3000 });
  await page.waitForTimeout(2000);
  await expect(dot).toHaveCount(0);
});
