import { test, expect, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { acceptDocumentsAfterLogin } from "./helpers/legal";
import { confirmSensitiveAction } from "./helpers/reauthentication";
import { prepareIndependentScenario } from "./helpers/prepare";

const password = "TOTPBrowserSynthetic2026!";

test.beforeEach(prepareIndependentScenario);

function otp(secret: string): string {
  const python = process.env.PYTHON_BIN;
  if (!python) throw new Error("Installed test Python is required");
  const result = spawnSync(python, ["-c", "import sys,pyotp; print(pyotp.TOTP(sys.stdin.read().strip()).now())"], { input: secret, encoding: "utf8" });
  if (result.status !== 0 || !/^\d{6}$/.test(result.stdout.trim())) throw new Error("Synthetic OTP computation failed");
  return result.stdout.trim();
}

async function nextTotpWindow(): Promise<void> {
  // Wait for an actual RFC6238 step. Do not rewrite server clocks or reset replay state.
  const remaining = 30000 - Date.now() % 30000 + 1000;
  await new Promise(resolve => setTimeout(resolve, remaining));
}

async function passwordLogin(page: Page) {
  await page.getByLabel("Имя пользователя или Email").fill("e2e_totp_user");
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
}

test("Real TOTP enrollment, factor reauthentication, recovery replay and password+TOTP login", async ({ page }) => {
  // Two real 30-second anti-replay windows are part of this lifecycle.
  test.setTimeout(100000);
  await page.goto("/");
  const caps = await (await page.request.get("/api/v1/auth/capabilities")).json();
  expect(caps.capabilities?.totp_enabled ?? caps.totp_enabled).toBe(true);
  await passwordLogin(page);
  await acceptDocumentsAfterLogin(page);
  await page.goto("/account/security");
  await page.getByTestId("setup-totp-button").click();
  await confirmSensitiveAction(page, password);
  await expect(page.getByTestId("totp-qr-code").locator("svg")).toBeVisible();
  const secret = (await page.getByTestId("totp-secret").innerText()).trim();
  expect(secret.length).toBeGreaterThanOrEqual(16);
  await page.getByTestId("totp-code-input").fill(otp(secret));
  await page.getByTestId("confirm-totp-button").click();
  await confirmSensitiveAction(page, password);
  await expect(page.getByTestId("totp-success")).toBeVisible();
  await expect(page.getByTestId("disable-totp-button")).toBeVisible();
  await nextTotpWindow();
  await page.getByTestId("generate-recovery-codes-button").click();
  const dialog = page.getByRole("dialog", { name: "Подтверждение чувствительной операции" });
  await dialog.getByLabel("Текущий пароль").fill(password);
  await dialog.getByRole("button", { name: "Подтвердить", exact: true }).click();
  await dialog.getByLabel("Второй фактор").selectOption("totp");
  await dialog.getByLabel("Код подтверждения").fill(otp(secret));
  await dialog.getByRole("button", { name: "Подтвердить", exact: true }).click();
  await expect(page.getByTestId("recovery-codes-display")).toBeVisible();
  const recovery = await page.getByTestId("recovery-codes-display").locator(".grid > div").first().innerText();
  expect(recovery.trim()).toMatch(/^[A-Z0-9]{8}(?:-[A-Z0-9]{8}){3}$/);
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await passwordLogin(page);
  await expect(page.getByLabel("Одноразовый код или код восстановления")).toBeVisible();
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);
  await page.getByLabel("Одноразовый код или код восстановления").fill(recovery.trim());
  await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
  await expect(page.getByText("Личный кабинет", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await passwordLogin(page);
  await page.getByLabel("Одноразовый код или код восстановления").fill(recovery.trim());
  await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);
  await nextTotpWindow();
  await page.getByLabel("Одноразовый код или код восстановления").fill(otp(secret));
  await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
  await expect(page.getByText("Личный кабинет", { exact: true })).toBeVisible();
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(200);
});
