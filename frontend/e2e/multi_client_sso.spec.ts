import { test, expect, type Page } from "@playwright/test";
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const clientProcesses: ChildProcessWithoutNullStreams[] = [];
const clientOrigins = ["http://localhost:8001", "http://localhost:8002"];
const isAuthorizationRequest = (url: URL): boolean =>
  url.pathname === "/oauth/authorize";
test.use({ trace: "off" }); // Authorization codes and ID tokens must not enter a retained trace.

async function startClient(python: string, module: string, port: number, clientSecret: string): Promise<void> {
  const probe = await fetch(`http://localhost:${port}/`, { signal: AbortSignal.timeout(1000) }).catch(() => null);
  if (probe) throw new Error(`Port ${port} is already occupied; refusing to use or stop an unowned process`);
  const child = spawn(python, ["-m", "uvicorn", module, "--host", "127.0.0.1", "--port", String(port), "--workers", "1"], {
    cwd: root,
    env: {
      ...process.env,
      CLIENT_SECRET: clientSecret,
      CLIENT_ID: port === 8001 ? "client_analytics_app" : "client_docs_app",
      REDIRECT_URI: `http://localhost:${port}/callback`,
      DEMO_ALLOW_HTTP_LOCALHOST: "1",
      SSO_SERVER_URL: process.env.E2E_SSO_URL || "http://localhost:8000",
      OIDC_ISSUER: process.env.E2E_ISSUER || "https://auth.alxprgs.tech",
      PYTHONUNBUFFERED: "1",
    },
    stdio: "pipe",
  });
  clientProcesses.push(child);
  let output = "";
  child.stderr.on("data", (chunk: Buffer) => { output = (output + chunk.toString()).slice(-1500); });
  for (let attempt = 0; attempt < 100; attempt++) {
    if (child.exitCode !== null) throw new Error(`Client process exited before readiness (exit ${child.exitCode}); inspect its private log`);
    const response = await fetch(`http://localhost:${port}/`, { signal: AbortSignal.timeout(500) }).catch(() => null);
    if (response?.ok) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Client ${port} was not ready; process output length ${output.length}`);
}

test.describe.serial("Two real FastAPI clients and installed SDK", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    const python = process.env.PYTHON_BIN;
    const firstSecret = process.env.E2E_CLIENT1_SECRET;
    const secondSecret = process.env.E2E_CLIENT2_SECRET;
    if (!python || !firstSecret || !secondSecret || !process.env.E2E_USERNAME || !process.env.E2E_PASSWORD) {
      throw new Error("PYTHON_BIN and explicit isolated E2E client/user credentials are required");
    }
    const installed = spawnSync(python, ["-c", "import alxprgs_sso, pathlib; print(pathlib.Path(alxprgs_sso.__file__).resolve())"], {
      cwd: root, encoding: "utf8", timeout: 10000,
    });
    if (installed.status !== 0 || !installed.stdout.includes("site-packages")) {
      throw new Error("The configured Python must import SDK from an installed wheel in site-packages");
    }
    await startClient(python, "examples.client1.app:app", 8001, firstSecret);
    await startClient(python, "examples.client2.app:app", 8002, secondSecret);
    page = await browser.newPage();
  });

  test.afterAll(async () => {
    if (page) await page.close();
    for (const child of clientProcesses) {
      if (child.exitCode === null) child.kill();
    }
  });

  test("password login, second-client SSO, replay, local and SSO logout", async ({ browser }) => {
    const callbackUrls: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/callback?code=")) callbackUrls.push(request.url());
    });
    await page.goto(clientOrigins[0]);
    await page.click("#btn-login");
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible();
    await page.fill('input[placeholder="user@alxprgs.tech"]', process.env.E2E_USERNAME!);
    await page.fill('input[type="password"]', process.env.E2E_PASSWORD!);
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL(`${clientOrigins[0]}/dashboard`);
    await expect(page.locator("#username")).toHaveText(process.env.E2E_USERNAME!);
    expect((await page.request.get(`${clientOrigins[0]}/api/me`)).status()).toBe(200);
    expect(callbackUrls).toHaveLength(1);

    await page.goto(clientOrigins[1]);
    await page.click("#btn-login");
    await expect(page).toHaveURL(`${clientOrigins[1]}/dashboard`);
    await expect(page.locator("#username")).toHaveText(process.env.E2E_USERNAME!);
    expect((await page.request.get(`${clientOrigins[1]}/api/me`)).status()).toBe(200);
    expect(callbackUrls).toHaveLength(2);

    const replay = await page.request.get(callbackUrls[0], { maxRedirects: 0 });
    expect(replay.status()).toBe(400);
    const foreignContext = await browser.newContext();
    try {
      const foreign = await foreignContext.request.get(callbackUrls[1], { maxRedirects: 0 });
      expect(foreign.status()).toBe(400);
    } finally {
      await foreignContext.close();
    }

    await page.goto(`${clientOrigins[0]}/dashboard`);
    await page.click("#btn-logout");
    await expect(page).toHaveURL(`${clientOrigins[0]}/`);
    expect((await page.request.get(`${clientOrigins[0]}/api/me`)).status()).toBe(401);
    expect((await page.request.get(`${clientOrigins[1]}/api/me`)).status()).toBe(200);

    // A real authorization response with the wrong nonce must fail in the SDK callback.
    let nonceTampered = false;
    await page.route(isAuthorizationRequest, async (route) => {
      const altered = new URL(route.request().url());
      altered.searchParams.set("nonce", "synthetic-wrong-nonce");
      nonceTampered = true;
      await route.continue({ url: altered.toString() });
    });
    const wrongNonce = await page.goto(`${clientOrigins[0]}/login`);
    const finalLocation = new URL(page.url());
    expect(
      nonceTampered,
      `Authorization interception missed; navigation ended at ${finalLocation.origin}${finalLocation.pathname}`,
    ).toBe(true);
    expect(
      wrongNonce?.status(),
      `Wrong-nonce navigation ended at ${finalLocation.origin}${finalLocation.pathname}`,
    ).toBe(400);
    expect((await page.request.get(`${clientOrigins[0]}/api/me`)).status()).toBe(401);
    await page.unroute(isAuthorizationRequest);

    // The authorization server issues a code, but the client's original PKCE verifier cannot redeem it.
    await page.route(isAuthorizationRequest, async (route) => {
      const altered = new URL(route.request().url());
      altered.searchParams.set("code_challenge", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
      await route.continue({ url: altered.toString() });
    });
    const wrongPkce = await page.goto(`${clientOrigins[0]}/login`);
    expect(wrongPkce?.status()).toBe(400);
    expect((await page.request.get(`${clientOrigins[0]}/api/me`)).status()).toBe(401);
    await page.unroute(isAuthorizationRequest);

    await page.route(isAuthorizationRequest, async (route) => {
      const altered = new URL(route.request().url());
      altered.searchParams.set("redirect_uri", `${clientOrigins[0]}/unregistered`);
      await route.continue({ url: altered.toString() });
    });
    const wrongRedirect = await page.goto(`${clientOrigins[0]}/login`);
    expect(wrongRedirect?.status()).toBe(400);
    expect((await page.request.get(`${clientOrigins[0]}/api/me`)).status()).toBe(401);
    await page.unroute(isAuthorizationRequest);

    // Local logout does not end SSO; a fresh flow can complete without a password.
    await page.goto(`${clientOrigins[0]}/login`);
    await expect(page).toHaveURL(`${clientOrigins[0]}/dashboard`);
    await page.click("#btn-sso-logout");
    await expect(page).toHaveURL(/localhost:5173/);
    expect((await page.request.get(`${clientOrigins[1]}/api/me`)).status()).toBe(200);
    await page.goto(`${clientOrigins[0]}/login`);
    await expect(page).toHaveURL(/localhost:5173\/login\?return_to=/);

    // The flow belongs to this browser, and a failed state consumes it.
    const wrongState = await page.goto(`${clientOrigins[0]}/callback?code=synthetic&state=wrong`);
    expect(wrongState?.status()).toBe(400);
    await page.goto(`${clientOrigins[0]}/login`);
    const returnTo = new URL(page.url()).searchParams.get("return_to");
    expect(returnTo).toBeTruthy();
    const state = new URL(returnTo!).searchParams.get("state");
    expect(state).toBeTruthy();
    const failedExchange = await page.goto(`${clientOrigins[0]}/callback?code=synthetic&state=${encodeURIComponent(state!)}`);
    expect(failedExchange?.status()).toBe(400);
    expect((await page.request.get(`${clientOrigins[0]}/api/me`)).status()).toBe(401);
  });
});
