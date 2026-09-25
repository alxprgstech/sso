import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

import fs from "fs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test.describe("WebAuthn / Passkey Real Browser Lifecycle (G4-PASSKEY, QA-11)", () => {
  test.use({ baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173" });

  test.beforeAll(async () => {
    // G6-PREFLIGHT: Проверка соответствия профиля enabled (Passkey=True) до запуска UI тестов
    const baseUrl = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173";
    const capsRes = await fetch(`${baseUrl}/api/v1/auth/capabilities`);
    if (!capsRes.ok) {
      throw new Error(`[G6-PREFLIGHT-FAIL] /api/v1/auth/capabilities вернул HTTP ${capsRes.status}`);
    }
    const capsData = await capsRes.json();
    const caps = capsData?.capabilities ?? capsData;
    if (caps.passkey_enabled !== true) {
      throw new Error(
        `[G6-PREFLIGHT-FAIL] Enabled Passkey Suite требует passkey_enabled=true, ` +
        `но получено: ${JSON.stringify(caps)}. Процесс бэкенда запущен с неверным профилем! Остановка до таймаутов браузера!`
      );
    }
  });

  test.beforeEach(() => {
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
  });

  test("01. Enabled Profile Capabilities & Passkey Login Button Visibility", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible();

    // В enabled-профиле Passkey отображается как "Включено"
    await expect(page.getByText("Passkey (WebAuthn):")).toBeVisible();
    await expect(
      page.locator("div:has-text('Passkey (WebAuthn):') span:has-text('Включено')").first()
    ).toBeVisible();

    // Кнопка входа по Passkey отображается
    await expect(page.locator('[data-testid="passkey-login-button"]')).toBeVisible();
  });

  test("02. Real WebAuthn Registration of Multiple Credentials via CDP Virtual Authenticator", async ({ page }) => {
    // 1. Включаем первый виртуальный аутентификатор через Chrome DevTools Protocol (TouchID / internal)
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("WebAuthn.enable");
    const auth1 = await cdp.send("WebAuthn.addVirtualAuthenticator", {
      options: {
        protocol: "ctap2",
        transport: "internal",
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
      },
    });

    // 2. Входим под e2e_passkey_multi_user
    await page.goto("/");
    await page.fill('input[placeholder="user@alxprgs.tech"]', "e2e_passkey_multi_user");
    await page.fill('input[type="password"]', "PasskeyE2E2026!");
    await page.click('button[type="submit"]');

    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });
    await expect(page.locator('[data-testid="passkeys-section"]')).toBeVisible();

    // 3. Регистрируем первый Passkey: "MacBook TouchID" на первом аутентификаторе
    await page.fill('[data-testid="passkey-name-input"]', "MacBook TouchID");
    await page.click('[data-testid="register-passkey-button"]');

    // Проверяем сообщение об успехе и появление ключа в списке
    await expect(page.locator('[data-testid="passkey-success"]')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('[data-testid="passkeys-list"]')).toContainText("MacBook TouchID");

    // 4. Симулируем подключение второго физического аутентификатора (YubiKey 5C / usb)
    // Удаляем первый аутентификатор из CDP сессии и добавляем второй, чтобы excludeCredentials не блокировал регистрацию
    await cdp.send("WebAuthn.removeVirtualAuthenticator", { authenticatorId: auth1.authenticatorId });
    const auth2 = await cdp.send("WebAuthn.addVirtualAuthenticator", {
      options: {
        protocol: "ctap2",
        transport: "usb",
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
      },
    });

    // Регистрируем второй Passkey: "Yubikey 5C" (множественные credentials)
    await page.fill('[data-testid="passkey-name-input"]', "Yubikey 5C");
    await page.click('[data-testid="register-passkey-button"]');

    await expect(page.locator('[data-testid="passkey-success"]')).toBeVisible({ timeout: 10000 });
    // Проверяем, что в списке отображаются ОБА зарегистрированных ключа
    await expect(page.locator('[data-testid="passkeys-list"]')).toContainText("MacBook TouchID");
    await expect(page.locator('[data-testid="passkeys-list"]')).toContainText("Yubikey 5C");

    // Проверяем в CDP, что второй виртуальный аутентификатор содержит сгенерированный FIDO2 credential
    const cdpCreds = await cdp.send("WebAuthn.getCredentials", { authenticatorId: auth2.authenticatorId });
    expect(cdpCreds.credentials.length).toBeGreaterThanOrEqual(1);
  });

  test("03. Passwordless Login via WebAuthn Assertion", async ({ page }) => {
    // Подключаем CDP с виртуальным аутентификатором
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("WebAuthn.enable");
    await cdp.send("WebAuthn.addVirtualAuthenticator", {
      options: {
        protocol: "ctap2",
        transport: "internal",
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
      },
    });

    // Сначала регистрируем ключ для e2e_passkey_login_user
    await page.goto("/");
    await page.fill('input[placeholder="user@alxprgs.tech"]', "e2e_passkey_login_user");
    await page.fill('input[type="password"]', "PasskeyE2E2026!");
    await page.click('button[type="submit"]');
    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });

    await page.fill('[data-testid="passkey-name-input"]', "Resident Login Key");
    await page.click('[data-testid="register-passkey-button"]');
    await expect(page.locator('[data-testid="passkey-success"]')).toBeVisible({ timeout: 10000 });

    // Выходим из системы
    await page.click('button:has-text("Выйти")');
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible({ timeout: 10000 });

    // Входим БЕЗ ввода пароля — нажимаем кнопку Passkey!
    await page.click('[data-testid="passkey-login-button"]');

    // Ожидаем входа и перехода в Личный кабинет под пользователем e2e_passkey_login_user
    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("header").getByText("e2e_passkey_login_user", { exact: true })).toBeVisible();
  });

  test("04. Key Deletion and Verification that Deleted Key Fails Authentication", async ({ page }) => {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("WebAuthn.enable");
    await cdp.send("WebAuthn.addVirtualAuthenticator", {
      options: {
        protocol: "ctap2",
        transport: "internal",
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
      },
    });

    // Входим под e2e_passkey_delete_user
    await page.goto("/");
    await page.fill('input[placeholder="user@alxprgs.tech"]', "e2e_passkey_delete_user");
    await page.fill('input[type="password"]', "PasskeyE2E2026!");
    await page.click('button[type="submit"]');
    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });

    // Регистрируем временный ключ для последующего удаления
    await page.fill('[data-testid="passkey-name-input"]', "Key To Delete");
    await page.click('[data-testid="register-passkey-button"]');
    await expect(page.locator('[data-testid="passkey-success"]')).toBeVisible({ timeout: 10000 });

    // Находим строку с "Key To Delete" и нажимаем кнопку "Удалить"
    const keyRow = page.locator('[data-testid="passkeys-list"] div:has-text("Key To Delete")');
    await keyRow.locator('button:has-text("Удалить")').first().click();

    // Проверяем сообщение об успешном удалении
    await expect(page.locator('[data-testid="passkey-success"]')).toContainText("удален", { timeout: 10000 });

    // Проверяем, что удалённого ключа больше нет в списке (отображается заглушка пустого списка)
    await expect(page.locator('[data-testid="passkeys-empty"]')).toBeVisible({ timeout: 10000 });

    // Выходим из системы
    await page.click('button:has-text("Выйти")');
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible({ timeout: 10000 });

    // Проверяем отрицательный сценарий: попытка входа по удалённому Passkey завершается ошибкой
    await page.click('[data-testid="passkey-login-button"]');
    await expect(page.locator(".bg-red-50")).toBeVisible({ timeout: 10000 });
  });
});
