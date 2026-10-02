import { test, expect, type Page } from "@playwright/test";
import { inflateSync, gunzipSync } from "node:zlib";

const secret = "canary-browser-password-otp-pkce-jwt-cookie-csrf-totp-recovery-webauthn-aws-smtp-email-phone"; // pragma: allowlist secret -- synthetic canary
type Item = { type: string; value: unknown };

function parseEnvelope(body: Buffer): Item[] {
  let cursor = body.indexOf(10) + 1;
  const items: Item[] = [];
  while (cursor > 0 && cursor < body.length) {
    const end = body.indexOf(10, cursor);
    if (end < 0) break;
    const header = JSON.parse(body.subarray(cursor, end).toString()) as { type: string; length?: number };
    cursor = end + 1;
    const payloadEnd = header.length ? cursor + header.length : body.indexOf(10, cursor);
    const payload = body.subarray(cursor, payloadEnd < 0 ? body.length : payloadEnd);
    cursor = (payloadEnd < 0 ? body.length : payloadEnd) + 1;
    if (header.type === "replay_recording") {
      const recordingStart = payload.indexOf(10) + 1; // per-recording JSON header
      const compressed = payload.subarray(recordingStart);
      let value: string;
      try { value = inflateSync(compressed).toString(); }
      catch { value = gunzipSync(compressed).toString(); }
      items.push({ type: header.type, value: JSON.parse(value) });
    } else items.push({ type: header.type, value: JSON.parse(payload.toString()) });
  }
  return items;
}

async function capture(page: Page) {
  const items: Item[] = [];
  const requests: string[] = [];
  page.on("request", request => requests.push(request.url()));
  await page.route("https://o1.ingest.de.sentry.io/**", async route => {
    const body = route.request().postDataBuffer();
    if (body) items.push(...parseEnvelope(body));
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}", headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.route("https://external.invalid/**", route => route.fulfill({ status: 200, body: "{}", headers: { "Access-Control-Allow-Origin": "*" } }));
  return { items, requests };
}

test("production: real SDK error/trace; recorder/worker hard off despite rates=1", async ({ page }) => {
  const { items, requests } = await capture(page);
  const outgoing: Record<string, string>[] = [];
  const external: Record<string, string>[] = [];
  await page.route("https://external.invalid/**", async route => {
    external.push(route.request().headers());
    await route.fulfill({ status: 200, body: "{}", headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.route("http://localhost:5187/api/telemetry-propagation**", async route => {
    outgoing.push(route.request().headers());
    await route.fulfill({ status: 200, body: "{}" });
  });
  await page.goto("/telemetry-harness.html?environment=production");
  await page.locator("#error").click();
  await page.evaluate(() => window.dispatchEvent(new Event("sdk-test")));
  await page.locator("#flush").click();
  await expect.poll(() => items.filter(item => item.type === "event").length).toBe(1);
  await expect.poll(() => items.filter(item => item.type === "transaction").length).toBeGreaterThan(0);
  await expect.poll(() => outgoing.length).toBeGreaterThan(0);
  expect(outgoing[0]["sentry-trace"]).toBeTruthy();
  await expect.poll(() => external.length).toBeGreaterThan(0);
  expect(external.every(headers => !headers["sentry-trace"] && !headers.baggage)).toBe(true);
  expect(JSON.stringify(items)).not.toContain(secret);
  expect(items.some(item => item.type.startsWith("replay"))).toBe(false);
  expect(requests.some(url => /replay\.ts|sentry-replay-worker/.test(url))).toBe(false);
});

test("global unhandled rejection is captured once with sanitized values", async ({ page }) => {
  const { items } = await capture(page);
  await page.goto("/telemetry-harness.html?environment=production");
  await page.locator("#rejection").click();
  await page.locator("#flush").click();
  await expect.poll(() => items.filter(item => item.type === "event").length).toBe(1);
  expect(JSON.stringify(items)).not.toContain(secret);
});

test("staging: real compressed rrweb recording and metadata contain no secret", async ({ page }) => {
  const { items, requests } = await capture(page);
  await page.goto("/telemetry-harness.html?environment=staging");
  await expect.poll(() => requests.some(url => url.includes("sentry-replay-worker"))).toBe(true);
  await page.locator("#error").click();
  // SDK enforces the minimum recording duration; this isn't an auth retry.
  await page.waitForTimeout(5500);
  await page.locator("#flush").click();
  await expect.poll(() => items.some(item => item.type === "replay_recording"), { timeout: 10000 }).toBe(true);
  const recordings = items.filter(item => item.type === "replay_recording");
  expect(Array.isArray(recordings[0].value)).toBe(true);
  expect(items.some(item => item.type === "replay_event")).toBe(true);
  expect(JSON.stringify(items)).not.toContain(secret);
});

test("sensitive initial URL disables rrweb, even before a React effect", async ({ page }) => {
  const { items, requests } = await capture(page);
  await page.goto(`/telemetry-harness.html?environment=staging&token=${secret}`);
  await page.locator("#error").click();
  await page.locator("#flush").click();
  await expect.poll(() => items.filter(item => item.type === "event").length).toBe(1);
  expect(JSON.stringify(items)).not.toContain(secret);
  expect(requests.some(url => url.includes("sentry-replay-worker"))).toBe(false);
  expect(items.some(item => item.type.startsWith("replay"))).toBe(false);
});

test("blocked ingestion leaves the UI usable", async ({ page }) => {
  await page.route("https://o1.ingest.de.sentry.io/**", route => route.abort("failed"));
  await page.goto("/telemetry-harness.html?environment=production");
  await page.locator("#error").click();
  await page.locator("#flush").click();
  await expect(page.getByText("Safe synthetic shell")).toBeVisible();
});

test("missing Worker cannot send the SDK's unsanitized fallback recording", async ({ page }) => {
  const { items } = await capture(page);
  await page.addInitScript(() => { Object.defineProperty(window, "Worker", { value: undefined }); });
  await page.goto("/telemetry-harness.html?environment=staging");
  await page.locator("#error").click();
  await page.waitForTimeout(5500);
  await page.locator("#flush").click();
  await expect.poll(() => items.some(item => item.type === "event")).toBe(true);
  expect(items.some(item => item.type.startsWith("replay"))).toBe(false);
  expect(JSON.stringify(items)).not.toContain(secret);
});
