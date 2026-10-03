import * as Sentry from "@sentry/react";
import { sanitizeBreadcrumb, sanitizeEvent, sanitizeReplayMetadata, canonicalRoute } from "./privacy";
import type { TelemetryConfig } from "../types/api";
import { permitsDiagnostics, permitsReplay, PRIVACY_CHANGE, PRIVACY_KEY } from "./consent";

export function parseConfig(value: unknown): TelemetryConfig | null {
  if (!value || typeof value !== "object") return null;
  const config = value as TelemetryConfig;
  if (typeof config.enabled !== "boolean" || typeof config.replay_enabled !== "boolean" ||
      !["local", "test", "staging", "production"].includes(config.environment) ||
      ![config.traces_sample_rate, config.replays_session_sample_rate, config.replays_on_error_sample_rate]
        .every(rate => typeof rate === "number" && Number.isFinite(rate) && rate >= 0 && rate <= 1) ||
      !Array.isArray(config.trace_propagation_targets) ||
      !config.trace_propagation_targets.every(target => typeof target === "string") ||
      typeof config.dsn !== "string") return null;
  if (config.enabled) {
    try {
      const dsn = new URL(config.dsn);
      if (dsn.protocol !== "https:" || !/^o\d+\.ingest(?:\.[a-z]+)?\.sentry\.io$/.test(dsn.hostname) ||
          !/^[a-zA-Z0-9]+$/.test(dsn.username) || dsn.password || dsn.search || dsn.hash ||
          !/^\/\d+$/.test(dsn.pathname) || (dsn.port && dsn.port !== "443")) return null;
    } catch { return null; }
  }
  return config;
}

export function propagationTargets(origin: string): RegExp[] {
  const escaped = origin.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return [new RegExp(`^${escaped}/(?:api|oauth)/`), /^\/(?:api|oauth)\//];
}

export function isExpectedClientFailure(error: unknown): boolean {
  if ((error instanceof Error || error instanceof DOMException) &&
      ["ApiError", "NetworkError", "AbortError", "NotAllowedError"].includes(error.name)) return true;
  return error instanceof TypeError && /^(Failed to fetch|Load failed|NetworkError when attempting to fetch resource\.)$/.test(error.message);
}

export async function bootstrapTelemetry(): Promise<boolean> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    // The race bounds even a broken fetch/JSON implementation; abort is cleanup.
    const config = await Promise.race([
      fetch("/api/v1/auth/telemetry-config", { credentials: "omit", cache: "no-store", signal: controller.signal })
        .then(response => response.ok ? response.json() : null).then(parseConfig),
      new Promise<null>(resolve => { timer = setTimeout(() => { controller.abort(); resolve(null); }, 300); }),
    ]);
    if (!config?.enabled || !permitsDiagnostics()) return false;
    return initializeTelemetry(config);
  } catch { return false; }
  finally { clearTimeout(timer); controller.abort(); }
}

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

export function watchTelemetryConsent(): () => void {
  let previous = ""; let generation = 0;
  const update = () => {
    const signature = `${permitsDiagnostics()}:${permitsReplay()}`;
    if (signature === previous) return;
    previous = signature;
    const current = ++generation;
    const client = Sentry.getClient();
    if (client) client.getOptions().enabled = false;
    // Transport checks consent again, including after asynchronous envelope sanitization.
    void Promise.resolve(Sentry.getReplay()?.stop({ flush: false })).catch(() => {}).then(() => client?.close(0)).catch(() => {}).then(() => {
      if (current === generation && permitsDiagnostics()) void bootstrapTelemetry();
    });
  };
  const storage = (event: StorageEvent) => { if (event.key === PRIVACY_KEY || event.key === null) update(); };
  window.addEventListener(PRIVACY_CHANGE, update); window.addEventListener("storage", storage);
  const timer = window.setInterval(update, 60_000);
  update();
  return () => { generation++; clearInterval(timer); window.removeEventListener(PRIVACY_CHANGE, update); window.removeEventListener("storage", storage); };
}
