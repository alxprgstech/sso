import { acceptDocumentsAfterLogin } from "./helpers/legal";
import { confirmSensitiveAction } from "./helpers/reauthentication";
import { prepareIndependentScenario } from "./helpers/prepare";
import { test, expect } from "@playwright/test";

test.describe("WebAuthn / Passkey Real Browser Lifecycle (G4-PASSKEY, QA-11)", () => {
  test.use({
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
  });

  test.beforeAll(async () => {
    // G6-PREFLIGHT: Проверка соответствия профиля enabled (Passkey=True) до запуска UI тестов
    const baseUrl = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173";
    const capsRes = await fetch(`${baseUrl}/api/v1/auth/capabilities`);
    if (!capsRes.ok) {
      throw new Error(
        `[G6-PREFLIGHT-FAIL] /api/v1/auth/capabilities вернул HTTP ${capsRes.status}`,
      );
    }
    const capsData = await capsRes.json();
    const caps = capsData?.capabilities ?? capsData;
    if (caps.passkey_enabled !== true) {
      throw new Error(
        `[G6-PREFLIGHT-FAIL] Enabled Passkey Suite требует passkey_enabled=true, ` +
          `но получено: ${JSON.stringify(caps)}. Процесс бэкенда запущен с неверным профилем! Остановка до таймаутов браузера!`,
      );
    }
  });

  test.beforeEach(prepareIndependentScenario);

  test("01. Enabled Profile Capabilities & Passkey Login Button Visibility", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Вход в ALXPRGS" }),
    ).toBeVisible();

    // Capabilities are read from the real server; no UI-only feature override.
    const response = await page.request.get("/api/v1/auth/capabilities");
    expect(response.ok()).toBe(true);
    expect((await response.json()).passkey_enabled).toBe(true);

    // Кнопка входа по Passkey отображается
    await expect(
      page.locator('[data-testid="passkey-login-button"]'),
    ).toBeVisible();
  });

  test("02. Real WebAuthn Registration of Multiple Credentials via CDP Virtual Authenticator", async ({
    page,
  }) => {
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
    await page.fill(
      'input[placeholder="user@alxprgs.tech"]',
      "e2e_passkey_multi_user",
    );
    await page.fill('input[type="password"]', "PasskeyE2E2026!");
    await page.click('button[type="submit"]');

    await acceptDocumentsAfterLogin(page);
    await page.goto("/account/security");
    await expect(page.getByText("Личный кабинет")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.locator('[data-testid="passkeys-section"]'),
    ).toBeVisible();

    // 3. Регистрируем первый Passkey: "MacBook TouchID" на первом аутентификаторе
    await page.fill('[data-testid="passkey-name-input"]', "MacBook TouchID");
    await page.click('[data-testid="register-passkey-button"]');

    await confirmSensitiveAction(page, "PasskeyE2E2026!", 2);

    // Проверяем сообщение об успехе и появление ключа в списке
    await expect(page.locator('[data-testid="passkey-success"]')).toBeVisible({
      timeout: 10000,
    });
    await expect(page.locator('[data-testid="passkeys-list"]')).toContainText(
      "MacBook TouchID",
    );

    // 4. Симулируем подключение второго физического аутентификатора (YubiKey 5C / usb)
    // Plug in the second device only AFTER a real assertion from the enrolled
    // first key. Reconnect that same first key for the verification action proof.
    let auth2: { authenticatorId: string } | undefined;
    const getFirstCredentials = () =>
      cdp.send("WebAuthn.getCredentials", {
        authenticatorId: auth1.authenticatorId,
      });
    let firstCredentials: Awaited<ReturnType<typeof getFirstCredentials>>;
    let secondCredentials: Awaited<ReturnType<typeof getFirstCredentials>>;

    await page.route(
      "**/api/v1/mfa/passkey/register/options",
      async (route) => {
        if (route.request().headers()["x-reauthentication"]) {
          firstCredentials = await getFirstCredentials();
          await cdp.send("WebAuthn.removeVirtualAuthenticator", {
            authenticatorId: auth1.authenticatorId,
          });
          auth2 = await cdp.send("WebAuthn.addVirtualAuthenticator", {
            options: {
              protocol: "ctap2",
              transport: "usb",
              hasResidentKey: true,
              hasUserVerification: true,
              isUserVerified: true,
            },
          });
          await route.continue();
          await page.unroute("**/api/v1/mfa/passkey/register/options");
          return;
        }
        await route.continue();
      },
    );
    await page.route("**/api/v1/mfa/passkey/register/verify", async (route) => {
      if (!route.request().headers()["x-reauthentication"]) {
        secondCredentials = await cdp.send("WebAuthn.getCredentials", {
          authenticatorId: auth2!.authenticatorId,
        });
        await cdp.send("WebAuthn.removeVirtualAuthenticator", {
          authenticatorId: auth2!.authenticatorId,
        });
        const reconnected = await cdp.send("WebAuthn.addVirtualAuthenticator", {
          options: {
            protocol: "ctap2",
            transport: "internal",
            hasResidentKey: true,
            hasUserVerification: true,
            isUserVerified: true,
          },
        });
        for (const credential of firstCredentials.credentials) {
          await cdp.send("WebAuthn.addCredential", {
            authenticatorId: reconnected.authenticatorId,
            credential,
          });
        }
        await route.continue();
        await page.unroute("**/api/v1/mfa/passkey/register/verify");
        return;
      }
      await route.continue();
    });

    // Регистрируем второй Passkey: "Yubikey 5C" (множественные credentials)
    await page.fill('[data-testid="passkey-name-input"]', "Yubikey 5C");
    await page.click('[data-testid="register-passkey-button"]');

    await confirmSensitiveAction(page, "PasskeyE2E2026!", 2);

    await expect(page.locator('[data-testid="passkey-success"]')).toBeVisible({
      timeout: 10000,
    });
    // Проверяем, что в списке отображаются ОБА зарегистрированных ключа
    await expect(page.locator('[data-testid="passkeys-list"]')).toContainText(
      "MacBook TouchID",
    );
    await expect(page.locator('[data-testid="passkeys-list"]')).toContainText(
      "Yubikey 5C",
    );

    auth2 = await cdp.send("WebAuthn.addVirtualAuthenticator", {
      options: {
        protocol: "ctap2",
        transport: "usb",
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
      },
    });
    for (const credential of secondCredentials!.credentials) {
      await cdp.send("WebAuthn.addCredential", {
        authenticatorId: auth2.authenticatorId,
        credential,
      });
    }

    // Проверяем в CDP, что второй виртуальный аутентификатор содержит сгенерированный FIDO2 credential
    expect(auth2).toBeDefined();
    const cdpCreds = await cdp.send("WebAuthn.getCredentials", {
      authenticatorId: auth2!.authenticatorId,
    });
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
    await page.fill(
      'input[placeholder="user@alxprgs.tech"]',
      "e2e_passkey_login_user",
    );
    await page.fill('input[type="password"]', "PasskeyE2E2026!");
    await page.click('button[type="submit"]');
    await acceptDocumentsAfterLogin(page);
    await page.goto("/account/security");
    await expect(page.getByText("Личный кабинет")).toBeVisible({
      timeout: 10000,
    });

    await page.fill('[data-testid="passkey-name-input"]', "Resident Login Key");
    await page.click('[data-testid="register-passkey-button"]');

    await confirmSensitiveAction(page, "PasskeyE2E2026!", 2);
    await expect(page.locator('[data-testid="passkey-success"]')).toBeVisible({
      timeout: 10000,
    });

    // Выходим из системы
    await page.click('button:has-text("Выйти")');
    await expect(
      page.getByRole("heading", { name: "Вход в ALXPRGS" }),
    ).toBeVisible({ timeout: 10000 });

    // Входим БЕЗ ввода пароля — нажимаем кнопку Passkey!
    await page.click('[data-testid="passkey-login-button"]');

    // Ожидаем входа и перехода в Личный кабинет под пользователем e2e_passkey_login_user
    await acceptDocumentsAfterLogin(page);
    await page.goto("/account/security");
    await expect(page.getByText("Личный кабинет")).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page
        .locator("header")
        .getByText("e2e_passkey_login_user", { exact: true }),
    ).toBeVisible();
  });

  test("04. Key Deletion and Verification that Deleted Key Fails Authentication", async ({
    page,
  }) => {
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
    await page.fill(
      'input[placeholder="user@alxprgs.tech"]',
      "e2e_passkey_delete_user",
    );
    await page.fill('input[type="password"]', "PasskeyE2E2026!");
    await page.click('button[type="submit"]');
    await acceptDocumentsAfterLogin(page);
    await page.goto("/account/security");
    await expect(page.getByText("Личный кабинет")).toBeVisible({
      timeout: 10000,
    });

    // Регистрируем временный ключ для последующего удаления
    await page.fill('[data-testid="passkey-name-input"]', "Key To Delete");
    await page.click('[data-testid="register-passkey-button"]');

    await confirmSensitiveAction(page, "PasskeyE2E2026!", 2);
    await expect(page.locator('[data-testid="passkey-success"]')).toBeVisible({
      timeout: 10000,
    });

    // Находим строку с "Key To Delete" и нажимаем кнопку "Удалить"
    const keyRow = page.locator(
      '[data-testid="passkeys-list"] div:has-text("Key To Delete")',
    );
    await keyRow.locator('button:has-text("Удалить")').first().click();
    await page
      .getByRole("dialog", { name: "Подтверждение действия" })
      .getByRole("button", { name: "Подтвердить", exact: true })
      .click();

    await confirmSensitiveAction(page, "PasskeyE2E2026!");

    // Проверяем сообщение об успешном удалении
    await expect(page.locator('[data-testid="passkey-success"]')).toContainText(
      "удален",
      { timeout: 10000 },
    );

    // Проверяем, что удалённого ключа больше нет в списке (отображается заглушка пустого списка)
    await expect(page.locator('[data-testid="passkeys-empty"]')).toBeVisible({
      timeout: 10000,
    });

    // Выходим из системы
    await page.click('button:has-text("Выйти")');
    await expect(
      page.getByRole("heading", { name: "Вход в ALXPRGS" }),
    ).toBeVisible({ timeout: 10000 });

    // Проверяем отрицательный сценарий: попытка входа по удалённому Passkey завершается ошибкой
    await page.click('[data-testid="passkey-login-button"]');
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 10000 });
  });
});
