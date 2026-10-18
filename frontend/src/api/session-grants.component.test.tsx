import { afterEach, expect, it, vi } from "vitest";
import { api } from "./client";
import { webcrypto } from "node:crypto";

vi.mock("../telemetry/sentry", () => ({ captureContractFailure: vi.fn() }));

afterEach(() => {
  api.setCsrfToken(null);
  api.setReauthenticationHandler(null);
  vi.unstubAllGlobals();
});

it("reuses the read grant, refreshes expiry and never sends it to a mutation", async () => {
  api.setCsrfToken("synthetic-csrf");
  const issued = ["synthetic-read-one", "synthetic-read-two", "synthetic-mutation"];
  const actions: string[] = [];
  const confirm = vi.fn(async (action: string) => { actions.push(action); return issued.shift()!; });
  vi.stubGlobal("crypto", webcrypto);
  api.setReauthenticationHandler(confirm);
  const requests: { method: string; grant: string | null }[] = [];
  let readCount = 0;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, options: RequestInit) => {
    const method = options.method ?? "GET";
    const grant = new Headers(options.headers).get("X-Reauthentication");
    requests.push({ method, grant });
    if (method === "GET") readCount++;
    const denied = !grant || (method === "GET" && readCount === 4);
    return new Response(JSON.stringify(denied ? { error: "reauthentication_required" } : method === "GET" ? [] : { status: "ok" }), { status: denied ? 401 : 200 });
  }));
  await api.getSessions();
  await api.getSessions();
  await api.getSessions();
  await api.revokeOtherSessions();
  expect(actions).toEqual([
    "GET /api/v1/auth/sessions", "GET /api/v1/auth/sessions", "DELETE /api/v1/auth/sessions",
  ]);
  expect(requests.filter(request => request.method === "DELETE").map(request => request.grant)).toEqual([null, "synthetic-mutation"]);
  expect(requests.filter(request => request.method === "GET").map(request => request.grant)).toEqual([null, "synthetic-read-one", "synthetic-read-one", "synthetic-read-one", "synthetic-read-two"]);
});
