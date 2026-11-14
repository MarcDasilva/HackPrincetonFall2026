import { test, expect } from "@playwright/test";

const CORS = { "access-control-allow-origin": "*" };
const RUN = "01a1dc4b-1976-734a-b614-ac90df34531f", TRACE = "01a1dc4a-1130-7221-9b36-58c2fe56f16f";
const at = (s: number) => new Date(Date.UTC(2026, 10, 14, 12, 0, s)).toISOString();
const trace = { run_id: TRACE, project: "horn-study", tracing_enabled: true };
const EVENTS = [
  { sequence: 1, timestamp: at(1), type: "research.agent_started", component: "hearing_research", summary: "started", trace, data: {} },
  { sequence: 2, timestamp: at(2), type: "research.searched", component: "hearing_research", summary: "presbycusis horn gain (2 results)", trace,
    data: { query: "presbycusis horn gain", langsmith: { run_id: RUN, trace_id: TRACE }, notes: [],
      results: [{ title: "Passive horns for high-frequency loss", year: 2019, authors: "A. Author", venue: "JASA", url: "https://papers.example.org/1", open_access: true, snippet: "A horn adds gain above 2 kHz." },
                { title: "Ear canal resonance", year: 2001, authors: "B. Author", venue: "Hear Res", url: "https://papers.example.org/2", open_access: false, snippet: "" }] } },
  { sequence: 3, timestamp: at(3), type: "research.source_read", component: "hearing_research", summary: "Read: Passive horns", trace, data: { langsmith: { run_id: RUN, trace_id: TRACE } } },
  // An older study: no per-run ids, so the row falls back to the whole study's trace.
  { sequence: 4, timestamp: at(4), type: "research.finding_added", component: "hearing_research", summary: "Horn gain helps", trace, data: {} },
  ...Array.from({ length: 40 }, (_, i) => ({ sequence: 5 + i, timestamp: at(5 + i), type: "research.finding_added", component: "use_context_research", summary: `Finding ${i}`, trace, data: {} })),
];

// Catches trace rows that do nothing on click: a search must open what was searched (query and hits), any other row must open ITS LangSmith run (or the study's trace for older events), and the trace lists must scroll WITHOUT a visible scrollbar.
test("trace rows open the search or LangSmith, and the lists show no scrollbar", async ({ page }) => {
  await page.route("**/lead/*/events", (route) => route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ status: "running", events: EVENTS }) }));
  await page.addInitScript(() => {
    const w = window as unknown as { opened: string[] };
    w.opened = [];
    window.open = ((u: string) => { w.opened.push(String(u)); return null; }) as typeof window.open;
  });
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await page.locator("body").click({ position: { x: 5, y: 400 } });
  await page.keyboard.press("5");
  const box = page.getByTestId("agent-hearing_research");
  await expect(box).toHaveCSS("opacity", "1", { timeout: 10_000 });
  const rows = box.getByTestId("trace-row");
  await expect(rows).toHaveCount(4);

  await rows.nth(1).click();                                  // search_literature
  const modal = page.getByTestId("search-modal");
  await expect(modal).toContainText("presbycusis horn gain");
  await expect(modal.getByTestId("search-hit")).toHaveCount(2);
  await expect(modal.getByRole("link", { name: "Passive horns for high-frequency loss" })).toHaveAttribute("href", "https://papers.example.org/1");
  await page.screenshot({ path: "test-results/trace-search-modal.png" });
  await page.keyboard.press("Escape");
  await expect(modal).toHaveCount(0);

  await rows.nth(2).click();                                  // read_source: its own run
  await rows.nth(3).click();                                  // older event: the study's trace
  const opened = await page.evaluate(() => (window as unknown as { opened: string[] }).opened);
  expect(opened).toEqual([expect.stringMatching(new RegExp(`/langsmith/${RUN}\\?trace_id=${TRACE}$`)), expect.stringMatching(new RegExp(`/langsmith/${TRACE}$`))]);

  // The long list still scrolls, but draws no scrollbar.
  const list = page.getByTestId("agent-use_context_research").getByTestId("traces");
  const [sw, client, offset, scrollH, clientH] = await list.evaluate((el: HTMLElement) => [getComputedStyle(el).scrollbarWidth, el.clientWidth, el.offsetWidth, el.scrollHeight, el.clientHeight] as const);
  expect(sw).toBe("none");
  expect(scrollH).toBeGreaterThan(clientH);
  expect(offset - client).toBeLessThanOrEqual(2);            // only the 1px borders, no scrollbar gutter
  await page.screenshot({ path: "test-results/trace-boxes.png" });
});

// Catches an older study's search showing nothing: its event has no saved hits, so the modal must fetch them (from the search's LangSmith run, via the agents server) and say so plainly when they cannot be found.
test("an older study's search fetches what it found", async ({ page }) => {
  const old = [
    { sequence: 1, timestamp: at(1), type: "research.agent_started", component: "hearing_research", summary: "started", trace, data: {} },
    { sequence: 2, timestamp: at(2), type: "research.searched", component: "hearing_research", summary: "speech audibility band importance (6 results)", trace, data: {} },
    { sequence: 3, timestamp: at(3), type: "research.searched", component: "hearing_research", summary: "nothing logged (0 results)", trace, data: {} },
  ];
  const asked: string[] = [];
  await page.route("**/lead/*/events", (route) => route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ status: "done", events: old }) }));
  await page.route("**/langsmith/search?*", (route) => {
    const u = new URL(route.request().url());
    asked.push(`${u.searchParams.get("trace_id")}|${u.searchParams.get("query")}`);
    return u.searchParams.get("query") === "speech audibility band importance"
      ? route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify({ query: "speech audibility band importance function mild sloping loss", notes: [], langsmith: { run_id: RUN, trace_id: TRACE },
          results: [{ title: "Variations in the Slope of the Psychometric Functions", year: "2014", authors: "A. MacPherson", venue: "Trends in Hearing", url: "https://doi.org/10.1177/x", open_access: true, snippet: "Slope matters." }] }) })
      : route.fulfill({ status: 404, headers: CORS, body: "{}" });
  });
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  await page.locator("body").click({ position: { x: 5, y: 400 } });
  await page.keyboard.press("5");
  const rows = page.getByTestId("agent-hearing_research").getByTestId("trace-row");
  await expect(rows).toHaveCount(3, { timeout: 10_000 });
  await expect(page.getByTestId("agent-hearing_research")).toHaveCSS("opacity", "1", { timeout: 10_000 });

  await rows.nth(1).click();
  const modal = page.getByTestId("search-modal");
  await expect(modal.getByTestId("search-hit")).toHaveCount(1);
  await expect(modal).toContainText("speech audibility band importance function mild sloping loss");   // the FULL query, not the summary
  await expect(modal.getByRole("link", { name: "Open in LangSmith" })).toHaveAttribute("href", new RegExp(`/langsmith/${RUN}\\?trace_id=${TRACE}$`));
  // ONE distinct lookup: the summary with its "(6 results)" tail cut off, against the study's trace (dev StrictMode may send it twice).
  expect([...new Set(asked)]).toEqual([`${TRACE}|speech audibility band importance`]);
  await page.screenshot({ path: "test-results/trace-search-recovered.png" });
  await page.keyboard.press("Escape");

  await rows.nth(2).click();
  await expect(modal.getByTestId("search-empty")).toHaveText("The results of this search could not be found in LangSmith.");
});
