// Synthetic SDK integration harness. This entry is never in the production build.
import { createRoot } from "react-dom/client";
import * as Sentry from "@sentry/react";
import { initializeTelemetry, watchTelemetryConsent } from "../../src/telemetry/sentry";

import { savePrivacyChoice } from "../../src/telemetry/consent";
const consentMode = new URLSearchParams(location.search).get("consent");
if (consentMode !== "none") savePrivacyChoice(true, consentMode !== "diagnostics"); // Explicit synthetic permission.

const environment = new URLSearchParams(location.search).get("environment") === "staging" ? "staging" : "production";
const parameters = new URLSearchParams(location.search);
parameters.delete("consent");
parameters.delete("environment"); // Test control, never a user/auth parameter.
history.replaceState(null, "", location.pathname + (parameters.size ? "?" + parameters.toString() : ""));
initializeTelemetry({ enabled: true, dsn: "https://public@o1.ingest.de.sentry.io/1", environment,
  traces_sample_rate: 1, replay_enabled: true, replays_session_sample_rate: 1,
  replays_on_error_sample_rate: 1, trace_propagation_targets: [],
});
const secret = "canary-browser-password-otp-pkce-jwt-cookie-csrf-totp-recovery-webauthn-aws-smtp-email-phone"; // pragma: allowlist secret -- synthetic canary
createRoot(document.getElementById("root")!).render(
  <Sentry.ErrorBoundary fallback={<p>Ошибка интерфейса</p>}>
    <p>Safe synthetic shell</p>
    <div data-sentry-block><input aria-label="Password" value={secret} readOnly /><div title={secret} data-secret={secret}>{secret}<svg><text>{secret}</text></svg></div></div>
    <button id="error" onClick={() => { Sentry.captureException(new Error(secret)); }}>Controlled error</button>
    <button id="rejection" onClick={() => { void Promise.reject(new Error(secret)); }}>Controlled rejection</button>
    <button id="flush" onClick={() => { void Sentry.getReplay()?.flush(); void Sentry.flush(1000); }}>Flush SDK</button>
  </Sentry.ErrorBoundary>
);
window.addEventListener("sdk-test", () => {
  Sentry.startSpan({ name: "/login", op: "navigation", forceTransaction: true, parentSpan: null }, () => {
    void fetch("/api/telemetry-propagation?secret=" + secret).catch(() => {});
    void fetch("https://external.invalid/api/telemetry-propagation?secret=" + secret).catch(() => {});
  });
});

window.addEventListener("privacy-revoke", () => { savePrivacyChoice(false, false); watchTelemetryConsent(); });
