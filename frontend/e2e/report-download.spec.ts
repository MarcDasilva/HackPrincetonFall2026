import { test, expect } from "@playwright/test";
import fs from "node:fs";

// Catches the end of the flow falling back to a text pop-up: saying yes to the report must download a full PDF report
// (figures, renders, research, the written report) and the print STL, with no pop-up, ONCE per session. Runs on a real
// patient's files through the real backend and agents server; only the lead's replies are mocked.
const RUN = process.env.AID_RUN ?? "14603cd9da42";
const SESSION = `../agents/studies/sessions/${RUN}.json`;
const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "*" };
const REPORT = "SUMMARY\nThe simulations measured speech audibility for the left ear across ten everyday scenes. Without a device the patient hears 50% of speech on average against 70% with normal hearing. The simulations measured speech audibility for the left ear across ten everyday scenes. Without a device the patient hears 50% of speech on average against 70% with normal hearing. The simulations measured speech audibility for the left ear across ten everyday scenes. Without a device the patient hears 50% of speech on average against 70% with normal hearing.\n\nYOUR HEARING TEST\nThe left ear shows a mild loss rising to 40 dB HL at 4 and 6 kHz. The right ear is similar above 1 kHz. The left ear shows a mild loss rising to 40 dB HL at 4 and 6 kHz. The right ear is similar above 1 kHz. The left ear shows a mild loss rising to 40 dB HL at 4 and 6 kHz. The right ear is similar above 1 kHz.\n\nWHAT YOU TOLD US\nThe patient reported difficulty following conversation at family gatherings. The patient reported difficulty following conversation at family gatherings. The patient reported difficulty following conversation at family gatherings.\n\nWHAT THE RESEARCH FOUND\nFour research agents reviewed horn acoustics, occlusion and speech-in-noise evidence. Four research agents reviewed horn acoustics, occlusion and speech-in-noise evidence. Four research agents reviewed horn acoustics, occlusion and speech-in-noise evidence.\n\nTHE LISTENING SIMULATIONS\nEach scene was simulated on a model of the patient's own head and ears. Quiet speech was hardest. Each scene was simulated on a model of the patient's own head and ears. Quiet speech was hardest. Each scene was simulated on a model of the patient's own head and ears. Quiet speech was hardest.\n\nTHE FOUR DESIGNS\nThe four options differ mainly in mouth size and collector length. The four options differ mainly in mouth size and collector length. The four options differ mainly in mouth size and collector length.\n\nTHE DESIGN YOU PICKED\nOption 1, a long cone collector, gives the most gain between 1.6 and 2.5 kHz. Option 1, a long cone collector, gives the most gain between 1.6 and 2.5 kHz. Option 1, a long cone collector, gives the most gain between 1.6 and 2.5 kHz.\n\nHOW MUCH IT HELPS\nThe validation shows small changes of plus or minus four points per scene. The validation shows small changes of plus or minus four points per scene. The validation shows small changes of plus or minus four points per scene.\n\nLIMITS OF THIS STUDY\nThese are simulations, not clinical measurements. These are simulations, not clinical measurements. These are simulations, not clinical measurements.\n\nNEXT STEPS\n- Print the STL file.\n- Wear it for a week in quiet conversation.\n- See an audiologist for a clinical assessment.";

test("yes to the report downloads the PDF report and the STL, no pop-up", async ({ page, request }) => {
  test.setTimeout(240_000);
  const ok = fs.existsSync(SESSION) && await request.get(`${BACKEND}/api/patients/${RUN}/files/head/head.json`).then((r) => r.ok(), () => false);
  test.skip(!ok, `needs session ${RUN} and its patient on the backend at ${BACKEND}`);
  const saved = JSON.parse(fs.readFileSync(SESSION, "utf8"));
  test.skip(!saved.picked || !saved.validation, "the session has not been validated yet");
  const s = { ...saved, run_id: RUN, stage: "final", reply: "Want your final report and the file to print?", status: "completed", launch_requested: true, report: null, updated_at: 1 };
  await page.route(`**/lead/${RUN}`, async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers: CORS });
    if (route.request().method() === "POST" && route.request().postDataJSON().message === "yes")
      Object.assign(s, { stage: "done", reply: "Your report and the file to print are downloading now. 😊", report: REPORT });
    return route.fulfill({ contentType: "application/json", headers: CORS, body: JSON.stringify(s) });
  });
  await page.route("**/sessions", (route) => route.fulfill({ contentType: "application/json", headers: CORS, body: "[]" }));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/zz-preview?session=${RUN}`);
  await page.evaluate((id) => localStorage.removeItem(`auris-report:${id}`), RUN);
  const line = page.getByTestId("orb").getByRole("status");
  await expect(line).toHaveText(/final report/, { timeout: 20_000 });

  const downloads: { name: string; path: string }[] = [];
  page.on("download", async (d) => downloads.push({ name: d.suggestedFilename(), path: await d.path() }));
  await page.locator("textarea").fill("yes");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(line).toHaveText(/downloading now\. 😊/);
  await expect.poll(() => downloads.length, { timeout: 120_000 }).toBe(2);
  expect(downloads.map((d) => d.name).sort()).toEqual([expect.stringMatching(/^Auris earpiece .*\.stl$/), expect.stringMatching(/^Auris report .*\.pdf$/)].sort());
  await expect(page.getByTestId("final-report")).toHaveCount(0);

  const pdf = downloads.find((d) => d.name.endsWith(".pdf"))!;
  const bytes = fs.readFileSync(pdf.path);
  expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");
  expect(bytes.length).toBeGreaterThan(200_000);                    // figures and renders, not a page of text
  fs.copyFileSync(pdf.path, test.info().outputPath("report.pdf"));
  const stl = downloads.find((d) => d.name.endsWith(".stl"))!;
  expect(fs.statSync(stl.path).size).toBeGreaterThan(10_000);
  await page.screenshot({ path: test.info().outputPath("done.png") });

  // a reload of the finished session does NOT download them again
  const before = downloads.length;
  await page.reload();
  await expect(line).toHaveText(/downloading now/, { timeout: 20_000 });
  await page.waitForTimeout(4000);
  expect(downloads.length).toBe(before);
});
