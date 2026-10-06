import type { TelemetryConfig } from "../types/api";
import { permitsDiagnostics, permitsReplay, PRIVACY_CHANGE, PRIVACY_KEY } from "./consent";
import { parseConfig } from "./config";
export { parseConfig, propagationTargets, isExpectedClientFailure } from "./config";

let runtime: typeof import("./sentry-runtime") | undefined;
let loading: Promise<typeof import("./sentry-runtime")> | undefined;
function loadRuntime() {
  return loading ??= import("./sentry-runtime").then(module => (runtime = module));
}

export async function initializeTelemetry(config: TelemetryConfig): Promise<boolean> {
  if (!parseConfig(config)?.enabled || !permitsDiagnostics()) return false;
  try {
    const sdk = await loadRuntime();
    return permitsDiagnostics() && sdk.initializeTelemetry(config);
  } catch { return false; }
}

export async function bootstrapTelemetry(isCurrent: () => boolean = () => true): Promise<boolean> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const config = await Promise.race([
      fetch("/api/v1/auth/telemetry-config", { credentials: "omit", cache: "no-store", signal: controller.signal })
        .then(response => response.ok ? response.json() : null).then(parseConfig),
      new Promise<null>(resolve => { timer = setTimeout(() => { controller.abort(); resolve(null); }, 300); }),
    ]);
    if (!config?.enabled || !permitsDiagnostics() || !isCurrent()) return false;
    const sdk = await loadRuntime();
    return isCurrent() && permitsDiagnostics() && sdk.initializeTelemetry(config);
  } catch { return false; }
  finally { clearTimeout(timer); controller.abort(); }
}

export function navigationBreadcrumb(page: "dashboard" | "admin" | "login" | "register") {
  if (permitsDiagnostics()) runtime?.navigationBreadcrumb(page);
}

export function captureContractFailure(): void {
  if (!permitsDiagnostics()) return;
  void loadRuntime().then(sdk => {
    if (permitsDiagnostics()) sdk.captureContractFailure();
  }).catch(() => {});
}

export function watchTelemetryConsent(): () => void {
  let previous = ""; let generation = 0;
  const update = () => {
    const signature = `${permitsDiagnostics()}:${permitsReplay()}`;
    if (signature === previous) return;
    previous = signature;
    const current = ++generation;
    // stopTelemetry disables the client synchronously before its first await.
    void (runtime?.stopTelemetry() ?? Promise.resolve()).then(() => {
      if (current === generation && permitsDiagnostics())
        void bootstrapTelemetry(() => current === generation);
    }).catch(() => {});
  };
  const storage = (event: StorageEvent) => { if (event.key === PRIVACY_KEY || event.key === null) update(); };
  window.addEventListener(PRIVACY_CHANGE, update); window.addEventListener("storage", storage);
  const timer = window.setInterval(update, 60_000);
  update();
  return () => { generation++; clearInterval(timer); window.removeEventListener(PRIVACY_CHANGE, update); window.removeEventListener("storage", storage); };
}
