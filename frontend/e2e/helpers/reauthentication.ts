import { expect, type Page } from "@playwright/test";

// Exercise the actual action/session/body-bound server proof. No injected proof
// or UI interception: password and CDP-backed verified assertion reach the API.
export async function confirmSensitiveAction(page: Page, password: string, count = 1) {
  for (let index = 0; index < count; index++) {
    const dialog = page.getByRole("dialog", { name: "Подтверждение чувствительной операции" });
    await expect(dialog.getByLabel("Текущий пароль")).toBeVisible();
    await dialog.getByLabel("Текущий пароль").fill(password);
    const started = page.waitForResponse(response => response.url().endsWith("/api/v1/auth/reauthentication") && response.request().method() === "POST");
    await dialog.getByRole("button", { name: "Подтвердить", exact: true }).click();
    const response = await started;
    expect(response.status()).toBe(200);
    const proof = await response.json();
    if (proof.factor_required) {
      await dialog.getByLabel("Второй фактор").selectOption("passkey");
      const verified = page.waitForResponse(response => response.url().endsWith("/api/v1/auth/reauthentication/factor") && response.request().method() === "POST");
      await dialog.getByRole("button", { name: "Подтвердить", exact: true }).click();
      expect((await verified).status()).toBe(200);
    }
  }
}
