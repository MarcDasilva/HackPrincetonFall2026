import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  workers: 2,
  use: {
    baseURL: "http://localhost:3100",
    launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] },
    permissions: ["camera"],
  },
  webServer: { command: "npx next dev -p 3100", url: "http://localhost:3100", reuseExistingServer: false, timeout: 180_000 },
});
