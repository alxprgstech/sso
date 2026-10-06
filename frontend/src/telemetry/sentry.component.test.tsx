import React from "react";
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { savePrivacyChoice } from "./consent";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { ErrorBoundary as AppErrorBoundary } from "../components/ErrorBoundary";
import { ErrorBoundary, getClient, init, captureException, flush } from "@sentry/react";
import { parseConfig, propagationTargets, bootstrapTelemetry, isExpectedClientFailure, initializeTelemetry } from "./sentry";
import { ApiError, api } from "../api/client";
import { sanitizeEvent } from "./privacy";

beforeEach(() => { savePrivacyChoice(true, false); });
afterEach(async () => { cleanup(); await getClient()?.close(0); savePrivacyChoice(false, false); vi.restoreAllMocks(); });
describe("telemetry bootstrap and real SDK ErrorBoundary", () => {
  it("does not initialize after consent is revoked during the SDK import", async () => {
    const pending = initializeTelemetry({ enabled: true, dsn: "https://public@o1.ingest.de.sentry.io/1", environment: "production",
      traces_sample_rate: 0, replay_enabled: false, replays_session_sample_rate: 0,
      replays_on_error_sample_rate: 0, trace_propagation_targets: [] });
    savePrivacyChoice(false, false);
    expect(await pending).toBe(false);
    expect(getClient()?.getOptions().enabled).not.toBe(true);
  });
  it("shows the local fallback and captures a sanitized event through the lazy SDK", async () => {
    const envelopes: unknown[] = [];
    init({ dsn: "https://public@o1.ingest.de.sentry.io/1", defaultIntegrations: false,
      beforeSend: event => sanitizeEvent(event),
      transport: () => ({ send: envelope => { envelopes.push(envelope); return Promise.resolve({}); }, flush: () => Promise.resolve(true) }),
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    function Broken(): React.ReactNode { throw new Error("canary-password-never-export"); }
    render(<AppErrorBoundary fallback={<p>Локальное восстановление</p>}><Broken /></AppErrorBoundary>);
    expect(screen.getByText("Локальное восстановление")).toBeTruthy();
    await waitFor(() => expect(envelopes).toHaveLength(1));
    expect(JSON.stringify(envelopes)).not.toContain("canary-password-never-export");
  });
  it("fails open within deadline when config fetch never resolves", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    const started = performance.now();
    expect(await bootstrapTelemetry()).toBe(false);
    expect(performance.now() - started).toBeLessThan(1000);
  });
  it("rejects malformed rates and ingestion destinations", () => {
    expect(parseConfig({ enabled: true, dsn: "https://untrusted.invalid/1" })).toBeNull();
    expect(parseConfig({ enabled: false })).toBeNull();
  });
  it("matches only the exact origin and API/OAuth paths", () => {
    const targets = propagationTargets("https://auth.alxprgs.tech");
    const matches = (url: string) => targets.some(pattern => pattern.test(url));
    expect(matches("https://auth.alxprgs.tech/api/v1/auth/login")).toBe(true);
    expect(matches("https://auth.alxprgs.tech.evil.invalid/api/login")).toBe(false);
    expect(matches("https://demo.alxprgs.tech/api/login")).toBe(false);
    expect(matches("//evil.invalid/api/login")).toBe(false);
    expect(matches("/verify-email?token=canary")).toBe(false);
  });
  it("classifies API responses, native WebAuthn cancellation and offline failures", () => {
    for (const status of [400, 401, 403, 404, 409, 429, 500, 503]) {
      expect(isExpectedClientFailure(new ApiError("Ошибка", status, "request_rejected", "/api/v1/auth/login"))).toBe(true);
    }
    expect(isExpectedClientFailure(new DOMException("User cancelled", "NotAllowedError"))).toBe(true);
    expect(isExpectedClientFailure(new TypeError("Failed to fetch"))).toBe(true);
    expect(isExpectedClientFailure(new TypeError("Unexpected contract"))).toBe(false);
  });
  it("captures one real boundary event with safe exception values", async () => {
    const envelopes: unknown[] = [];
    init({ dsn: "https://public@o1.ingest.de.sentry.io/1", defaultIntegrations: false,
      beforeSend: event => sanitizeEvent(event),
      transport: () => ({ send: envelope => { envelopes.push(envelope); return Promise.resolve({}); }, flush: () => Promise.resolve(true) }),
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    function Broken(): React.ReactNode { throw new Error("canary-password-never-export"); }
    render(<ErrorBoundary fallback={<p>Не удалось отобразить страницу.</p>} showDialog={false}><Broken /></ErrorBoundary>);
    expect(screen.getByText("Не удалось отобразить страницу.")).toBeTruthy();
    await flush(500);
    expect(envelopes).toHaveLength(1);
    expect(JSON.stringify(envelopes)).not.toContain("canary-password-never-export");
    // A second handled capture remains a normal SDK event, independent of UI recovery.
    captureException(new TypeError("canary-otp-never-export"));
    await flush(500);
    expect(envelopes).toHaveLength(2);
    expect(JSON.stringify(envelopes)).not.toContain("canary-otp-never-export");
  });
  it("captures an invalid successful API contract once, while expected HTTP failures stay local", async () => {
    const envelopes: unknown[] = [];
    init({ dsn: "https://public@o1.ingest.de.sentry.io/1", defaultIntegrations: false,
      beforeSend: (event, hint) => isExpectedClientFailure(hint.originalException) ? null : sanitizeEvent(event),
      transport: () => ({ send: envelope => { envelopes.push(envelope); return Promise.resolve({}); }, flush: () => Promise.resolve(true) }),
    });
    const fetch = vi.spyOn(globalThis, "fetch");
    for (const status of [400, 401, 403, 409, 429, 500, 503]) {
      fetch.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Ошибка запроса" }), { status }));
      await expect(api.getCapabilities()).rejects.toMatchObject({ name: "ApiError", status });
    }
    expect(envelopes).toHaveLength(0);
    fetch.mockResolvedValueOnce(new Response("not JSON", { status: 200 }));
    await expect(api.getCapabilities()).rejects.toMatchObject({ name: "ApiError", code: "invalid_response" });
    await waitFor(() => expect(envelopes).toHaveLength(1));
  });
});
