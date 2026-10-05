// Browser-hosted UI unit regression with explicitly mocked API contracts. Authentication/PG/MFA are
// covered by privacy.spec.ts and the existing real-server suites, not these fixtures.
import AxeBuilder from "@axe-core/playwright";
import { test, expect, type Page } from "@playwright/test";
import type { UserProfile } from "../src/types/api";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const themeKey = "alxprgs.ui.theme.v1";
const brandManifest = JSON.parse(
  readFileSync(
    new URL("../public/brand/source-manifest.json", import.meta.url),
    "utf8",
  ),
) as {
  repository: string;
  commit: string;
  files: Record<string, { sha256: string; bytes: number }>;
};
const profile: UserProfile = {
  id: "ui-fixture",
  username: "ui_fixture",
  email: "ui@example.test",
  is_active: true,
  is_superuser: true,
  email_verified: true,
  roles: ["admin"],
  has_totp: false,
  has_passkey: false,
  created_at: "2026-01-01T00:00:00Z",
  legal_acceptance_required: false,
  deletion_pending: false,
  session_purpose: "full",
};
const documents = {
  documents: ["privacy", "terms", "cookies", "data-consent"].map((id) => ({
    id,
    path: `/${id}`,
    title: `Документ ${id}`,
    version: "ui-version",
    status: "draft",
    paragraphs: ["Текст тестового документа."],
  })),
  required_versions: { terms: "ui-version", "data-consent": "ui-version" },
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    let violations = 0;
    document.addEventListener(
      "DOMContentLoaded",
      () => {
        document.documentElement.dataset.cspViolations = String(violations);
      },
      { once: true },
    );
    document.addEventListener("securitypolicyviolation", () => {
      violations += 1;
      if (document.documentElement)
        document.documentElement.dataset.cspViolations = String(violations);
    });
  });
});
test.afterEach(async ({ page }) => {
  await expect(page.locator("html")).toHaveAttribute(
    "data-csp-violations",
    "0",
  );
});

async function mockUI(
  page: Page,
  user: UserProfile | null = null,
  enabled = false,
  overrides: Record<string, { status?: number; json: unknown }> = {},
) {
  const fixtures: Record<string, { status?: number; json: unknown }> = {
    "GET /api/v1/auth/capabilities": {
      json: {
        totp_enabled: enabled,
        passkey_enabled: enabled,
        recovery_codes_enabled: enabled,
        email_verification_enabled: true,
        require_verified_email: false,
        registration_mode: "open",
      },
    },
    "GET /api/v1/auth/telemetry-config": {
      json: {
        enabled: false,
        replay_enabled: false,
        environment: "production",
      },
    },
    "GET /api/v1/legal/documents": { json: documents },
    "GET /api/v1/auth/me": {
      status: user ? 200 : 401,
      json: user ?? { detail: "Not authenticated" },
    },
    "GET /api/v1/auth/sessions": { json: [] },
    "GET /api/v1/mfa/passkey/credentials": { json: [] },
    "GET /api/v1/admin/users": { json: [] },
    "GET /api/v1/admin/system/status": {
      json: {
        bootstrap_completed: true,
        bootstrap_completed_at: null,
        registration_mode: "closed",
        total_users: 1,
        total_active_admins: 1,
      },
    },
    "GET /api/v1/admin/audit": { json: [] },
    "GET /api/v1/auth/account-deletion": {
      json: {
        pending: false,
        requested_at: null,
        scheduled_for: null,
        request_allowed_at: null,
      },
    },
    "POST /api/v1/auth/account-deletion/reauthenticate": {
      json: {
        authorization: "synthetic-ui-proof",
        factor_required: false,
        expires_at: "2099-01-01T00:00:00Z",
      },
    },
    "POST /api/v1/auth/account-deletion": {
      status: 403,
      json: {
        detail: {
          error: "forbidden",
          detail:
            "Запрещено удалять, блокировать или лишать прав последнего активного администратора системы",
        },
      },
    },
    "POST /api/v1/mfa/totp/setup": {
      json: {
        secret: "SYNTHETICUIQR", // pragma: allowlist secret -- synthetic UI fixture, not a working TOTP secret
        otpauth_url: "otpauth://totp/UI?secret=SYNTHETICUIQR&issuer=UI",
      },
    }, // pragma: allowlist secret -- synthetic UI QR fixture
  };
  Object.assign(fixtures, overrides);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    const fixture = fixtures[key] ?? {
      status: 500,
      json: { detail: `Unconfigured UI fixture: ${key}` },
    };
    await route.fulfill({ status: fixture.status ?? 200, json: fixture.json });
  });
}

async function bannerAtBottom(page: Page) {
  await expect(
    page.getByRole("region", { name: "Cookies и диагностика" }),
  ).toBeVisible();
  const geometry = await page.evaluate(() => {
    const banner = document
      .querySelector(".cookie-banner")!
      .getBoundingClientRect();
    const content = document
      .querySelector(".app-scroll")!
      .getBoundingClientRect();
    return {
      bottom: banner.bottom,
      height: banner.height,
      top: banner.top,
      contentBottom: content.bottom,
      viewport: innerHeight,
      fitsWidth: document.documentElement.scrollWidth <= innerWidth,
    };
  });
  expect(Math.abs(geometry.bottom - geometry.viewport)).toBeLessThan(2);
  expect(
    Math.abs(geometry.viewport - geometry.contentBottom - geometry.height),
  ).toBeLessThan(2);
  expect(geometry.contentBottom).toBeLessThanOrEqual(geometry.top + 1);
  expect(geometry.fitsWidth).toBe(true);
}

test("cookies layout remains consistent through repeated resizes without ResizeObserver", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "ResizeObserver", { value: undefined });
  });
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
  await expect(
    page.getByRole("region", { name: "Cookies и диагностика" }),
  ).toHaveCount(0);
  const bottom = await page
    .locator(".app-scroll")
    .evaluate((element) => element.getBoundingClientRect().bottom);
  expect(Math.abs(bottom - page.viewportSize()!.height)).toBeLessThan(2);
});

test("system theme, explicit choice, reload and cross-tab changes", async ({
  page,
  context,
}) => {
  await mockUI(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/login");
  const control = page.getByRole("combobox", { name: "Тема оформления" });
  await expect(control).toHaveValue("dark");
  await control.selectOption("system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await control.selectOption("dark");
  await page.reload();
  await expect(control).toHaveValue("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(
    await page.evaluate((key) => localStorage.getItem(key), themeKey),
  ).toBe("dark");
  const second = await context.newPage();
  await mockUI(second);
  await second.goto("/privacy");
  await expect(
    second.getByRole("combobox", { name: "Тема оформления" }),
  ).toHaveValue("dark");
  await second
    .getByRole("combobox", { name: "Тема оформления" })
    .selectOption("light");
  await expect(control).toHaveValue("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await second.evaluate((key) => localStorage.removeItem(key), themeKey);
  await expect(control).toHaveValue("dark");
  await second.close();
});

test("theme still works when browser storage is unavailable", async ({
  page,
}) => {
  await mockUI(page);
  await page.addInitScript(() => {
    Object.defineProperty(Storage.prototype, "getItem", {
      value: () => {
        throw new DOMException("Unavailable");
      },
    });
    Object.defineProperty(Storage.prototype, "setItem", {
      value: () => {
        throw new DOMException("Unavailable");
      },
    });
  });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/register");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page
    .getByRole("combobox", { name: "Тема оформления" })
    .selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Только необходимые" }).click();
  await expect(page.getByRole("status")).toContainText(
    "браузерное хранение недоступно",
  );
});

test("theme selector is reachable and operable with a keyboard", async ({
  page,
}) => {
  await mockUI(page);
  await page.goto("/login");
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "К основному содержимому" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  const control = page.getByRole("combobox", { name: "Тема оформления" });
  await expect(control).toBeFocused();
  await control.selectOption("system");
  await page.keyboard.press("ArrowDown");
  await expect(control).toHaveValue("light");
  await page.keyboard.press("ArrowDown");
  await expect(control).toHaveValue("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("the head script applies stored dark theme before the React entry runs", async ({
  page,
}) => {
  await page.addInitScript(
    (key) => localStorage.setItem(key, "dark"),
    themeKey,
  );
  // No React: the self-hosted classic script must be enough for first paint.
  await page.route(
    /\/(?:src\/main\.tsx|assets\/index-[^/]+\.js)(?:\?.*)?$/,
    (route) => route.abort(),
  );
  await page.goto("/privacy");
  await expect(page.locator("#root")).toBeEmpty();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(
    await page
      .locator("html")
      .evaluate((element) => getComputedStyle(element).colorScheme),
  ).toBe("dark");
});

for (const theme of ["light", "dark"] as const) {
  test(`official local brand artwork and compact roles: ${theme}`, async ({
    page,
  }) => {
    await page.addInitScript(
      ({ key, value }) => localStorage.setItem(key, value),
      {
        key: themeKey,
        value: theme,
      },
    );
    await mockUI(page);
    const imageRequests: string[] = [];
    page.on("request", (request) => {
      if (request.resourceType() === "image") imageRequests.push(request.url());
    });
    expect(brandManifest.repository).toBe(
      "https://github.com/alxprgstech/assets",
    );
    expect(brandManifest.commit).toBe(
      "9b0eec08898a2eb2a02a66d895055c6ec7d97051", // pragma: allowlist secret -- pinned public assets commit SHA
    );
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 320, height: 480 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto("/login");
      const artwork = page.locator(".brand-auth img");
      await expect(artwork).toBeVisible();
      const name = viewport.width < 640 ? "logo-mark.svg" : "logo.svg";
      await expect
        .poll(() =>
          artwork.evaluate(
            (img: HTMLImageElement, expectedName) =>
              img.complete &&
              img.naturalWidth > 0 &&
              new URL(img.currentSrc).pathname === `/brand/${expectedName}`,
            name,
          ),
        )
        .toBe(true);
      await expect(artwork).toHaveCSS("background-color", "rgb(255, 255, 255)");
      await expect(page.locator(".auth-form h1").locator("..")).toHaveCSS(
        "opacity",
        "1",
      );
      await page.evaluate(() => document.fonts.ready);
      expect(
        await page
          .locator(".app-scroll")
          .evaluate((el) => el.scrollWidth <= el.clientWidth),
      ).toBe(true);
      await page.screenshot({
        path: `../artifacts/frontend-redesign/brand-${theme}-${viewport.width}.png`,
      });
    }
    for (const [name, expected] of Object.entries(brandManifest.files)) {
      const response = await page.request.get(`/brand/${name}`);
      expect(response.status()).toBe(200);
      const bytes = await response.body();
      expect(bytes.byteLength).toBe(expected.bytes);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(
        expected.sha256,
      );
    }
    await expect(
      page.locator('link[rel="icon"][type="image/svg+xml"]'),
    ).toHaveAttribute("href", "/brand/logo-mark.svg");
    await mockUI(page, profile);
    await page.goto("/");
    const brandLink = page.getByRole("link", {
      name: "ALXPRGS SSO — личный кабинет",
    });
    await expect(brandLink.locator("img")).toHaveAttribute(
      "src",
      "/brand/logo-mark.svg",
    );
    expect((await brandLink.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    const origin = new URL(page.url()).origin;
    expect(imageRequests.length).toBeGreaterThan(0);
    expect(
      imageRequests.every((url) => url.startsWith(`${origin}/brand/`)),
    ).toBe(true);
  });

  test(`palette text and focus contrast: ${theme}`, async ({ page }) => {
    await mockUI(page);
    await page.goto("/cookies");
    await page
      .getByRole("combobox", { name: "Тема оформления" })
      .selectOption(theme);
    const ratios = await page.evaluate(() => {
      const css = getComputedStyle(document.documentElement);
      const luminance = (variable: string) => {
        let hex = css.getPropertyValue(variable).trim().slice(1);
        if (hex.length === 3)
          hex = hex
            .split("")
            .map((c) => c + c)
            .join("");
        const channels = [0, 2, 4]
          .map((index) => parseInt(hex.slice(index, index + 2), 16) / 255)
          .map((value) =>
            value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
          );
        return (
          channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
        );
      };
      const contrast = (fg: string, bg: string) => {
        const a = luminance(fg),
          b = luminance(bg);
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      };
      const text = [
        "--text-primary",
        "--text-secondary",
        "--text-tertiary",
        "--brand",
      ].flatMap((fg) =>
        ["--canvas", "--surface-1"].map((bg) => ({
          pair: `${fg}/${bg}`,
          ratio: contrast(fg, bg),
        })),
      );
      for (const prefix of ["danger", "success", "warning"])
        text.push({
          pair: prefix,
          ratio: contrast(`--${prefix}`, `--${prefix}-surface`),
        });
      return {
        text,
        focus: contrast("--focus", "--surface-1"),
        border: contrast("--control-border", "--surface-1"),
      };
    });
    for (const sample of ratios.text)
      expect(sample.ratio, sample.pair).toBeGreaterThanOrEqual(4.5);
    expect(ratios.focus).toBeGreaterThanOrEqual(3);
    expect(ratios.border).toBeGreaterThanOrEqual(3);
  });
  for (const viewport of [
    { width: 1908, height: 901 },
    { width: 390, height: 844 },
  ]) {
    test(`mouse password focus, labels and typing: ${theme} ${viewport.width}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await mockUI(page);
      await page.addInitScript(
        ({ key, value }) => localStorage.setItem(key, value),
        { key: themeKey, value: theme },
      );
      for (const path of ["/login", "/register"]) {
        await page.goto(path);
        const fields = page.locator('input[type="password"]');
        await expect(fields.first()).toBeVisible();
        for (const field of await fields.all()) {
          await field.click();
          await expect(field).toBeFocused();
          await page.keyboard.type("SyntheticUiInput");
          await expect(field).toHaveValue("SyntheticUiInput");
          const id = await field.getAttribute("id");
          await page.locator(`label[for="${id}"]`).click();
          await expect(field).toBeFocused();
          expect(
            await field.evaluate((e) => getComputedStyle(e).outlineStyle),
          ).not.toBe("none");
        }
        await bannerAtBottom(page);
      }
    });

    test(`single dashboard deletion link and navigation: ${theme} ${viewport.width}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await mockUI(page, profile);
      await page.goto("/account/privacy");
      await page
        .getByRole("combobox", { name: "Тема оформления" })
        .selectOption(theme);
      const dataManagement = page.getByRole("region", {
        name: "Управление данными",
      });
      const deletion = dataManagement.getByRole("link", {
        name: "Удаление аккаунта",
        exact: true,
      });
      await expect(
        page.getByRole("link", { name: "Удаление аккаунта", exact: true }),
      ).toHaveCount(1);
      await expect(deletion).toHaveAttribute("href", "/account-deletion");
      await deletion.click();
      await expect(page).toHaveURL("/account-deletion");
      await expect(
        page.getByRole("heading", { name: "Удаление аккаунта", exact: true }),
      ).toBeVisible();
      await expect(page.getByLabel("Текущий пароль")).toBeVisible();
    });

    test(`consent actions and cookies layout: ${theme} ${viewport.width}`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await mockUI(page, { ...profile, legal_acceptance_required: true });
      await page.goto("/");
      await page
        .getByRole("combobox", { name: "Тема оформления" })
        .selectOption(theme);
      await expect(
        page.getByRole("heading", { name: "Подтвердите документы" }),
      ).toBeVisible();
      const deletion = page.getByRole("link", {
        name: "Удаление аккаунта",
        exact: true,
      });
      const logout = page.getByRole("button", { name: "Выйти", exact: true });
      const style = (element: Element) => {
        const css = getComputedStyle(element);
        return [
          css.height,
          css.padding,
          css.border,
          css.backgroundColor,
          css.color,
          css.textDecorationLine,
        ];
      };
      await expect
        .poll(
          async () =>
            JSON.stringify(await deletion.evaluate(style)) ===
            JSON.stringify(await logout.evaluate(style)),
        )
        .toBe(true);
      await bannerAtBottom(page);
      await page.screenshot({
        path: testInfo.outputPath(`consent-${theme}-${viewport.width}.png`),
      });
      const settingsTrigger = page.getByRole("button", {
        name: "Настройки cookies",
      });
      await settingsTrigger.click();
      await expect(
        page.getByRole("checkbox", { name: /Диагностика ошибок/ }),
      ).toBeFocused();
      await bannerAtBottom(page);
      await page.getByRole("button", { name: "Сохранить выбор" }).click();
      await expect(settingsTrigger).toBeFocused();
      await expect(page.locator(".cookie-banner")).toHaveCount(0);
      expect(
        await page
          .locator(".app-shell")
          .evaluate((element) => getComputedStyle(element).paddingBottom),
      ).toBe("0px");
    });
  }

  test(`last administrator refusal is a prominent alert: ${theme}`, async ({
    page,
  }) => {
    await mockUI(page, profile);
    await page.goto("/account-deletion");
    await page
      .getByRole("combobox", { name: "Тема оформления" })
      .selectOption(theme);
    await page.getByLabel("Текущий пароль").fill("SyntheticUiInput");
    await page
      .getByRole("button", { name: "Подтвердить доступ для удаления" })
      .click();
    await page.getByRole("checkbox", { name: /Понимаю последствия/ }).check();
    await page.getByRole("button", { name: "Запланировать удаление" }).click();
    const alert = page.getByRole("alert");
    await expect(alert).toContainText(
      "Запрещено удалять, блокировать или лишать прав последнего активного администратора системы",
    );
    await expect(alert.locator("strong")).toBeVisible();
    expect(
      await alert.evaluate(
        (element) => getComputedStyle(element).borderLeftWidth,
      ),
    ).toBe("4px");
    expect(
      await alert.evaluate(
        (element) => getComputedStyle(element).backgroundColor,
      ),
    ).not.toBe(
      await page
        .locator("body")
        .evaluate((element) => getComputedStyle(element).backgroundColor),
    );
  });

  test(`dashboard, QR and modal surfaces: ${theme}`, async ({ page }) => {
    await mockUI(page, profile, true);
    await page.goto("/account/security");
    await page
      .getByRole("combobox", { name: "Тема оформления" })
      .selectOption(theme);
    await page.getByRole("button", { name: /Настроить TOTP/ }).click();
    const qr = page.getByRole("img", {
      name: "QR-код для подключения ALXPRGS SSO",
    });
    await expect(qr).toBeVisible();
    expect(
      await qr
        .locator("..")
        .evaluate((element) => getComputedStyle(element).backgroundColor),
    ).toBe("rgb(255, 255, 255)");
    await page.getByRole("button", { name: "Изменить пароль" }).click();
    const dialog = page.getByRole("dialog", { name: "Смена пароля" });
    await expect(dialog).toBeVisible();
    expect(
      await dialog.evaluate(
        (element) => getComputedStyle(element).backgroundColor,
      ),
    ).toBe(theme === "dark" ? "rgb(15, 17, 21)" : "rgb(255, 255, 255)");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await page.getByRole("link", { name: "Администрирование" }).click();
    await page.goto("/admin/users");
    await page.getByRole("button", { name: /Добавить пользователя/ }).click();
    const adminDialog = page.getByRole("dialog", {
      name: "Новый пользователь",
    });
    await expect(adminDialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(adminDialog).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await bannerAtBottom(page);
    expect(
      await page
        .locator(".app-scroll")
        .evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
    await page
      .getByRole("link", { name: "Личный кабинет", exact: true })
      .click();
  });
}

// Browser UI regressions with explicit fixtures; real API/PG suites remain mandatory.
test("deep links, browser back/forward and heading titles", async ({
  page,
}) => {
  await mockUI(page, profile);
  await page.goto("/account/sessions");
  await expect(
    page.getByRole("heading", { name: "Активные сессии", level: 1 }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Разделы учётной записи" })
    .getByRole("link", { name: "Профиль", exact: true })
    .click();
  await expect(page).toHaveURL("/");
  await page
    .getByRole("navigation", { name: "Разделы учётной записи" })
    .getByRole("link", { name: "Безопасность", exact: true })
    .click();
  await expect(page).toHaveURL("/account/security");
  await expect(page).toHaveTitle("Безопасность — ALXPRGS SSO");
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Профиль", level: 1 }),
  ).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL("/account/security");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Безопасность", level: 1 }),
  ).toBeVisible();
  await page.goto("/missing/route");
  await expect(
    page.getByRole("heading", { name: "Страница не найдена" }),
  ).toBeVisible();
});
test("command palette keyboard navigation, no result and Escape focus restoration", async ({
  page,
}) => {
  await mockUI(page, profile);
  await page.goto("/");
  const opener = page.getByRole("button", { name: "Открыть команды" });
  await expect(
    page.getByRole("heading", { name: "Профиль", level: 1 }),
  ).toBeVisible();
  await opener.focus();
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Команды ALXPRGS" });
  const search = dialog.getByRole("combobox", { name: "Поиск команды" });
  await expect(search).toBeFocused();
  await search.fill("Несуществующая команда XZQ");
  await expect(dialog.getByText("Команды не найдены")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await page.keyboard.press("Control+k");
  await search.fill("Безопасность");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/account/security");
  await expect(
    page.getByRole("heading", { name: "Безопасность", level: 1 }),
  ).toBeFocused();
});
test("ordinary profiles cannot discover or fetch administrator controls", async ({
  page,
}) => {
  const adminRequests: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/v1/admin/"))
      adminRequests.push(r.url());
  });
  await mockUI(page, { ...profile, is_superuser: false, roles: ["user"] });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Профиль", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Администрирование" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Открыть команды" }).click();
  await page
    .getByRole("combobox", { name: "Поиск команды" })
    .fill("Журнал аудита");
  await expect(page.getByText("Команды не найдены")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("/admin/users");
  await expect(
    page.getByRole("heading", { name: "Доступ ограничен" }),
  ).toBeVisible();
  expect(adminRequests).toEqual([]);
});
test("320px short viewport keeps modal scrolling, focus isolation and mobile navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 360 });
  await mockUI(page, profile);
  await page.goto("/account/security");
  const opener = page.getByRole("button", { name: "Изменить пароль" });
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Смена пароля" });
  await expect(dialog.getByLabel("Текущий пароль")).toBeFocused();
  await expect(dialog).toHaveCSS("opacity", "1");
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(15);
  expect(box!.y).toBeGreaterThanOrEqual(15);
  expect(box!.y + box!.height).toBeLessThanOrEqual(345);
  expect(
    await page.locator(".app-shell").evaluate((e) => (e as HTMLElement).inert),
  ).toBe(true);
  for (let i = 0; i < 15; i++) {
    await page.keyboard.press("Tab");
    expect(
      await dialog.evaluate((e) => e.contains(document.activeElement)),
    ).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
  await page.getByRole("button", { name: "Разделы", exact: true }).click();
  const menu = page.getByRole("dialog", { name: "Разделы" });
  await menu.getByRole("link", { name: "Сессии", exact: true }).click();
  await expect(page).toHaveURL("/account/sessions");
  expect(
    await page
      .locator(".app-scroll")
      .evaluate((e) => e.scrollWidth <= e.clientWidth),
  ).toBe(true);
});
test("reduced motion disables repeated topology animation and pointer lighting updates", async ({
  page,
}) => {
  await mockUI(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/login");
  const scene = page.locator(".infrastructure");
  await expect(scene).toHaveAttribute("data-running", "false");
  expect(
    await page
      .locator(".signal")
      .evaluate((e) => getComputedStyle(e).animationName),
  ).toBe("none");
  const box = await scene.boundingBox();
  await page.mouse.move(box!.x + 10, box!.y + 10);
  await page.mouse.move(box!.x + 100, box!.y + 100);
  expect(
    await scene.evaluate((e) =>
      (e as HTMLElement).style.getPropertyValue("--pointer-x"),
    ),
  ).toBe("");
  await expect(page.getByLabel("Пароль", { exact: true })).toBeEditable();
});

test("decorative chunk failure leaves authentication usable", async ({
  page,
}) => {
  await mockUI(page, null, false, {
    "POST /api/v1/auth/login": {
      status: 401,
      json: { error: "invalid_credentials" },
    },
  });
  const chunkPattern =
    /\/(?:assets\/Infrastructure-[\w-]+\.js|src\/components\/Infrastructure\.tsx)(?:\?.*)?$/;
  const failure = page.waitForEvent("requestfailed", {
    predicate: (request) => chunkPattern.test(request.url()),
  });
  await page.route(chunkPattern, (route) => route.abort("failed"));
  await page.goto("/login");
  await failure;
  const username = page.getByLabel("Имя пользователя или Email", {
    exact: true,
  });
  await expect(username).toBeVisible();
  await expect(
    page.getByText("Не удалось отобразить страницу.", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".auth-decoration")).toHaveCount(0);
  await username.fill("decorative_failure_user");
  await page.getByLabel("Пароль", { exact: true }).fill("test123");
  const request = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/auth/login",
  );
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  expect((await request).postDataJSON().username).toBe(
    "decorative_failure_user",
  );
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(username).toBeVisible();
});

for (const theme of ["dark", "light"] as const) {
  test(`accessible public and account/admin surfaces: ${theme}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockUI(page, profile, false, {
      "GET /api/v1/admin/clients": { json: [] },
    });
    for (const path of [
      "/",
      "/account/security",
      "/account/sessions",
      "/account/privacy",
      "/admin",
      "/admin/users",
      "/admin/applications",
      "/admin/audit",
      "/admin/system",
      "/account-deletion",
      "/privacy",
    ]) {
      await page.goto(path);
      await page
        .getByRole("combobox", { name: "Тема оформления" })
        .selectOption(theme);
      await expect(page.locator("#main-content h1")).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "best-practice"])
        .analyze();
      expect(
        result.violations.map((v) => ({
          id: v.id,
          targets: v.nodes.map((n) => n.target),
        })),
        path,
      ).toEqual([]);
    }
    await mockUI(page, null, false); // Explicit anonymous UI fixture, never used in protected integration.
    for (const path of ["/login", "/register"]) {
      await page.goto(path);
      await page
        .getByRole("combobox", { name: "Тема оформления" })
        .selectOption(theme);
      await expect(page.locator("#main-content h1")).toBeVisible();
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "best-practice"])
        .analyze();
      expect(
        result.violations.map((v) => ({
          id: v.id,
          targets: v.nodes.map((n) => n.target),
        })),
        path,
      ).toEqual([]);
    }
  });
}

for (const theme of ["dark", "light"] as const) {
  test(`render and keyboard table/menu/palette surfaces: ${theme}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1440, height: 900 });
    const users = [
      {
        ...profile,
        id: "ui-admin",
        username: "alex_admin",
        updated_at: profile.created_at,
      },
      {
        ...profile,
        id: "ui-reader",
        username: "research_reader",
        email: "reader@example.test",
        roles: ["user"],
        is_superuser: false,
        updated_at: profile.created_at,
      },
      {
        ...profile,
        id: "ui-disabled",
        username: "blocked_account",
        email: "blocked@example.test",
        roles: ["user"],
        is_active: false,
        is_superuser: false,
        updated_at: profile.created_at,
      },
    ];
    await mockUI(page, profile, true, {
      "GET /api/v1/admin/users": { json: users },
      "GET /api/v1/admin/clients": {
        json: [
          {
            id: "ui-app",
            client_id: "ui-analytics",
            client_name: "Портал исследований",
            client_type: "confidential",
            is_active: true,
            redirect_uris: ["https://research.example.test/identity/callback"],
            allowed_scopes: ["openid", "profile", "email"],
            client_secret: null,
            created_at: profile.created_at,
          },
        ],
      },
      "GET /api/v1/admin/audit": {
        json: [
          {
            id: "ui-event",
            event_type: "session.login",
            user_id: "ui-admin",
            ip_address: "192.0.2.1",
            user_agent: "Synthetic browser",
            details: {},
            created_at: profile.created_at,
          },
        ],
      },
      "GET /api/v1/auth/sessions": {
        json: [
          {
            id: "ui-session",
            ip_address: "192.0.2.1",
            user_agent: "Synthetic desktop browser",
            is_current: true,
            last_activity_at: profile.created_at,
            expires_at: profile.created_at,
            created_at: profile.created_at,
          },
        ],
      },
    });
    for (const path of [
      "/",
      "/account/security",
      "/account/sessions",
      "/admin",
      "/admin/users",
      "/admin/applications",
    ]) {
      await page.goto(path);
      await page
        .getByRole("combobox", { name: "Тема оформления" })
        .selectOption(theme);
      await expect(page.locator("#main-content h1")).toBeVisible();
      if (path === "/admin/users")
        await expect(
          page.getByRole("button", { name: "Действия: alex_admin" }),
        ).toBeVisible();
      if (path === "/admin/applications")
        await expect(page.getByText("Портал исследований")).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      expect(
        await page
          .locator(".app-scroll")
          .evaluate((e) => e.scrollWidth <= e.clientWidth),
      ).toBe(true);
      const key = path === "/" ? "profile" : path.slice(1).replace(/\//g, "-");
      await page.screenshot({
        path: `../artifacts/frontend-redesign/final-${theme}-${key}-desktop.png`,
      });
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "best-practice"])
        .analyze();
      expect(
        result.violations.map((v) => ({
          id: v.id,
          targets: v.nodes.map((n) => n.target),
        })),
        path,
      ).toEqual([]);
    }
    await page.goto("/admin/users");
    const table = page.getByRole("table", { name: "Пользователи" });
    await table.getByRole("button", { name: /Пользователь/ }).click();
    await expect(table.getByRole("columnheader").first()).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    const menu = page.getByRole("button", { name: "Действия: alex_admin" });
    await menu.focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("menuitem", { name: "Заблокировать", exact: true }),
    ).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(
      page.getByRole("menuitem", { name: "Отозвать сессии" }),
    ).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toBeFocused();
    await page.getByRole("button", { name: "Открыть команды" }).click();
    await expect(
      page.getByRole("combobox", { name: "Поиск команды" }),
    ).toBeFocused();
    await page.screenshot({
      path: `../artifacts/frontend-redesign/final-${theme}-commands-desktop.png`,
    });
    const paletteAudit = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "best-practice"])
      .analyze();
    expect(
      paletteAudit.violations.map((v) => ({
        id: v.id,
        targets: v.nodes.map((n) => n.target),
      })),
    ).toEqual([]);
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/admin/users");
    await expect(menu).toBeVisible();
    expect(
      await page
        .locator(".app-scroll")
        .evaluate((e) => e.scrollWidth <= e.clientWidth),
    ).toBe(true);
    await page.screenshot({
      path: `../artifacts/frontend-redesign/final-${theme}-users-mobile.png`,
    });
    await page.goto("/account/security");
    await page.getByRole("button", { name: "Изменить пароль" }).click();
    await expect(page.getByRole("dialog", { name: "Смена пароля" })).toHaveCSS(
      "opacity",
      "1",
    );
    await page.screenshot({
      path: `../artifacts/frontend-redesign/final-${theme}-password-mobile.png`,
    });
    const modalAudit = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "best-practice"])
      .analyze();
    expect(
      modalAudit.violations.map((v) => ({
        id: v.id,
        targets: v.nodes.map((n) => n.target),
      })),
    ).toEqual([]);
    await page.keyboard.press("Escape");
    await mockUI(page, null, true);
    for (const path of ["/login", "/register"]) {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(path);
      await expect(page.locator("#main-content h1")).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({
        path: `../artifacts/frontend-redesign/final-${theme}-${path.slice(1)}-desktop.png`,
      });
      await page.setViewportSize({ width: 320, height: 480 });
      expect(
        await page
          .locator(".app-scroll")
          .evaluate((e) => e.scrollWidth <= e.clientWidth),
      ).toBe(true);
      await page.screenshot({
        path: `../artifacts/frontend-redesign/final-${theme}-${path.slice(1)}-mobile.png`,
      });
    }
  });
}
