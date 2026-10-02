import type { Breadcrumb, Event, ErrorEvent } from "@sentry/react";
import type { TransactionEvent } from "@sentry/core";

const pages = new Set(["/", "/login", "/register", "/verify-email", "/admin"]);
const apiRoutes = [
  /^\/api\/v1\/auth\/(capabilities|login|logout|me|change-password|sessions|register)$/,
  /^\/api\/v1\/auth\/register\/(confirm-code|confirm-link|preview-link|resend|confirm-gmail)$/,
  /^\/api\/v1\/(admin|mfa)\/[a-z-]+$/,
  /^\/oauth\/(authorize|token|userinfo|revoke|logout)$/,
];

export function canonicalRoute(value: string): string {
  try {
    const path = new URL(value, "https://sso.invalid").pathname;
    if (pages.has(path) || apiRoutes.some(pattern => pattern.test(path))) return path;
    if (/^\/api\/v1\/auth\/sessions\/[^/]+$/.test(path)) return "/api/v1/auth/sessions/{id}";
    if (/^\/api\/v1\/admin\/(users|clients)\/[^/]+$/.test(path)) return path.split("/").slice(0, 5).join("/") + "/{id}";
  } catch { /* fail closed */ }
  return "unmatched";
}

export function safeAsset(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value, globalThis.location?.origin || "https://sso.invalid");
    if (url.origin !== (globalThis.location?.origin || "https://sso.invalid")) return undefined;
    if (/^\/assets\/[A-Za-z0-9_-]+-[A-Za-z0-9_-]{8,}\.js$/.test(url.pathname)) return url.origin + url.pathname;
  } catch { /* fail closed */ }
  return undefined;
}

const errorKinds = new Set(["Error", "TypeError", "RangeError", "SyntaxError", "ReferenceError", "URIError", "AggregateError", "DOMException"]);
const hex = (value: unknown, length: number): value is string => typeof value === "string" && new RegExp(`^[a-f0-9]{${length}}$`).test(value);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

export function sanitizeEvent(event: ErrorEvent): ErrorEvent | null;
export function sanitizeEvent(event: TransactionEvent): TransactionEvent | null;
export function sanitizeEvent(event: Event): Event | null;
export function sanitizeEvent(event: Event): Event | null {
  try {
    const clean: Event = { platform: "javascript", level: "error", tags: { component: "frontend" } };
    clean.breadcrumbs = event.breadcrumbs?.flatMap(breadcrumb => {
      const clean = sanitizeBreadcrumb(breadcrumb);
      return clean ? [clean] : [];
    });
    if (hex(event.event_id, 32)) clean.event_id = event.event_id;
    if (finite(event.timestamp)) clean.timestamp = event.timestamp;
    if (typeof __BUILD_IDENTITY__ !== "undefined") clean.release = __BUILD_IDENTITY__.release;
    const trace = event.contexts?.trace;
    if (trace && hex(trace.trace_id, 32) && hex(trace.span_id, 16)) {
      clean.contexts = { trace: { trace_id: trace.trace_id, span_id: trace.span_id, op: "app" } };
    }
    clean.transaction = canonicalRoute(event.transaction || event.request?.url || "/");
    if (event.type === "transaction") {
      if (clean.transaction === "unmatched") return null;
      clean.type = "transaction";
      if (finite(event.start_timestamp)) clean.start_timestamp = event.start_timestamp;
      clean.transaction_info = { source: "route" };
      clean.spans = event.spans?.flatMap(span => hex(span.trace_id, 32) && hex(span.span_id, 16) && finite(span.timestamp) && finite(span.start_timestamp) ? [{
        trace_id: span.trace_id,
        span_id: span.span_id,
        parent_span_id: hex(span.parent_span_id, 16) ? span.parent_span_id : undefined,
        timestamp: span.timestamp, start_timestamp: span.start_timestamp,
        op: ["http.client", "pageload", "navigation"].includes(span.op || "") ? span.op : "app",
        description: "Application operation", data: {},
        status: span.status === "ok" ? "ok" as const : span.status === "internal_error" ? "internal_error" as const : "unknown_error" as const,
      }] : []);
    } else {
      if (!event.exception?.values?.length) return null;
      clean.exception = { values: event.exception.values.map(exception => ({
        type: errorKinds.has(exception.type || "") ? exception.type : "Error",
        value: "Unexpected interface failure",
        stacktrace: { frames: exception.stacktrace?.frames?.map(frame => ({
          filename: safeAsset(frame.filename), abs_path: safeAsset(frame.abs_path),
          lineno: finite(frame.lineno) ? frame.lineno : undefined,
          colno: finite(frame.colno) ? frame.colno : undefined, in_app: Boolean(safeAsset(frame.filename)),
        })) || [] },
      })) };
    }
    clean.debug_meta = { images: event.debug_meta?.images?.flatMap(image => {
      const file = "code_file" in image ? safeAsset(image.code_file) : undefined;
      return image.type === "sourcemap" && file && /^[a-f0-9-]{36}$/.test(image.debug_id || "")
        ? [{ type: "sourcemap" as const, code_file: file, debug_id: image.debug_id }] : [];
    }) || [] };
    return clean;
  } catch { return null; }
}

export function sanitizeBreadcrumb(breadcrumb: Breadcrumb): Breadcrumb | null {
  if (breadcrumb.category === "sso.navigation" && ["dashboard", "admin", "login", "register"].includes(breadcrumb.message || "")) {
    return { category: "sso.navigation", message: breadcrumb.message, level: "info" };
  }
  return null;
}

export function sanitizeReplayMetadata(event: Event): Event | null {
  try {
    if (event.type !== "replay_event") return event;
    // Replay metadata has its own schema; beforeSend does not process it.
    const source = event as Event & { replay_id?: string; replay_start_timestamp?: number; urls?: string[]; error_ids?: string[]; trace_ids?: string[]; segment_id?: number; replay_type?: string };
    const clean = {
      type: "replay_event", replay_id: hex(source.replay_id, 32) ? source.replay_id : undefined,
      timestamp: finite(source.timestamp) ? source.timestamp : undefined,
      replay_start_timestamp: finite(source.replay_start_timestamp) ? source.replay_start_timestamp : undefined,
      segment_id: finite(source.segment_id) ? source.segment_id : undefined,
      urls: source.urls?.map(canonicalRoute) || [],
      replay_type: ["session", "buffer"].includes(source.replay_type || "") ? source.replay_type : "buffer",
      error_ids: source.error_ids?.filter(id => hex(id, 32)) || [],
      trace_ids: source.trace_ids?.filter(id => hex(id, 32)) || [],
      platform: "javascript", release: typeof __BUILD_IDENTITY__ === "undefined" ? undefined : __BUILD_IDENTITY__.release,
    };
    return clean as Event;
  } catch { return null; }
}
