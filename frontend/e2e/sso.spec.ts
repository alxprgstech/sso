import { acceptDocumentsAfterLogin } from "./helpers/legal";
import { confirmSensitiveAction } from "./helpers/reauthentication";
import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test.describe("ALXPRGS SSO End-to-End Suite", () => {
  test.use({ baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173" });

  test.beforeAll(async () => {
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

    // G6-PREFLIGHT: Проверка соответствия профиля default-off до запуска UI тестов
    const baseUrl = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173";
    const capsRes = await fetch(`${baseUrl}/api/v1/auth/capabilities`);
    if (!capsRes.ok) {
      throw new Error(`[G6-PREFLIGHT-FAIL] /api/v1/auth/capabilities вернул HTTP ${capsRes.status}`);
    }
    const capsData = await capsRes.json();
    const caps = capsData?.capabilities ?? capsData;
    if (caps.passkey_enabled !== false || caps.totp_enabled !== false) {
      throw new Error(
        `[G6-PREFLIGHT-FAIL] Default-off SSO Suite требует отключенных флагов (false), ` +
        `но получено: ${JSON.stringify(caps)}. Остановка до таймаутов браузера!`
      );
    }
  });
  test("01. Default Profile: Capabilities & Security Invariants UI", async ({ page }) => {
    // 1. Открываем главную страницу входа
    await page.goto("/");

    // Проверяем ключевые элементы страницы входа
    await expect(page.getByRole("heading", { name: "Вход в ALXPRGS" })).toBeVisible();
    const caps=await (await page.request.get("/api/v1/auth/capabilities")).json();
    expect(caps.totp_enabled).toBe(false); expect(caps.passkey_enabled).toBe(false); expect(caps.recovery_codes_enabled).toBe(false);
    await expect(page.getByTestId("passkey-login-button")).toHaveCount(0);
    await expect(page.getByLabel("Пароль",{exact:true})).toBeEditable();
  });

  test("02. Admin Login, Dashboard, and Switch Registration Mode to Open", async ({ page }) => {
    await page.goto("/");

    // Вводим данные первого администратора Compose
    await page.fill('input[placeholder="user@alxprgs.tech"]', "compose_admin");
    await page.fill('input[type="password"]', "ComposeAdminPass2026!");
    await page.click('button[type="submit"]');

    // Ожидаем загрузки личного кабинета и отображения сессии
    await acceptDocumentsAfterLogin(page);
    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("header").getByText("compose_admin", { exact: true })).toBeVisible();
    await expect(page.locator("header").getByText("Admin", { exact: true })).toBeVisible();

    // Переходим в панель администрирования
    await page.click('a:has-text("Администрирование")');
    await expect(page.getByText("Административная панель")).toBeVisible();

    // Переключаемся на вкладку "Конфигурация"
    await page.click('a:has-text("Конфигурация")');
    await expect(page.getByText("Управление политикой самостоятельной регистрации")).toBeVisible();
    await expect(page.getByText("Закрыта (closed)")).toBeVisible();

    // Выбираем открытый режим
    await page.locator('input[value="open"]').check();

    // Вводим пароль администратора для подтверждения (re-authentication)
    await page.fill('input[placeholder*="Введите ваш пароль"]', "ComposeAdminPass2026!");

    // Сохраняем
    await page.click('button:has-text("Применить режим регистрации")');
    await confirmSensitiveAction(page, "ComposeAdminPass2026!");

    // Проверяем сообщение об успешном изменении
    await expect(
      page.getByText('Режим регистрации успешно изменён на "open"')
    ).toBeVisible({ timeout: 10000 });

    // Выходим из системы
    await page.click('button:has-text("Выйти")');
    await expect(page.getByRole("heading", { name: "Вход в ALXPRGS" })).toBeVisible({ timeout: 10000 });
  });

  test("03. Open Mode: Self-Registration of New User and Standard User Access", async ({ page }) => {
    await page.goto("/");

    // Ссылка на регистрацию теперь должна отображаться
    const registerLink = page.getByRole("button", { name: "Зарегистрироваться" });
    await expect(registerLink).toBeVisible({ timeout: 5000 });
    await registerLink.click();

    // Проверяем форму регистрации
    await expect(page.getByRole("heading", { name: "Регистрация в ALXPRGS SSO" })).toBeVisible();

    // Заполняем форму
    const uniqueId = Date.now().toString().slice(-6);
    const testUsername = `pw_user_${uniqueId}`;
    const testEmail = `pw_user_${uniqueId}@alxprgs.tech`;
    const testPassword = "UserPassword2026!";

    await page.fill('input[placeholder="alex_ivanov"]', testUsername);
    await page.fill('input[placeholder="alex@alxprgs.tech"]', testEmail);

    const passwordInputs = page.locator('input[type="password"]');
    await passwordInputs.nth(0).fill(testPassword);
    await passwordInputs.nth(1).fill(testPassword);

    await page.getByRole("checkbox").nth(0).check();
    await page.getByRole("checkbox").nth(1).check();
    await page.click('button:has-text("Зарегистрироваться")');

    // Код берётся из локального SMTP-приёмника CI, без подмены проверки на backend.
    await expect(page.getByLabel("Код из письма")).toBeVisible({ timeout: 10000 });
    const mailboxPath = process.env.E2E_MAILBOX_PATH;
    if (!mailboxPath) throw new Error("E2E_MAILBOX_PATH is required");
    let emailCode = "";
    await expect.poll(() => {
      const entries = fs.readFileSync(mailboxPath, "utf8").trim().split("\n").filter(Boolean);
      const message = entries.map((line) => JSON.parse(line) as { to: string[]; code: string })
        .find((entry) => entry.to.includes(testEmail));
      emailCode = message?.code ?? "";
      return emailCode;
    }, { timeout: 10000 }).toMatch(/^\d{6}$/);
    await page.getByLabel("Код из письма").fill(emailCode);
    await page.getByRole("button", { name: "Подтвердить адрес" }).click();
    await expect(page.getByText("Адрес подтверждён, учётная запись создана. Теперь можно войти.")).toBeVisible();
    await page.getByRole("button", { name: "Перейти ко входу" }).click();
    const loginHeader = page.getByRole("heading", { name: "Вход в ALXPRGS" });
    await expect(loginHeader).toBeVisible();

    // Входим созданным пользователем
    await page.fill('input[placeholder="user@alxprgs.tech"]', testUsername);
    await page.fill('input[type="password"]', testPassword);
    await page.click('button[type="submit"]');

    // Проверяем загрузку личного кабинета
    await acceptDocumentsAfterLogin(page);
    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("header").getByText(testUsername, { exact: true })).toBeVisible();

    // Проверяем RBAC: кнопка "Администрирование" НЕ должна отображаться для обычного пользователя
    await expect(page.getByRole("link", { name: "Администрирование" })).not.toBeVisible();

    // Выходим
    await page.click('button:has-text("Выйти")');
    await expect(page.getByRole("heading", { name: "Вход в ALXPRGS" })).toBeVisible({ timeout: 10000 });
  });

  test("04. Restore Default Closed Registration Mode as Admin", async ({ page }) => {
    await page.goto("/");

    // Входим как администратор
    await page.fill('input[placeholder="user@alxprgs.tech"]', "compose_admin");
    await page.fill('input[type="password"]', "ComposeAdminPass2026!");
    await page.click('button[type="submit"]');

    await acceptDocumentsAfterLogin(page);
    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("header").getByText("compose_admin", { exact: true })).toBeVisible();

    // Переходим в админку -> Конфигурация
    await page.click('a:has-text("Администрирование")');
    await page.click('a:has-text("Конфигурация")');
    await expect(page.getByText("Управление политикой самостоятельной регистрации")).toBeVisible();
    await expect(page.getByText("Открыта (open)")).toBeVisible();

    // Возвращаем режим closed
    await page.locator('input[value="closed"]').check();
    await page.fill('input[placeholder*="Введите ваш пароль"]', "ComposeAdminPass2026!");
    await page.click('button:has-text("Применить режим регистрации")');
    await confirmSensitiveAction(page, "ComposeAdminPass2026!");

    await expect(
      page.getByText('Режим регистрации успешно изменён на "closed"')
    ).toBeVisible({ timeout: 10000 });

    // Выходим
    await page.click('button:has-text("Выйти")');
    await expect(page.getByRole("heading", { name: "Вход в ALXPRGS" })).toBeVisible({ timeout: 10000 });

    // Проверяем, что ссылка на регистрацию снова скрыта
    await expect(page.getByRole("button", { name: "Зарегистрироваться" })).not.toBeVisible();
  });
});
