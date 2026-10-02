import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig(base, {
  testMatch: "email.spec.ts",
  testIgnore: [],
  timeout: 180_000,
  workers: 1,
  retries: 0,
  maxFailures: 1,
  outputDir: "test-results/email",
  preserveOutput: "never",
  reporter: [["./e2e/helpers/emailReporter.ts"]],
  use: { trace: "off", screenshot: "off", video: "off" },
});
