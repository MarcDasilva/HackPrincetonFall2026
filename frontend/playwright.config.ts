import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  use: {
    baseURL: "http://localhost:3000",
    // Fake webcam: headless Chromium has no camera, so getUserMedia would fail without these flags.
    launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] },
    permissions: ["camera"],
  },
  webServer: { command: "npm run dev", url: "http://localhost:3000", reuseExistingServer: true, timeout: 120_000 },
});
