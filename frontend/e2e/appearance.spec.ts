// Browser-hosted UI unit regression with explicitly mocked API contracts. Authentication/PG/MFA are
// covered by privacy.spec.ts and the existing real-server suites, not these fixtures.
import { test, expect, type Page } from "@playwright/test";
import type { UserProfile } from "../src/types/api";

const themeKey = "alxprgs.ui.theme.v1";
const profile: UserProfile = { id: "ui-fixture", username: "ui_fixture", email: "ui@example.test", is_active: true,
  is_superuser: true, email_verified: true, roles: ["admin"], has_totp: false, has_passkey: false,
  created_at: "2026-01-01T00:00:00Z", legal_acceptance_required: false, deletion_pending: false, session_purpose: "full" };
const documents = { documents: ["privacy", "terms", "cookies", "data-consent"].map(id => ({ id, path: `/${id}`, title: `Документ ${id}`, version: "ui-version", status: "draft", paragraphs: ["Текст тестового документа."] })), required_versions: { terms: "ui-version", "data-consent": "ui-version" } };

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    let violations = 0;
    document.addEventListener("DOMContentLoaded", () => { document.documentElement.dataset.cspViolations = String(violations); }, { once: true });
    document.addEventListener("securitypolicyviolation", () => {
      violations += 1;
      if (document.documentElement) document.documentElement.dataset.cspViolations = String(violations);
    });
  });
});
test.afterEach(async ({ page }) => {
  await expect(page.locator("html")).toHaveAttribute("data-csp-violations", "0");
});

async function mockUI(page: Page, user: UserProfile | null = null, enabled = false) {
  const fixtures: Record<string, { status?: number; json: unknown }> = {
    "GET /api/v1/auth/capabilities": { json: { totp_enabled: enabled, passkey_enabled: enabled, recovery_codes_enabled: enabled, email_verification_enabled: true, require_verified_email: false, registration_mode: "open" } },
    "GET /api/v1/auth/telemetry-config": { json: { enabled: false, replay_enabled: false, environment: "production" } },
    "GET /api/v1/legal/documents": { json: documents },
    "GET /api/v1/auth/me": { status: user ? 200 : 401, json: user ?? { detail: "Not authenticated" } },
    "GET /api/v1/auth/sessions": { json: [] },
    "GET /api/v1/mfa/passkey/credentials": { json: [] },
    "GET /api/v1/admin/users": { json: [] },
    "GET /api/v1/auth/account-deletion": { json: { pending: false, requested_at: null, scheduled_for: null, request_allowed_at: null } },
    "POST /api/v1/auth/account-deletion/reauthenticate": { json: { authorization: "synthetic-ui-proof", factor_required: false, expires_at: "2099-01-01T00:00:00Z" } },
    "POST /api/v1/auth/account-deletion": { status: 403, json: { detail: { error: "forbidden", detail: "Запрещено удалять, блокировать или лишать прав последнего активного администратора системы" } } },
    "POST /api/v1/mfa/totp/setup": { json: { secret: "SYNTHETICUIQR", otpauth_url: "otpauth://totp/UI?secret=SYNTHETICUIQR&issuer=UI" } }, // pragma: allowlist secret -- synthetic UI QR fixture
  };
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    const fixture = fixtures[key] ?? { status: 500, json: { detail: `Unconfigured UI fixture: ${key}` } };
    await route.fulfill({ status: fixture.status ?? 200, json: fixture.json });
  });
}

async function bannerAtBottom(page: Page) {
  await expect(page.getByRole("region", { name: "Cookies и диагностика" })).toBeVisible();
  const geometry = await page.evaluate(() => {
    const banner = document.querySelector(".cookie-banner")!.getBoundingClientRect();
    const content = document.querySelector(".app-scroll")!.getBoundingClientRect();
    return { bottom: banner.bottom, height: banner.height, top: banner.top, contentBottom: content.bottom,
      viewport: innerHeight, fitsWidth: document.documentElement.scrollWidth <= innerWidth };
  });
  expect(Math.abs(geometry.bottom - geometry.viewport)).toBeLessThan(2);
  expect(Math.abs(geometry.viewport - geometry.contentBottom - geometry.height)).toBeLessThan(2);
  expect(geometry.contentBottom).toBeLessThanOrEqual(geometry.top + 1);
  expect(geometry.fitsWidth).toBe(true);
}

test("cookies layout remains consistent through repeated resizes without ResizeObserver", async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(window, "ResizeObserver", { value: undefined }); });
  await mockUI(page);
  await page.goto("/login");
  await bannerAtBottom(page);
  for (const width of [390, 1280, 390, 768, 320, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    await bannerAtBottom(page);
  }
  await page.getByRole("button", { name: "Настроить", exact: true }).click();
  await bannerAtBottom(page);
  await page.setViewportSize({ width: 390, height: 600 });
  await bannerAtBottom(page);
  await page.getByRole("button", { name: "Только необходимые" }).click();
  await expect(page.getByRole("region", { name: "Cookies и диагностика" })).toHaveCount(0);
  const bottom = await page.locator(".app-scroll").evaluate(element => element.getBoundingClientRect().bottom);
  expect(Math.abs(bottom - page.viewportSize()!.height)).toBeLessThan(2);
});

test("system theme, explicit choice, reload and cross-tab changes", async ({ page, context }) => {
  await mockUI(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/login");
  const control = page.getByRole("combobox", { name: "Тема оформления" });
  await expect(control).toHaveValue("system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await control.selectOption("dark");
  await page.reload();
  await expect(control).toHaveValue("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(key => localStorage.getItem(key), themeKey)).toBe("dark");
  const second = await context.newPage(); await mockUI(second);
  await second.goto("/privacy");
  await expect(second.getByRole("combobox", { name: "Тема оформления" })).toHaveValue("dark");
  await second.getByRole("combobox", { name: "Тема оформления" }).selectOption("light");
  await expect(control).toHaveValue("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await second.evaluate(key => localStorage.removeItem(key), themeKey);
  await expect(control).toHaveValue("system");
  await second.close();
});

test("theme still works when browser storage is unavailable", async ({ page }) => {
  await mockUI(page);
  await page.addInitScript(() => {
    Object.defineProperty(Storage.prototype, "getItem", { value: () => { throw new DOMException("Unavailable"); } });
    Object.defineProperty(Storage.prototype, "setItem", { value: () => { throw new DOMException("Unavailable"); } });
  });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/register");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("combobox", { name: "Тема оформления" }).selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Только необходимые" }).click();
  await expect(page.getByRole("status")).toContainText("браузерное хранение недоступно");
});

test("theme selector is reachable and operable with a keyboard", async ({ page }) => {
  await mockUI(page); await page.goto("/login");
  await page.keyboard.press("Tab"); await expect(page.getByRole("link", { name: "К основному содержимому" })).toBeFocused();
  await page.keyboard.press("Tab");
  const control = page.getByRole("combobox", { name: "Тема оформления" });
  await expect(control).toBeFocused();
  await page.keyboard.press("ArrowDown"); await expect(control).toHaveValue("light");
  await page.keyboard.press("ArrowDown"); await expect(control).toHaveValue("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("the head script applies stored dark theme before the React entry runs", async ({ page }) => {
  await page.addInitScript(key => localStorage.setItem(key, "dark"), themeKey);
  // No React: the self-hosted classic script must be enough for first paint.
  await page.route(/\/(?:src\/main\.tsx|assets\/index-[^/]+\.js)(?:\?.*)?$/, route => route.abort());
  await page.goto("/privacy");
  await expect(page.locator("#root")).toBeEmpty();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.locator("html").evaluate(element => getComputedStyle(element).colorScheme)).toBe("dark");
});

for (const theme of ["light", "dark"] as const) {
  test(`palette text and focus contrast: ${theme}`, async ({ page }) => {
    await mockUI(page); await page.goto("/cookies");
    await page.getByRole("combobox", { name: "Тема оформления" }).selectOption(theme);
    const ratios = await page.evaluate(() => {
      const css = getComputedStyle(document.documentElement);
      const luminance = (variable: string) => {
        const hex = css.getPropertyValue(variable).trim().slice(1);
        const channels = [0, 2, 4].map(index => parseInt(hex.slice(index, index + 2), 16) / 255)
          .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
        return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
      };
      const contrast = (fg: string, bg: string) => {
        const a = luminance(fg), b = luminance(bg); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      };
      const text = ["--text-main", "--text-secondary", "--text-muted", "--text-subtle", "--link"]
        .flatMap(fg => ["--bg-main", "--surface"].map(bg => ({ pair: `${fg}/${bg}`, ratio: contrast(fg, bg) })));
      for (const prefix of ["info", "danger", "success", "warning", "purple"]) text.push({ pair: prefix, ratio: contrast(`--${prefix}-text`, `--${prefix}-bg`) });
      return { text, focus: contrast("--focus", "--surface"), border: contrast("--control-border", "--surface") };
    });
    for (const sample of ratios.text) expect(sample.ratio, sample.pair).toBeGreaterThanOrEqual(4.5);
    expect(ratios.focus).toBeGreaterThanOrEqual(3); expect(ratios.border).toBeGreaterThanOrEqual(3);
  });
  for (const viewport of [{ width: 1908, height: 901 }, { width: 390, height: 844 }]) {
    test(`mouse password focus, labels and typing: ${theme} ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport); await mockUI(page);
      await page.addInitScript(({ key, value }) => localStorage.setItem(key, value), { key: themeKey, value: theme });
      for (const path of ["/login", "/register"]) {
        await page.goto(path);
        const fields = page.locator('input[type="password"]'); await expect(fields.first()).toBeVisible();
        for (const field of await fields.all()) {
          await field.click(); await expect(field).toBeFocused();
          await page.keyboard.type("SyntheticUiInput"); await expect(field).toHaveValue("SyntheticUiInput");
          const id = await field.getAttribute("id");
          await page.locator(`label[for="${id}"]`).click(); await expect(field).toBeFocused();
          expect(await field.evaluate(e => getComputedStyle(e).outlineStyle)).not.toBe("none");
        }
        await bannerAtBottom(page);
      }
    });

    test(`consent actions and cookies layout: ${theme} ${viewport.width}`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport); await mockUI(page, { ...profile, legal_acceptance_required: true });
      await page.goto("/");
      await page.getByRole("combobox", { name: "Тема оформления" }).selectOption(theme);
      await expect(page.getByRole("heading", { name: "Подтвердите документы" })).toBeVisible();
      const deletion = page.getByRole("link", { name: "Удаление аккаунта", exact: true });
      const logout = page.getByRole("button", { name: "Выйти", exact: true });
      const style = (element: Element) => { const css = getComputedStyle(element); return [css.height, css.padding, css.border, css.backgroundColor, css.color, css.textDecorationLine]; };
      expect(await deletion.evaluate(style)).toEqual(await logout.evaluate(style));
      await bannerAtBottom(page);
      await page.screenshot({ path: testInfo.outputPath(`consent-${theme}-${viewport.width}.png`) });
      const settingsTrigger = page.getByRole("button", { name: "Настройки cookies" });
      await settingsTrigger.click();
      await expect(page.getByRole("checkbox", { name: /Диагностика ошибок/ })).toBeFocused();
      await bannerAtBottom(page);
      await page.getByRole("button", { name: "Сохранить выбор" }).click();
      await expect(settingsTrigger).toBeFocused();
      await expect(page.locator(".cookie-banner")).toHaveCount(0);
      expect(await page.locator(".app-shell").evaluate(element => getComputedStyle(element).paddingBottom)).toBe("0px");
    });
  }

  test(`last administrator refusal is a prominent alert: ${theme}`, async ({ page }) => {
    await mockUI(page, profile); await page.goto("/account-deletion");
    await page.getByRole("combobox", { name: "Тема оформления" }).selectOption(theme);
    await page.getByLabel("Текущий пароль").fill("SyntheticUiInput");
    await page.getByRole("button", { name: "Подтвердить доступ для удаления" }).click();
    await page.getByRole("checkbox", { name: /Понимаю последствия/ }).check();
    await page.getByRole("button", { name: "Запланировать удаление" }).click();
    const alert = page.getByRole("alert");
    await expect(alert).toContainText("Запрещено удалять, блокировать или лишать прав последнего активного администратора системы");
    await expect(alert.locator("strong")).toBeVisible();
    expect(await alert.evaluate(element => getComputedStyle(element).borderLeftWidth)).toBe("4px");
    expect(await alert.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe(await page.locator("body").evaluate(element => getComputedStyle(element).backgroundColor));
  });

  test(`dashboard, QR and modal surfaces: ${theme}`, async ({ page }) => {
    await mockUI(page, profile, true); await page.goto("/");
    await page.getByRole("combobox", { name: "Тема оформления" }).selectOption(theme);
    await page.getByRole("button", { name: /Настроить TOTP/ }).click();
    const qr = page.getByRole("img", { name: "QR-код для подключения ALXPRGS SSO" });
    await expect(qr).toBeVisible();
    expect(await qr.locator("..").evaluate(element => getComputedStyle(element).backgroundColor)).toBe("rgb(255, 255, 255)");
    await page.getByRole("button", { name: "Изменить пароль" }).click();
    const dialog = page.getByRole("dialog", { name: "Смена пароля" });
    await expect(dialog).toBeVisible();
    expect(await dialog.evaluate(element => getComputedStyle(element).backgroundColor)).toBe(theme === "dark" ? "rgb(17, 28, 47)" : "rgb(255, 255, 255)");
    await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0);
    await page.getByRole("button", { name: "Администрирование" }).click();
    await page.getByRole("button", { name: /Добавить пользователя/ }).click();
    const adminDialog = page.getByRole("dialog", { name: "Новый пользователь" });
    await expect(adminDialog).toBeVisible(); await page.keyboard.press("Escape"); await expect(adminDialog).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await bannerAtBottom(page);
    expect(await page.locator(".app-scroll").evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.getByRole("button", { name: "Личный кабинет", exact: true }).click();
  });
}
