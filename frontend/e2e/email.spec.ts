import { acceptDocumentsAfterLogin } from "./helpers/legal";
import { test, expect, type Page } from "@playwright/test";
import { createMailbox, waitForVerification } from "./helpers/testmail";

const adminPassword = "ComposeAdminPass2026!";
const userPassword = "EmailBrowserFixture2026!";

async function login(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByPlaceholder("user@alxprgs.tech").fill(username);
  await page.locator('input[type="password"]').fill(password);
  await page.locator('button[type="submit"]').click();
  await acceptDocumentsAfterLogin(page);
  await expect(page.getByText("Личный кабинет")).toBeVisible();
}

async function registrationMode(page: Page, mode: "open" | "closed") {
  await login(page, "compose_admin", adminPassword);
  await page.getByRole("link", { name: "Администрирование", exact: true }).click();
  await page.getByRole("link", { name: "Конфигурация", exact: true }).click();
  await page.locator(`input[value="${mode}"]`).check();
  await page.getByPlaceholder("Введите ваш пароль", { exact: false }).fill(adminPassword);
  await page.getByRole("button", { name: "Применить режим регистрации" }).click();
  await expect(page.getByText(`Режим регистрации успешно изменён на "${mode}"`)).toBeVisible();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
}

for (const mode of ["code", "link"] as const) {
  test(`Registration through delivered email ${mode}`, async ({ page, browser }, testInfo) => {
    const adminContext = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
    const adminPage = await adminContext.newPage();
    try {
      await registrationMode(adminPage, "open");
      const mailbox = await createMailbox(`${testInfo.testId}|${testInfo.workerIndex}|${testInfo.retry}`);
      const username = `email_${mailbox.mailbox.tag.slice(-20)}`;
      await page.goto("/register");
      await page.getByPlaceholder("alex_ivanov").fill(username);
      await page.getByPlaceholder("alex@alxprgs.tech").fill(mailbox.address);
      const passwords = page.locator('input[type="password"]');
      await passwords.nth(0).fill(userPassword);
      await passwords.nth(1).fill(userPassword);
      await page.getByRole("checkbox").nth(0).check();
      await page.getByRole("checkbox").nth(1).check();
      await page.getByRole("button", { name: "Зарегистрироваться", exact: true }).click();
      await expect(page.getByLabel("Код из письма")).toBeVisible();
      const verification = await waitForVerification(mailbox, username);
      if (mode === "code") {
        await page.getByLabel("Код из письма").fill(verification.code);
        await page.getByRole("button", { name: "Подтвердить адрес", exact: true }).click();
        await expect(page.getByText("Адрес подтверждён, учётная запись создана. Теперь можно войти.")).toBeVisible();
      } else {
        // The helper has already checked exact origin/path/mode before navigation.
        await page.goto(verification.link);
        await page.getByRole("button", { name: "Подтвердить адрес", exact: true }).click();
        await expect(page.getByRole("status")).toHaveText("Адрес подтверждён. Теперь можно войти в систему.");
      }
      await login(page, username, userPassword);
      await expect(page.locator("header").getByText(username, { exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "Администрирование", exact: true })).toHaveCount(0);
    } finally {
      try { await registrationMode(adminPage, "closed"); }
      finally { await adminContext.close(); }
    }
  });
}
