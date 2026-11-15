import { test, expect } from "@playwright/test";

// The picker is display only: catches it losing an option, or a pick leaking into the composer's request.
test("the chat's model picker offers three models and changing it sends nothing", async ({ page }) => {
  await page.goto("/zz-preview");
  await page.waitForFunction(() => {
    const w = document.querySelector("textarea")?.closest("div[style*='fixed']");
    return !!w && getComputedStyle(w).opacity === "1";
  });
  const picker = page.getByTestId("model-picker");
  await expect(picker.locator("option")).toHaveText(["Fable 5.2", "Opus 5.5", "Haiku 5.5"]);
  await expect(picker).toHaveValue("Opus 5.5");
  const requests: string[] = [];
  page.on("request", (r) => requests.push(r.url()));
  await picker.selectOption("Haiku 5.5");
  await expect(picker).toHaveValue("Haiku 5.5");
  await page.waitForTimeout(300);
  expect(requests).toEqual([]);
  await page.screenshot({ path: "test-results/model-picker.png" });
});
