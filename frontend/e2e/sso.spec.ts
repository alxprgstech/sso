import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test.describe("ALXPRGS SSO End-to-End Suite", () => {
  test.beforeAll(() => {
    try {
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
          TEST_DATABASE_URL:
            process.env.TEST_DATABASE_URL ||
            "postgresql+psycopg://sso_test_user:sso_test_password@localhost:5433/alxprgs_sso_test",
        },
      });
    } catch (e) {
      console.error("E2E setup error:", e);
    }
  });
  test("01. Default Profile: Capabilities & Security Invariants UI", async ({ page }) => {
    // 1. Открываем главную страницу входа
    await page.goto("/");

    // Проверяем ключевые элементы страницы входа
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible();
    await expect(page.getByText("alxprgs.tech", { exact: false })).toBeVisible();

    // Проверяем отображение флагов отложенных возможностей (все 4 выключены по умолчанию)
    const policyBlock = page.locator("text=Политика безопасности (default-профиль)");
    await expect(policyBlock).toBeVisible();

    await expect(page.getByText("TOTP аутентификатор:")).toBeVisible();
    await expect(page.getByText("Passkey (WebAuthn):")).toBeVisible();
    await expect(page.getByText("Резервные коды:")).toBeVisible();

    // Парольный вход активен
    await expect(page.getByText("Парольный вход:")).toBeVisible();
    await expect(page.getByText("Активен (Argon2id)")).toBeVisible();
  });

  test("02. Admin Login, Dashboard, and Switch Registration Mode to Open", async ({ page }) => {
    await page.goto("/");

    // Вводим данные первого администратора Compose
    await page.fill('input[placeholder="user@alxprgs.tech"]', "compose_admin");
    await page.fill('input[type="password"]', "ComposeAdminPass2026!");
    await page.click('button[type="submit"]');

    // Ожидаем загрузки личного кабинета и отображения сессии
    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("header").getByText("compose_admin", { exact: true })).toBeVisible();
    await expect(page.locator("header").getByText("Admin", { exact: true })).toBeVisible();

    // Переходим в панель администрирования
    await page.click('button:has-text("Администрирование")');
    await expect(page.getByText("Административная панель")).toBeVisible();

    // Переключаемся на вкладку "Конфигурация"
    await page.click('button:has-text("Конфигурация")');
    await expect(page.getByText("Управление политикой самостоятельной регистрации")).toBeVisible();
    await expect(page.getByText("Закрыта (closed)")).toBeVisible();

    // Выбираем открытый режим
    await page.locator('input[value="open"]').check();

    // Вводим пароль администратора для подтверждения (re-authentication)
    await page.fill('input[placeholder*="Введите ваш пароль"]', "ComposeAdminPass2026!");

    // Сохраняем
    await page.click('button:has-text("Применить режим регистрации")');

    // Проверяем сообщение об успешном изменении
    await expect(
      page.getByText('Режим регистрации успешно изменён на "open"')
    ).toBeVisible({ timeout: 10000 });

    // Выходим из системы
    await page.click('button:has-text("Выйти")');
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible({ timeout: 10000 });
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

    await page.click('button:has-text("Зарегистрироваться")');

    // Проверяем сообщение об успешной регистрации
    await expect(
      page.getByText("Учётная запись успешно зарегистрирована!")
    ).toBeVisible({ timeout: 10000 });

    // Ожидаем автоматического перехода на форму входа или переходим явно
    await page.waitForTimeout(2500);
    if (await page.getByRole("heading", { name: "Регистрация в ALXPRGS SSO" }).isVisible()) {
      await page.click('button:has-text("Войти")');
    }

    // Входим созданным пользователем
    await page.fill('input[placeholder="user@alxprgs.tech"]', testUsername);
    await page.fill('input[type="password"]', testPassword);
    await page.click('button[type="submit"]');

    // Проверяем загрузку личного кабинета
    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("header").getByText(testUsername, { exact: true })).toBeVisible();

    // Проверяем RBAC: кнопка "Администрирование" НЕ должна отображаться для обычного пользователя
    await expect(page.getByRole("button", { name: "Администрирование" })).not.toBeVisible();

    // Выходим
    await page.click('button:has-text("Выйти")');
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible({ timeout: 10000 });
  });

  test("04. Restore Default Closed Registration Mode as Admin", async ({ page }) => {
    await page.goto("/");

    // Входим как администратор
    await page.fill('input[placeholder="user@alxprgs.tech"]', "compose_admin");
    await page.fill('input[type="password"]', "ComposeAdminPass2026!");
    await page.click('button[type="submit"]');

    await expect(page.getByText("Личный кабинет")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("header").getByText("compose_admin", { exact: true })).toBeVisible();

    // Переходим в админку -> Конфигурация
    await page.click('button:has-text("Администрирование")');
    await page.click('button:has-text("Конфигурация")');
    await expect(page.getByText("Управление политикой самостоятельной регистрации")).toBeVisible();
    await expect(page.getByText("Открыта (open)")).toBeVisible();

    // Возвращаем режим closed
    await page.locator('input[value="closed"]').check();
    await page.fill('input[placeholder*="Введите ваш пароль"]', "ComposeAdminPass2026!");
    await page.click('button:has-text("Применить режим регистрации")');

    await expect(
      page.getByText('Режим регистрации успешно изменён на "closed"')
    ).toBeVisible({ timeout: 10000 });

    // Выходим
    await page.click('button:has-text("Выйти")');
    await expect(page.getByRole("heading", { name: "Единая система входа ALXPRGS" })).toBeVisible({ timeout: 10000 });

    // Проверяем, что ссылка на регистрацию снова скрыта
    await expect(page.getByRole("button", { name: "Зарегистрироваться" })).not.toBeVisible();
  });
});
