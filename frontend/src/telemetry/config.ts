import type { TelemetryConfig } from "../types/api";

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
