import * as Sentry from "@sentry/react";
import { sanitizeBreadcrumb, sanitizeEvent, sanitizeReplayMetadata, canonicalRoute } from "./privacy";
import type { TelemetryConfig } from "../types/api";
import { permitsDiagnostics, permitsReplay } from "./consent";
import { parseConfig, propagationTargets, isExpectedClientFailure } from "./config";

// Also used by the isolated SDK browser harness; no SSO capabilities are replaced.
export function initializeTelemetry(config: TelemetryConfig): boolean {
  try {
    if (!parseConfig(config)?.enabled || !permitsDiagnostics()) return false;
    // rrweb Meta events bypass the public recording hook. Don't start a recorder
    // on any initial query/fragment URL, including verification/return_to links.
    const replayAllowed = permitsReplay() && config.environment === "staging" && config.replay_enabled && !location.search && !location.hash;
    Sentry.init({
      dsn: config.dsn, environment: config.environment, release: __BUILD_IDENTITY__.release,
      traceLifecycle: "static", sendClientReports: false,
      profileSessionSampleRate: 0, profileLifecycle: "manual",
      transport: options => {
        const transport = Sentry.makeFetchTransport(options);
        const pending = new Set<Promise<unknown>>();
        return {
          send(envelope) {
            if (!permitsDiagnostics()) return Promise.resolve({});
            const delivery = (async () => {
              const replay = envelope[1].some(item => item[0].type.startsWith("replay"));
              if (replay && (!replayAllowed || !permitsReplay() || !await import("./replay-envelope").then(module => module.recordingWasSanitized(envelope)))) return {};
              // Block all channels which are outside the v1 capture policy.
              const items = envelope[1].filter(item => ["event", "transaction", "replay_event", "replay_recording"].includes(item[0].type));
              if (!items.length) return {};
              if (!permitsDiagnostics() || (replay && !permitsReplay())) return {};
              // Dynamic sampling envelope metadata is independent of event hooks.
              const { event_id, sent_at } = envelope[0];
              return transport.send([{ event_id, sent_at, sdk: { name: "sentry.javascript.react", version: Sentry.SDK_VERSION } }, items] as typeof envelope);
            })();
            pending.add(delivery);
            void delivery.finally(() => pending.delete(delivery)).catch(() => {});
            return delivery;
          },
          async flush(timeout) {
            let timer: ReturnType<typeof setTimeout> | undefined;
            try {
              const drained = await Promise.race([
                Promise.allSettled([...pending]).then(() => true),
                new Promise<boolean>(resolve => { timer = setTimeout(() => resolve(false), timeout ?? 2000); }),
              ]);
              return drained && await transport.flush(timeout);
            } finally { clearTimeout(timer); }
          },
        };
      },
      dataCollection: {
        userInfo: false, cookies: false, httpHeaders: false, httpBodies: [], urlQueryParams: false,
        graphQL: { document: false, variables: false }, genAI: { inputs: false, outputs: false },
        databaseQueryData: false, queues: false, stackFrameVariables: false, frameContextLines: 0,
      },
      integrations: defaults => defaults.filter(integration =>
        !["Breadcrumbs", "BrowserSession", "Feedback", "Replay"].includes(integration.name)
      ).concat(config.traces_sample_rate > 0 ? [Sentry.browserTracingIntegration({
        beforeStartSpan: options => ({ ...options, name: canonicalRoute(options.name), attributes: {} }),
      })] : []),
      tracesSampler: context => {
        const route = canonicalRoute(context.name);
        if (config.traces_sample_rate === 0 || route === "unmatched" || route === "/api/v1/auth/telemetry-config") return 0;
        return context.inheritOrSampleWith(config.traces_sample_rate);
      },
      tracePropagationTargets: config.traces_sample_rate > 0 ? propagationTargets(window.location.origin) : [],
      beforeSend: (event, hint) => {
        if (!permitsDiagnostics()) return null;
        hint.attachments = [];
        if (isExpectedClientFailure(hint.originalException)) return null;
        const clean = sanitizeEvent(event);
        if (clean) clean.environment = config.environment;
        return clean;
      },
      beforeSendTransaction: (event, hint) => {
        if (!permitsDiagnostics()) return null;
        hint.attachments = [];
        const clean = sanitizeEvent(event);
        if (clean) clean.environment = config.environment;
        return clean;
      },
      beforeBreadcrumb: sanitizeBreadcrumb,
      beforeSendLog: () => null, beforeSendMetric: () => null,
      replaysSessionSampleRate: replayAllowed ? config.replays_session_sample_rate : 0,
      replaysOnErrorSampleRate: replayAllowed ? config.replays_on_error_sample_rate : 0,
    });
    Sentry.addEventProcessor(event => {
      const clean = sanitizeReplayMetadata(event);
      if (clean?.type === "replay_event") clean.environment = config.environment;
      return clean;
    });
    if (replayAllowed && (config.replays_session_sample_rate > 0 || config.replays_on_error_sample_rate > 0)) {
      // Do not hold rendering on the optional recorder download.
      void import("./replay").then(({ createReplay }) => {
        if (permitsReplay() && !location.search && !location.hash) Sentry.addIntegration(createReplay());
      }).catch(() => {});
    }
    return true;
  } catch { return false; }
}

export function navigationBreadcrumb(page: "dashboard" | "admin" | "login" | "register") {
  if (!permitsDiagnostics()) return;
  Sentry.addBreadcrumb({ category: "sso.navigation", message: page, level: "info" });
}

export function captureContractFailure(): void {
  if (!permitsDiagnostics()) return;
  Sentry.captureException(new Error("Unexpected interface failure"));
}

export async function stopTelemetry(): Promise<void> {
  const client = Sentry.getClient();
  if (client) client.getOptions().enabled = false;
  await Promise.resolve(Sentry.getReplay()?.stop({ flush: false })).catch(() => {});
  await Promise.resolve(client?.close(0)).catch(() => {});
}
