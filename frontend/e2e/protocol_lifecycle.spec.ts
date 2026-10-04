import { test, expect, type Page } from "@playwright/test";
import { createHash, randomBytes } from "node:crypto";
import { createServer } from "node:http";
import { acceptDocumentsAfterLogin } from "./helpers/legal";
import { confirmSensitiveAction } from "./helpers/reauthentication";

const password = "ProtocolBrowserSynthetic2026!";
const callback = "http://localhost:8001/callback";

async function login(page: Page) {
  await page.getByLabel("Имя пользователя или Email").fill("e2e_protocol_user");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
}

function authorize(origin: string, policy: Record<string, string>) {
  const verifier = randomBytes(48).toString("base64url");
  const nonce = randomBytes(24).toString("base64url");
  const state = randomBytes(24).toString("base64url");
  const query = new URLSearchParams({ client_id: "client_analytics_app", redirect_uri: callback, response_type: "code", scope: "openid profile", state, nonce, code_challenge: createHash("sha256").update(verifier).digest("base64url"), code_challenge_method: "S256", ...policy });
  return { url: origin + "/oauth/authorize?" + query, verifier, nonce, state };
}

test("Real browser prompt login/none/max_age and credential-event session invalidation", async ({ page, browser }) => {
  page.on("requestfailed", request => {
    const target = new URL(request.url());
    console.info("Protocol transport failure", target.origin + target.pathname, request.failure()?.errorText);
  });
  const origin = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173";
  const silent = authorize(origin, { prompt: "none" });
  const noSession = await page.request.get(silent.url, { maxRedirects: 0 });
  const error = new URL(noSession.headers().location);
  expect(error.searchParams.get("error")).toBe("login_required");
  expect(error.searchParams.get("state")).toBe(silent.state);
  expect(error.origin).toBe(new URL(callback).origin);
  await page.goto("/");
  await login(page);
  await acceptDocumentsAfterLogin(page);
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  const other = await browser.newContext({ baseURL: origin });
  await other.addCookies(await page.context().cookies());
  const landing = createServer((request, response) => {
    response.writeHead(request.url?.startsWith("/callback?") ? 200 : 404, { "Content-Type": "text/plain" });
    response.end("Registered RP callback landing");
  });
  try {
    // A real loopback HTTP landing receives the registered redirect. Installed
    // SDK flows are tested separately in multi_client_sso; no OP traffic is mocked.
    await new Promise<void>((resolve, reject) => {
      landing.once("error", reject);
      landing.listen(8001, "127.0.0.1", resolve);
    });
    const policies: Record<string, string>[] = [{ prompt: "login" }, { max_age: "0" }];
    for (const policy of policies) {
      const flow = authorize(origin, policy);
      await page.goto(flow.url);
      await expect(page.getByLabel("Имя пользователя или Email")).toBeVisible();
      expect(page.url()).toContain("force_login=1");
      await login(page);
      await expect(page).toHaveURL(new RegExp("^http://localhost:8001/callback\\?"));
      const returned = new URL(page.url());
      expect(returned.searchParams.get("state")).toBe(flow.state);
      const code = returned.searchParams.get("code");
      expect(code).toBeTruthy();
      const response = await page.request.post(origin + "/oauth/token", { form: { grant_type: "authorization_code", client_id: "client_analytics_app", client_secret: process.env.E2E_CLIENT1_SECRET || "analytics_client_secret_123", redirect_uri: callback, code: code!, code_verifier: flow.verifier } });
      expect(response.status()).toBe(200);
      expect(response.headers()["cache-control"]).toBe("no-store");
      const tokens = await response.json();
      const claims = JSON.parse(Buffer.from(tokens.id_token.split(".")[1], "base64url").toString());
      expect(claims.nonce).toBe(flow.nonce);
      expect(Number.isInteger(claims.auth_time)).toBe(true);
      expect(Date.now() / 1000 - claims.auth_time).toBeLessThan(5);
    }
    await page.goto("/");
    const authenticated = authorize(origin, { prompt: "none", max_age: "300" });
    const recent = await page.request.get(authenticated.url, { maxRedirects: 0 });
    expect(new URL(recent.headers().location).searchParams.get("code")).toBeTruthy();
    const stale = authorize(origin, { prompt: "none", max_age: "0" });
    expect(new URL((await page.request.get(stale.url, { maxRedirects: 0 })).headers().location).searchParams.get("error")).toBe("login_required");
    await expect(page.getByText("Личный кабинет", { exact: true })).toBeVisible();
    const current = await (await page.request.get("/api/v1/auth/me")).json();
    expect(current.id ?? current.user_id).toBe(me.id ?? me.user_id);
    await page.getByRole("button", { name: "Изменить пароль", exact: true }).click();
    const dialog = page.locator('[role="dialog"][aria-label="Смена пароля"]');
    await dialog.getByLabel("Текущий пароль").fill(password);
    await dialog.getByLabel("Новый пароль (мин. 15 символов)").fill("NewProtocolBrowserSynthetic2026!");
    await dialog.getByLabel("Подтверждение нового пароля").fill("NewProtocolBrowserSynthetic2026!");
    await dialog.getByRole("button", { name: "Сохранить новый пароль" }).click();
    const proofDialog = page.getByRole("dialog", { name: "Подтверждение чувствительной операции" });
    await expect(proofDialog).toBeVisible();
    await expect(dialog).toHaveJSProperty("inert", true);
    await proofDialog.getByLabel("Текущий пароль").focus();
    await page.keyboard.press("Shift+Tab");
    await expect(proofDialog.getByRole("button", { name: "Подтвердить", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(proofDialog).toBeHidden();
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveJSProperty("inert", false);
    await expect(dialog.getByRole("button", { name: "Сохранить новый пароль" })).toBeEnabled();
    await dialog.getByRole("button", { name: "Сохранить новый пароль" }).click();
    await confirmSensitiveAction(page, password);
    await expect(dialog).toBeHidden();
    expect((await other.request.get("/api/v1/auth/me")).status()).toBe(401);
    expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);
  } finally {
    landing.closeAllConnections();
    await new Promise<void>(resolve => landing.close(() => resolve()));
    await other.close();
  }
});
