import { test, expect } from "@playwright/test";
import { mockStudy } from "./mockBackend";

// Catches the research preview losing a corner box, the study's events not reaching each agent's box, or the lead's center line going missing.
test("research preview: four agent boxes show their study events around the lead", async ({ page }) => {
  await mockStudy(page);
  await page.goto("/zz-preview/research");
  for (const key of ["hearing_research", "use_context_research", "acoustic_design_research", "ear_fit_research"]) {
    const box = page.getByTestId(`agent-${key}`);
    await expect(box).toBeVisible();
    await expect(box.getByTestId("traces").locator("> div")).not.toHaveCount(0);
    await expect(box.getByTestId("summary")).not.toBeEmpty();
  }
  await expect(page.getByTestId("lead").getByRole("status")).toHaveText("Four agents are researching your aid. Ask me anything.");
  // Events land in their OWN agent's box, and a finished agent's footer is its own summary.
  await expect(page.getByTestId("agent-hearing_research").getByTestId("traces")).toContainText("Finding from hearing_research");
  await expect(page.getByTestId("agent-hearing_research").getByTestId("traces")).not.toContainText("ear_fit_research");
  // submit_finding posts show as their own row, and the latest post is the working agent's footer.
  await expect(page.getByTestId("agent-hearing_research").getByTestId("traces")).toContainText("submit_finding");
  await expect(page.getByTestId("agent-hearing_research").getByTestId("summary")).toHaveText("Board post from hearing_research");
  await expect(page.getByTestId("agent-ear_fit_research").getByTestId("summary")).toHaveText("A concha lock holds while running.");
  await page.waitForTimeout(3000); // flight + fade
  await page.screenshot({ path: "test-results/research-preview.png" });
});
