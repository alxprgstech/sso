import { expect, type Page } from "@playwright/test";

/** Explicit UI acceptance for existing synthetic accounts; never changes capabilities. */
export async function acceptDocumentsAfterLogin(page: Page) {
  await expect(page.getByRole("heading", {name:"Подтвердите документы"}).or(page.getByRole("link", {name:"Личный кабинет", exact:true}))).toBeVisible();
  if (await page.getByRole("heading", {name:"Подтвердите документы"}).isVisible()) {
    await page.getByRole("checkbox").nth(0).check();
    await page.getByRole("checkbox").nth(1).check();
    await page.getByRole("button", {name:"Подтвердить и продолжить"}).click();
  }
}
