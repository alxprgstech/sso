import { test, expect, Page } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import http from "http";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test.describe.serial("Cross-Client SSO & OIDC Delegation Suite (G8-SDK / FINAL-09)", () => {
  test.use({ baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173" });

  let page: Page;
  let server8001: http.Server | null = null;
  let server8002: http.Server | null = null;

  test.beforeAll(async ({ browser }) => {
    const testDbUrl = process.env.TEST_DATABASE_URL;
    if (!testDbUrl) {
      throw new Error("TEST_DATABASE_URL environment variable is required for E2E tests");
    }
    let pythonExe =
      process.env.PYTHON_BIN ||
      (process.platform === "win32"
        ? path.resolve(__dirname, "../../.venv/Scripts/python.exe")
        : path.resolve(__dirname, "../../.venv/bin/python"));
    if (!fs.existsSync(pythonExe)) {
      pythonExe = process.platform === "win32" ? "python" : "python3";
    }
    const scriptPath = path.resolve(__dirname, "../../scripts/prepare_e2e_data.py");
    execFileSync(pythonExe, [scriptPath], {
      env: {
        ...process.env,
        TEST_DATABASE_URL: testDbUrl,
      },
      stdio: "inherit",
    });

    // Запускаем легкие слушающие HTTP-серверы для callback URL демонстрационных клиентов
    server8001 = http.createServer((_req, res) => {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end("<!DOCTYPE html><html><body><h1>Client 1 Callback OK</h1></body></html>");
    }).listen(8001);

    server8002 = http.createServer((_req, res) => {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end("<!DOCTYPE html><html><body><h1>Client 2 Callback OK</h1></body></html>");
    }).listen(8002);

    page = await browser.newPage();
  });

  test.afterAll(async () => {
    if (page) {
      await page.close();
    }
    if (server8001) {
      server8001.close();
    }
    if (server8002) {
      server8002.close();
    }
  });

  test("01. Client 1 Authorization redirects unauthenticated user to SSO login and preserves return_to", async () => {
    // 1. Имитируем переход пользователя из Client 1 (Analytics) на /oauth/authorize
    const client1Redirect = "http://localhost:8001/callback";
    const state1 = "state_client1_flow_xyz123";
    const challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"; // S256 hash
    const authUrl1 =
      `/oauth/authorize?client_id=client_analytics_app` +
      `&redirect_uri=${encodeURIComponent(client1Redirect)}` +
      `&response_type=code` +
      `&scope=openid%20profile%20email` +
      `&state=${state1}` +
      `&code_challenge=${challenge}` +
      `&code_challenge_method=S256`;

    await page.goto(authUrl1);

    // Должен произойти редирект на /login?return_to=...
    await expect(page).toHaveURL(/\/login\?return_to=/);
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible();

    // 2. Входим под пользователем
    await page.fill('input[placeholder="user@alxprgs.tech"]', "compose_admin");
    await page.fill('input[type="password"]', "ComposeAdminPass2026!");
    await page.click('button[type="submit"]');

    // 3. После успешного входа SSO сервер перенаправляет обратно на redirect_uri Client 1 с authorization code
    await page.waitForURL((url) => {
      return (
        url.hostname === "localhost" &&
        url.port === "8001" &&
        url.pathname === "/callback" &&
        url.searchParams.has("code") &&
        url.searchParams.get("state") === state1
      );
    }, { timeout: 15000 });

    const currentUrl = new URL(page.url());
    const authCode1 = currentUrl.searchParams.get("code");
    expect(authCode1).toBeTruthy();
    expect(authCode1!.length).toBeGreaterThan(20);
    expect(currentUrl.searchParams.get("state")).toBe(state1);
  });

  test("02. Seamless SSO to Client 2 without re-entering credentials", async () => {
    // Пользователь уже вошел в SSO в предыдущем тесте (сессионная cookie активна).
    // Переход на /oauth/authorize для Client 2 (Docs) должен моментально выдать код без формы логина!
    const client2Redirect = "http://localhost:8002/callback";
    const state2 = "state_client2_flow_abc789";
    const challenge2 = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";
    const authUrl2 =
      `/oauth/authorize?client_id=client_docs_app` +
      `&redirect_uri=${encodeURIComponent(client2Redirect)}` +
      `&response_type=code` +
      `&scope=openid%20profile` +
      `&state=${state2}` +
      `&code_challenge=${challenge2}` +
      `&code_challenge_method=S256`;

    await page.goto(authUrl2);

    // Никакой формы логина! Мгновенный редирект на callback Client 2
    await page.waitForURL((url) => {
      return (
        url.hostname === "localhost" &&
        url.port === "8002" &&
        url.pathname === "/callback" &&
        url.searchParams.has("code") &&
        url.searchParams.get("state") === state2
      );
    }, { timeout: 15000 });

    const currentUrl = new URL(page.url());
    const authCode2 = currentUrl.searchParams.get("code");
    expect(authCode2).toBeTruthy();
    expect(authCode2!.length).toBeGreaterThan(20);
    expect(currentUrl.searchParams.get("state")).toBe(state2);
  });

  test("03. Scopes filtering & rejection of unpermitted scopes", async () => {
    const client1Redirect = "http://localhost:8001/callback";
    const challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";

    // Scope без openid должен возвращать 400 invalid_scope
    const invalidAuthUrl =
      `/oauth/authorize?client_id=client_analytics_app` +
      `&redirect_uri=${encodeURIComponent(client1Redirect)}` +
      `&response_type=code` +
      `&scope=profile%20email` +
      `&code_challenge=${challenge}` +
      `&code_challenge_method=S256`;

    const response = await page.goto(invalidAuthUrl);
    expect(response?.status()).toBe(400);
  });

  test("04. SSO Logout terminates session and revokes access across clients", async () => {
    // 1. Переходим в интерфейс личного кабинета и выполняем выход
    await page.goto("/");
    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });
    const logoutPromise = page.waitForResponse(
      (resp) => resp.url().includes("/auth/logout") && resp.status() === 200
    );
    await page.click('button:has-text("Выйти")');
    await logoutPromise;
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible({ timeout: 10000 });

    // 2. Теперь попытка перехода на Client 2 снова требует логина
    const client2Redirect = "http://localhost:8002/callback";
    const challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";
    const authUrl2 =
      `/oauth/authorize?client_id=client_docs_app` +
      `&redirect_uri=${encodeURIComponent(client2Redirect)}` +
      `&response_type=code` +
      `&scope=openid%20profile` +
      `&code_challenge=${challenge}` +
      `&code_challenge_method=S256`;

    await page.goto(authUrl2);
    // Должен перенаправить на страницу входа
    await expect(page).toHaveURL(/\/login\?return_to=/);
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible();
  });
});
