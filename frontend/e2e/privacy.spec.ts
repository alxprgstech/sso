import { test, expect, type Page, type Locator } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createHash, randomBytes } from "node:crypto";

const username = "privacy_e2e_" + randomBytes(6).toString("hex");

async function keyboardFocus(page: Page, target: Locator) {
  for (let step=0; step<90; step++) {
    if (await target.evaluate(element => element === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error("Control cannot be reached with Tab");
}
async function activate(page: Page, target: Locator) { await keyboardFocus(page, target); await page.keyboard.press("Enter"); }
async function type(page: Page, target: Locator, value: string) { await keyboardFocus(page,target); await page.keyboard.type(value); }
async function check(page: Page, target: Locator) { await keyboardFocus(page,target); await page.keyboard.press("Space"); }

test.beforeAll(() => {
  if (!process.env.TEST_DATABASE_URL || !process.env.PYTHON_BIN) throw new Error("Explicit test DB and Python required");
  execFileSync(process.env.PYTHON_BIN, [fileURLToPath(new URL("../../scripts/prepare_e2e_data.py", import.meta.url))], {env:{...process.env, PRIVACY_E2E_USERNAME:username}, stdio:"inherit"});
});

test("public documents and cookie refusal work with a keyboard, reload and another tab", async ({page, context}) => {
  const outgoing:string[]=[];
  page.on("request",request=>outgoing.push(request.url()));
  await page.goto("/login");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link",{name:"К основному содержимому"})).toBeFocused();
  await page.keyboard.press("Enter"); await expect(page.locator("#main-content")).toBeFocused();
  await activate(page,page.getByRole("button",{name:"Только необходимые"}));
  await page.reload(); await expect(page.getByRole("heading",{name:"Cookies и диагностика"})).toHaveCount(0);
  for (const [name,title] of [["Конфиденциальность","Политика конфиденциальности"],["Условия использования","Условия использования"],["Политика cookies","Политика cookies и браузерного хранения"],["Согласие на обработку данных","Согласие на обработку персональных данных"]]) {
    await activate(page,page.getByRole("link",{name,exact:true})); await expect(page.getByRole("heading",{name:title,exact:true})).toBeVisible();
  }
  const second=await context.newPage(); await second.goto("/login");
  await activate(page,page.getByRole("button",{name:"Настройки cookies"}));
  await activate(page,page.getByRole("button",{name:"Разрешить диагностику"}));
  await expect.poll(()=>second.evaluate(()=>JSON.parse(localStorage.getItem("alxprgs.privacy.v1")!).diagnostics)).toBe(true);
  await activate(second,second.getByRole("button",{name:"Настройки cookies"}));
  await activate(second,second.getByRole("button",{name:"Только необходимые"}));
  await expect.poll(()=>page.evaluate(()=>JSON.parse(localStorage.getItem("alxprgs.privacy.v1")!).diagnostics)).toBe(false);
  expect(outgoing.some(url=>/\.ingest(?:\.[a-z]+)?\.sentry\.io/.test(url))).toBe(false);
});

test("account deletion: real default/enabled policy, limited access and keyboard cancellation", async ({page,context}) => {
  const capabilities=await (await page.request.get("/api/v1/auth/capabilities")).json();
  const enabled=process.env.PRIVACY_ENABLED_PROFILE === "1";
  expect(capabilities.passkey_enabled).toBe(enabled);
  let cdp;
  if (enabled) {
    cdp=await context.newCDPSession(page); await cdp.send("WebAuthn.enable");
    await cdp.send("WebAuthn.addVirtualAuthenticator",{options:{protocol:"ctap2",transport:"internal",hasResidentKey:true,hasUserVerification:true,isUserVerified:true}});
  }
  await page.goto("/login");
  await type(page,page.getByLabel("Имя пользователя или Email"),username);
  await type(page,page.getByLabel("Пароль",{exact:true}),"PasskeyE2E2026!");
  await activate(page,page.getByRole("button",{name:"Войти",exact:true}));
  await expect(page.getByRole("heading",{name:"Подтвердите документы"})).toBeVisible();
  const consent=page.getByRole("checkbox");
  await expect(consent.nth(0)).not.toBeChecked(); await expect(consent.nth(1)).not.toBeChecked();
  await check(page,consent.nth(0)); await check(page,consent.nth(1));
  await activate(page,page.getByRole("button",{name:"Подтвердить и продолжить"}));
  await expect(page.getByRole("button",{name:"Личный кабинет",exact:true})).toBeVisible();
  if (enabled) {
    await type(page,page.locator('[data-testid="passkey-name-input"]'),"Synthetic privacy key");
    await activate(page,page.locator('[data-testid="register-passkey-button"]'));
    await expect(page.locator('[data-testid="passkey-success"]')).toBeVisible();
  }
  const verifier=randomBytes(32).toString("base64url"); const challenge=createHash("sha256").update(verifier).digest("base64url");
  const authorize=await page.request.get("/oauth/authorize",{maxRedirects:0,params:{client_id:"client_analytics_app",redirect_uri:"http://127.0.0.1:8001/callback",response_type:"code",code_challenge:challenge,code_challenge_method:"S256",scope:"openid profile email"}});
  expect(authorize.status()).toBe(302);
  const code=new URL(authorize.headers().location).searchParams.get("code")!;
  const tokens=await (await page.request.post("/oauth/token",{form:{grant_type:"authorization_code",client_id:"client_analytics_app",client_secret:"analytics_client_secret_123",code,code_verifier:verifier,redirect_uri:"http://127.0.0.1:8001/callback"}})).json();
  expect(tokens.access_token).toBeTruthy();
  await activate(page,page.getByRole("region",{name:"Управление данными"}).getByRole("link",{name:"Удаление аккаунта",exact:true}));
  const reauthenticate=async (action:string) => {
    await type(page,page.getByLabel("Текущий пароль"),"PasskeyE2E2026!");
    await activate(page,page.getByRole("button",{name:`Подтвердить доступ для ${action}`}));
    if (enabled) {
      await expect(page.getByLabel("Второй фактор")).toHaveValue("passkey");
      await activate(page,page.getByRole("button",{name:"Подтвердить второй фактор"}));
    }
    await expect(page.getByRole("checkbox")).toBeVisible();
    await check(page,page.getByRole("checkbox"));
  };
  await reauthenticate("удаления");
  const response=page.waitForResponse(response=>response.url().endsWith("/api/v1/auth/account-deletion")&&response.request().method()==="POST");
  await activate(page,page.getByRole("button",{name:"Запланировать удаление"}));
  const submitted=await response; expect(submitted.status()).toBe(202);
  const status=await submitted.json(); expect(Date.parse(status.scheduled_for)-Date.parse(status.requested_at)).toBe(14*86400000);
  await expect(page.getByText(/Окончательное удаление запланировано/)).toBeVisible();
  expect((await page.request.get("/api/v1/auth/sessions")).status()).toBe(403);
  expect((await page.request.get("/oauth/userinfo",{headers:{Authorization:`Bearer ${tokens.access_token}`}})).status()).toBe(401);
  expect((await page.request.post("/oauth/token",{form:{grant_type:"refresh_token",client_id:"client_analytics_app",client_secret:"analytics_client_secret_123",refresh_token:tokens.refresh_token}})).status()).toBe(400);
  await page.reload(); await expect(page.getByText(/Окончательное удаление запланировано/)).toBeVisible();
  await reauthenticate("отмены"); await activate(page,page.getByRole("button",{name:"Отменить удаление"}));
  await expect(page.getByRole("heading",{name:"Единая система входа ALXPRGS"})).toBeVisible();
  await type(page,page.getByLabel("Имя пользователя или Email"),username);
  await type(page,page.getByLabel("Пароль",{exact:true}),"PasskeyE2E2026!");
  await activate(page,page.getByRole("button",{name:"Войти",exact:true}));
  if (enabled) await activate(page,page.locator('[data-testid="passkey-mfa-button"]'));
  await expect(page.getByRole("button",{name:"Личный кабинет",exact:true})).toBeVisible();
  await activate(page,page.getByRole("region",{name:"Управление данными"}).getByRole("link",{name:"Удаление аккаунта",exact:true}));
  await expect(page.getByText(/Повторная заявка доступна с/)).toBeVisible();
});


test("administrator dialog supports keyboard focus, Shift+Tab and Escape", async ({page}) => {
  await page.goto("/login");
  await type(page,page.getByLabel("Имя пользователя или Email"),"compose_admin");
  await type(page,page.getByLabel("Пароль",{exact:true}),"ComposeAdminPass2026!");
  await activate(page,page.getByRole("button",{name:"Войти",exact:true}));
  await expect(page.getByRole("heading",{name:"Подтвердите документы"}).or(page.getByRole("button",{name:"Личный кабинет",exact:true}))).toBeVisible();
  if (await page.getByRole("heading",{name:"Подтвердите документы"}).isVisible()) {
    await check(page,page.getByRole("checkbox").nth(0)); await check(page,page.getByRole("checkbox").nth(1));
    await activate(page,page.getByRole("button",{name:"Подтвердить и продолжить"}));
  }
  await activate(page,page.getByRole("button",{name:"Администрирование",exact:true}));
  const opener = page.getByRole("button",{name:"+ Добавить пользователя",exact:true});
  await activate(page,opener);
  const dialog=page.getByRole("dialog",{name:"Новый пользователь"});
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
  for (let step=0;step<12;step++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0); await expect(opener).toBeFocused();
});
