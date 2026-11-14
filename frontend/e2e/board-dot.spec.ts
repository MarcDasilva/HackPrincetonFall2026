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

  // Every frame, where the dot is AND whether the orb canvas itself draws a node right under it (the overlay dot is not in
  // the canvas, so a bright opaque pixel there is the orb's own dot): its whole path, without racing a 1.5 s animation.
  type Frame = { x: number; y: number; node: boolean };
  await page.evaluate(() => {
    const w = window as unknown as { path: Frame[] };
    w.path = [];
    const canvas = document.querySelector<HTMLCanvasElement>("[data-testid=lead] canvas")!, g = canvas.getContext("2d")!;
    const tick = () => {
      const d = document.querySelector("[data-testid=board-dot]");
      if (d) {
        const b = d.getBoundingClientRect(), c = canvas.getBoundingClientRect(), k = canvas.width / c.width;
        const x = b.left + b.width / 2, y = b.top + b.height / 2;
        const px = g.getImageData(Math.round((x - c.left) * k) - 3, Math.round((y - c.top) * k) - 3, 7, 7).data;
        // Front nodes are drawn opaque and light (Orb ink >= ~170 grey); lines top out near 148 grey and partly transparent.
        let node = false;
        for (let i = 0; i < px.length; i += 4) if (px[i + 3] > 230 && px[i] > 165) node = true;
        w.path.push({ x, y, node });
      }
      requestAnimationFrame(tick);
    };
    tick();
  });
  await expect(dot).toHaveCount(1, { timeout: 5000 });
  // It targets one of the center orb's own dots, not the orb's middle.
  expect(Number(await dot.getAttribute("data-node"))).toBeGreaterThanOrEqual(0);
  await page.waitForTimeout(500);
  await page.screenshot({ path: "test-results/board-dot.png" });
  await page.waitForTimeout(550); // just before the 1.1 s flight lands
  await page.screenshot({ path: "test-results/board-dot-landing.png" });
  await expect(dot).toHaveCount(0, { timeout: 3000 });
  const path = await page.evaluate(() => (window as unknown as { path: Frame[] }).path);
  const flyer = (await page.getByTestId("flyer-use_context_research").boundingBox())!;
  const lead = (await page.getByTestId("lead").locator("canvas").boundingBox())!;
  const center = { x: lead.x + lead.width / 2, y: lead.y + lead.height / 2 };
  const near = (p: { x: number; y: number }, q: { x: number; y: number }) => Math.hypot(p.x - q.x, p.y - q.y);
  // Leaves from the agent's orb...
  expect(near(path[0], { x: flyer.x + flyer.width / 2, y: flyer.y + flyer.height / 2 })).toBeLessThan(12);
  // ...and lands ON the sphere (80% of the canvas), riding its node to the end.
  expect(near(path.at(-1)!, center)).toBeLessThan(lead.width * 0.4 + 4);
  // ...exactly on one of the orb's drawn dots for the landing frames (the last 0.35 s rides the node).
  const landing = path.slice(-10);
  expect(landing.filter((f) => f.node).length).toBeGreaterThanOrEqual(8);
  // Later polls (same post) fire nothing new.
  await page.waitForTimeout(2000);
  await expect(dot).toHaveCount(0);
});
