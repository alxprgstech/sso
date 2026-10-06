import { test, expect } from "@playwright/test";

test("static cache policy preserves CSP and refreshes the HTML shell", async ({ page, request }) => {
  const paths: string[] = [];
  page.on("request", response => paths.push(new URL(response.url()).pathname));
  const shell = await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Вход в ALXPRGS" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(shell!.headers()["cache-control"]).toBe("no-cache");
  const assets = paths.filter(path => /^\/assets\/.+-[A-Za-z0-9_-]{8}\.(js|css|woff2)$/.test(path));
  expect(assets.length).toBeGreaterThan(0);
  for (const path of assets) {
    const response = await request.get(path);
    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toBe("max-age=31536000");
    expect(response.headers()["content-security-policy"]).toContain("script-src 'self'");
    expect(response.headers()["x-content-type-options"]).toBe("nosniff");
  }
  expect(paths).not.toContain("/theme/design-tokens.css");
  expect(paths.some(path => /\/assets\/(sentry-runtime|replay|Dialog)-/.test(path))).toBe(false);
  const mutable = await request.get("/theme/theme.js");
  expect(mutable.headers()["cache-control"]).toBe("max-age=3600");
  for (const path of ["/assets/missing-abcdefgh.js", "/assets/private-abcdefgh.js.map", "/brand/missing.svg"]) {
    const response = await request.get(path);
    expect(response.status()).toBe(404);
    expect(response.headers()["cache-control"]).toBeUndefined();
  }
});

test("proxy serves llms.txt as UTF-8 text in the browser", async ({ page }) => {
  const response = await page.goto("/llms.txt");
  expect(response?.status()).toBe(200);
  expect(response!.headers()["content-type"]).toMatch(/^text\/plain;\s*charset=utf-8$/i);
  expect(response!.headers()["x-content-type-options"]).toBe("nosniff");
  const text = await page.locator("body").innerText();
  expect(text).toContain("# ALXPRGS SSO");
  expect(text).toContain("Единая система входа для сервисов ALXPRGS");
  expect(text).toContain("[Политика конфиденциальности](/privacy)");
  expect(text).not.toContain("Р•Рґ");
});

test("proxy enforces CSP while the production login UI remains functional", async ({ page }) => {
  const response = await page.goto("/login");
  expect(response).not.toBeNull();
  const headers = response!.headers();
  expect(headers["content-security-policy"]).toContain("script-src 'self'");
  expect(headers["content-security-policy-report-only"]).toBeUndefined();
  expect(headers["content-security-policy"]).not.toMatch(/unsafe-inline|unsafe-eval/);
  await expect(page.getByRole("heading", { name: "Вход в ALXPRGS" })).toBeVisible();
  await expect(page.getByLabel("Имя пользователя или Email")).toBeEditable();
  let foreignRequests = 0;
  await page.route("https://csp-injected.example/**", route => { foreignRequests++; return route.abort(); });
  const result = await page.evaluate(async () => {
    const violations: string[] = [];
    document.addEventListener("securitypolicyviolation", event => violations.push(event.violatedDirective));
    const script = document.createElement("script");
    script.textContent = "document.documentElement.dataset.injected = 'executed'";
    document.body.append(script);
    const foreign = document.createElement("script");
    foreign.src = "https://csp-injected.example/script.js";
    document.body.append(foreign);
    const style = document.createElement("style");
    style.textContent = "html { --injected-style: executed; }";
    document.head.append(style);
    await fetch("https://csp-injected.example/collect").catch(() => undefined);
    await new Promise(resolve => setTimeout(resolve, 100));
    return { violations, executed: document.documentElement.dataset.injected,
      style: getComputedStyle(document.documentElement).getPropertyValue("--injected-style") };
  });
  expect(result.executed).toBeUndefined();
  expect(result.style).toBe("");
  expect(result.violations).toEqual(expect.arrayContaining(["script-src-elem", "style-src-elem", "connect-src"]));
  expect(foreignRequests).toBe(0);
  await expect(page.getByLabel("Пароль", { exact: true })).toBeEditable();
});
