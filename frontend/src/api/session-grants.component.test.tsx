import { afterEach, expect, it, vi } from "vitest";
import { api, SESSIONS_READ_GRANT_KEY } from "./client";
import { webcrypto } from "node:crypto";

vi.mock("../telemetry/sentry", () => ({ captureContractFailure: vi.fn() }));

afterEach(() => {
  api.setCsrfToken(null);
  api.setReauthenticationHandler(null);
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

function proof(authorization: string, expiresAt?: string) {
  return { authorization, factor_required: false, expires_at: expiresAt };
}

it("reuses the read grant, refreshes expiry and never sends it to a mutation", async () => {
  api.setCsrfToken("synthetic-csrf");
  const issued = ["synthetic-read-one", "synthetic-read-two", "synthetic-mutation"];
  const actions: string[] = [];
  const confirm = vi.fn(async (action: string) => {
    actions.push(action);
    return proof(issued.shift()!);
  });
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

it("reuses the documented five-minute grant after a page reload without prompting", async () => {
  api.setCsrfToken("synthetic-csrf");
  const handler = vi.fn();
  api.setReauthenticationHandler(handler);
  window.sessionStorage.setItem(
    SESSIONS_READ_GRANT_KEY,
    JSON.stringify({
      authorization: "synthetic-stored-grant",
      expiresAt: Date.now() + 60_000,
    }),
  );
  const sent: (string | null)[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, options: RequestInit) => {
    sent.push(new Headers(options.headers).get("X-Reauthentication"));
    return new Response(JSON.stringify([]), { status: 200 });
  }));
  await expect(api.getSessions()).resolves.toEqual([]);
  expect(sent).toEqual(["synthetic-stored-grant"]);
  expect(handler).not.toHaveBeenCalled();
});

it("drops an expired stored grant and asks for a fresh confirmation", async () => {
  api.setCsrfToken("synthetic-csrf");
  window.sessionStorage.setItem(
    SESSIONS_READ_GRANT_KEY,
    JSON.stringify({ authorization: "expired", expiresAt: Date.now() - 1 }),
  );
  const handler = vi.fn(async () => proof("synthetic-fresh", new Date(Date.now() + 300_000).toISOString()));
  api.setReauthenticationHandler(handler);
  vi.stubGlobal("crypto", webcrypto);
  const sent: (string | null)[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, options: RequestInit) => {
    const grant = new Headers(options.headers).get("X-Reauthentication");
    sent.push(grant);
    if (!grant || grant === "expired") {
      return new Response(JSON.stringify({ error: "reauthentication_required" }), { status: 401 });
    }
    return new Response(JSON.stringify([]), { status: 200 });
  }));
  await api.getSessions();
  expect(handler).toHaveBeenCalledTimes(1);
  expect(sent).toEqual([null, "synthetic-fresh"]);
  const stored = JSON.parse(window.sessionStorage.getItem(SESSIONS_READ_GRANT_KEY)!);
  expect(stored.authorization).toBe("synthetic-fresh");
  expect(stored.expiresAt).toBeGreaterThan(Date.now());
});

it("clears the stored grant when the browser session changes", async () => {
  api.setCsrfToken("synthetic-csrf");
  window.sessionStorage.setItem(
    SESSIONS_READ_GRANT_KEY,
    JSON.stringify({
      authorization: "synthetic-stored-grant",
      expiresAt: Date.now() + 60_000,
    }),
  );
  api.setCsrfToken("another-session-csrf");
  expect(window.sessionStorage.getItem(SESSIONS_READ_GRANT_KEY)).toBeNull();
});

it("coalesces identical pending reads but never shares a mutation proof", async () => {
  api.setCsrfToken("synthetic-csrf");
  vi.stubGlobal("crypto", webcrypto);
  let releaseFetch!: () => void;
  const fetchGate = new Promise<void>((resolve) => { releaseFetch = resolve; });
  let releaseProof!: () => void;
  const proofGate = new Promise<void>((resolve) => { releaseProof = resolve; });
  const handler = vi.fn(async () => {
    await proofGate;
    return proof("synthetic-shared");
  });
  api.setReauthenticationHandler(handler);
  const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
    await fetchGate;
    const grant = new Headers(options.headers).get("X-Reauthentication");
    if (!grant) return new Response(JSON.stringify({ error: "reauthentication_required" }), { status: 401 });
    return new Response(JSON.stringify([]), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const first = api.getSessions();
  const second = api.getSessions();
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  releaseFetch();
  await vi.waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
  releaseProof();
  await Promise.all([first, second]);
  expect(handler).toHaveBeenCalledTimes(1);

  handler.mockClear();
  const mutation = vi.fn(async () => proof("synthetic-one"));
  api.setReauthenticationHandler(mutation);
  await Promise.all([api.revokeOtherSessions(), api.revokeOtherSessions()]);
  expect(mutation).toHaveBeenCalledTimes(2);
});
