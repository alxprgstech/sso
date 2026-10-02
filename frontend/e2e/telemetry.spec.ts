import { test, expect } from "@playwright/test";

// Runs against the real SSO server in both existing default-off/enabled MFA
// campaigns. Capabilities and crypto are never replaced by routes or mocks.
test("ordinary SSO campaigns expose disabled telemetry and block sensitive views", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", request => requests.push(request.url()));
  await page.goto("/");
  const response = await page.request.get("/api/v1/auth/telemetry-config");
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect(await response.json()).toMatchObject({
    enabled: false, dsn: "", traces_sample_rate: 0,
    replay_enabled: false, replays_session_sample_rate: 0,
    replays_on_error_sample_rate: 0, trace_propagation_targets: [],
  });
  await expect(page.locator("#root [data-sentry-block]")).toBeVisible();
  expect(requests.some(url => /\.ingest(?:\.[a-z]+)?\.sentry\.io|sentry-replay-worker/.test(url))).toBe(false);
});
