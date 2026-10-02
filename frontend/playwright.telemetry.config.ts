import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e/telemetry", testMatch: "*.spec.ts", fullyParallel: false,
  forbidOnly: !!process.env.CI, retries: 0, workers: 1, timeout: 30000,
  reporter: "line",
  use: { baseURL: "http://localhost:5187", headless: true, trace: "off" },
  webServer: { command: "npm run dev -- --host 127.0.0.1 --port 5187 --strictPort", url: "http://localhost:5187/telemetry-harness.html", reuseExistingServer: false },
});
