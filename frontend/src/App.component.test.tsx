import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "./App";
import type { Capabilities, UserProfile } from "./types/api";

vi.mock("qrcode.react", () => ({
  QRCodeSVG: ({ value }: { value: string }) => (
    <svg data-testid="qr-renderer" data-value={value} />
  ),
}));

const apiMock = vi.hoisted(() => ({
  setReauthenticationHandler: vi.fn(),
  startReauthentication: vi.fn(),
  confirmReauthentication: vi.fn(),
  getCapabilities: vi.fn(),
  getLegalDocuments: vi.fn(),
  getMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  getClientContext: vi.fn(),
  verifyTotpLogin: vi.fn(),
  verifyRecoveryCodeLogin: vi.fn(),
  getSessions: vi.fn(),
  getPasskeyCredentials: vi.fn(),
  getAdminUsers: vi.fn(),
  createAdminUser: vi.fn(),
  getSystemStatus: vi.fn(),
  updateRegistrationMode: vi.fn(),
  changePassword: vi.fn(),
  getAuditEvents: vi.fn(),
  downloadAudit: vi.fn(),
  setupTotp: vi.fn(),
  confirmEmailVerification: vi.fn(),
  register: vi.fn(),
  confirmRegistrationCode: vi.fn(),
  confirmRegistrationLink: vi.fn(),
  previewRegistrationLink: vi.fn(),
  resendRegistration: vi.fn(),
}));
vi.mock("./api/client", () => ({ api: apiMock }));

const disabled: Capabilities = {
  totp_enabled: false,
  passkey_enabled: false,
  recovery_codes_enabled: false,
  email_verification_enabled: true,
  require_verified_email: false,
  registration_mode: "closed",
};

const admin: UserProfile = {
  id: "synthetic-admin",
  username: "admin_test",
  email: "admin@example.test",
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

beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState({}, "", "/login");
  apiMock.getCapabilities.mockResolvedValue(disabled);
  apiMock.getLegalDocuments.mockResolvedValue({
    documents: [],
    required_versions: { terms: "2026-10-03", "data-consent": "2026-10-03" },
  });
  apiMock.getMe.mockRejectedValue(new Error("No session"));
  apiMock.getSessions.mockResolvedValue([]);
  apiMock.logout.mockResolvedValue(undefined);
  apiMock.getAdminUsers.mockResolvedValue([]);
  apiMock.getAuditEvents.mockResolvedValue([]);
  apiMock.downloadAudit.mockResolvedValue(undefined);
  apiMock.getSystemStatus.mockResolvedValue({
    bootstrap_completed: true,
    bootstrap_completed_at: null,
    registration_mode: "closed",
    total_users: 1,
    total_active_admins: 1,
  });
});
afterEach(cleanup);

async function enterPassword() {
  const username = screen.getByPlaceholderText("user@alxprgs.tech");
  const password = document.querySelector<HTMLInputElement>(
    'input[type="password"]',
  );
  expect(password).not.toBeNull();
  fireEvent.change(username, { target: { value: "synthetic_user" } });
  fireEvent.change(password!, { target: { value: "synthetic_password" } });
  fireEvent.click(screen.getByRole("button", { name: "Войти" }));
}

describe("server capabilities and account flows", () => {
  it("distinguishes a pending or failed passkey read from an empty list and retries", async () => {
    window.history.replaceState({}, "", "/account/security");
    apiMock.getMe.mockResolvedValue(admin);
    apiMock.getCapabilities.mockResolvedValue({
      ...disabled,
      passkey_enabled: true,
    });
    let rejectRead!: (reason: Error) => void;
    apiMock.getPasskeyCredentials.mockImplementationOnce(
      () =>
        new Promise((_, reject) => {
          rejectRead = reject;
        }),
    );
    apiMock.getPasskeyCredentials.mockResolvedValueOnce([]);
    render(<App />);
    await screen.findByText("Загрузка ключей доступа");
    expect(screen.queryByTestId("passkeys-empty")).toBeNull();
    await waitFor(() =>
      expect(apiMock.getPasskeyCredentials).toHaveBeenCalledTimes(1),
    );
    await act(async () => rejectRead(new Error("Unavailable")));
    await screen.findByText("Не удалось загрузить ключи доступа.");
    expect(screen.queryByTestId("passkeys-empty")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Повторить загрузку ключей" }),
    );
    await screen.findByTestId("passkeys-empty");
    expect(apiMock.getPasskeyCredentials).toHaveBeenCalledTimes(2);
  });
  it("requires the emailed six-digit code before completing registration", async () => {
    window.history.replaceState({}, "", "/register");
    apiMock.getCapabilities.mockResolvedValue({
      ...disabled,
      registration_mode: "open",
    });
    apiMock.register.mockResolvedValue({
      status: "verification_pending",
      challenge_id: "synthetic-challenge",
      expires_at: "2026-09-29T18:00:00Z",
      request_details: { ip: "192.0.2.1", os: "Windows", city: "Неизвестно" },
    });
    apiMock.confirmRegistrationCode.mockResolvedValue({
      status: "ok",
      user_id: "synthetic-user",
    });
    render(<App />);
    fireEvent.change(await screen.findByPlaceholderText("alex_ivanov"), {
      target: { value: "alex" },
    });
    fireEvent.change(screen.getByPlaceholderText("alex@alxprgs.tech"), {
      target: { value: "alex@example.test" },
    });
    const passwords = document.querySelectorAll<HTMLInputElement>(
      'input[type="password"]',
    );
    fireEvent.change(passwords[0], {
      target: { value: "SyntheticPassword2026!" },
    });
    fireEvent.change(passwords[1], {
      target: { value: "SyntheticPassword2026!" },
    });
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Зарегистрироваться" })
          .hasAttribute("disabled"),
      ).toBe(true),
    );
    for (const checkbox of screen.getAllByRole("checkbox"))
      fireEvent.click(checkbox);
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "Зарегистрироваться" })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрироваться" }));
    await screen.findByLabelText("Код из письма");
    expect(apiMock.confirmRegistrationCode).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Сведения о запросе"));
    expect(screen.getByText("Windows")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Код из письма"), {
      target: { value: "012345" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить адрес" }));
    await waitFor(() =>
      expect(apiMock.confirmRegistrationCode).toHaveBeenCalledWith(
        "synthetic-challenge",
        "012345",
      ),
    );
    expect(await screen.findByText(/учётная запись создана/)).toBeTruthy();
  });

  it("previews registration link details without consuming the link", async () => {
    window.history.replaceState(
      {},
      "",
      "/verify-email?mode=registration&token=synthetic-registration-link",
    );
    apiMock.previewRegistrationLink.mockResolvedValue({
      request_details: { ip: "192.0.2.2", city: "Неизвестно" },
    });
    apiMock.confirmRegistrationLink.mockResolvedValue({
      status: "ok",
      user_id: "synthetic-user",
    });
    render(<App />);
    await screen.findByRole("button", { name: "Подтвердить адрес" });
    expect(window.location.search).toBe("");
    expect(apiMock.confirmRegistrationLink).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить адрес" }));
    await waitFor(() =>
      expect(apiMock.confirmRegistrationLink).toHaveBeenCalledWith(
        "synthetic-registration-link",
      ),
    );
  });

  it("opens a verification link without a session and waits for a user click", async () => {
    window.history.replaceState(
      {},
      "",
      "/verify-email?token=synthetic-once-token",
    );
    apiMock.confirmEmailVerification.mockResolvedValue({
      status: "ok",
      message: "Подтверждено",
    });
    render(<App />);
    const button = await screen.findByRole("button", {
      name: "Подтвердить адрес",
    });
    expect(window.location.search).toBe("");
    expect(apiMock.confirmEmailVerification).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() =>
      expect(apiMock.confirmEmailVerification).toHaveBeenCalledWith(
        "synthetic-once-token",
      ),
    );
    expect((await screen.findByRole("status")).textContent).toContain(
      "Адрес подтверждён",
    );
  });

  it("shows an error for an expired verification token without exposing it", async () => {
    window.history.replaceState(
      {},
      "",
      "/verify-email?token=synthetic-expired-token",
    );
    apiMock.confirmEmailVerification.mockRejectedValue(
      new Error("Ссылка недействительна"),
    );
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Подтвердить адрес" }),
    );
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Ссылка недействительна",
    );
    expect(window.location.search).toBe("");
    expect(screen.queryByText("synthetic-expired-token")).toBeNull();
  });

  it.each([
    ["normal account", { ...admin, is_superuser: false, roles: ["user"] }],
    ["administrator", admin],
  ])(
    "shows a single account deletion link in data management for %s",
    async (_role, user) => {
      apiMock.getMe.mockResolvedValue(user);
      window.history.replaceState({}, "", "/account/privacy");
      render(<App />);
      const dataManagement = await screen.findByRole("region", {
        name: "Управление данными",
      });
      const link = within(dataManagement).getByRole("link", {
        name: "Удаление аккаунта",
      });
      expect(link.getAttribute("href")).toBe("/account-deletion");
      expect(
        screen.getAllByRole("link", { name: "Удаление аккаунта" }),
      ).toEqual([link]);
    },
  );

  it("does not expose TOTP setup or QR when the server flag is disabled", async () => {
    apiMock.getMe.mockResolvedValue(admin);
    window.history.replaceState({}, "", "/account/security");
    render(<App />);
    await screen.findByTestId("totp-section");
    expect(screen.queryByTestId("totp-qr-code")).toBeNull();
    expect(screen.queryByTestId("copy-totp-secret-button")).toBeNull();
    expect(screen.queryByRole("button", { name: "Настроить TOTP" })).toBeNull();
  });

  it("renders the server TOTP provisioning URI as QR and copies only the secret", async () => {
    const provisioningUri =
      "otpauth://totp/ALXPRGS%20SSO:admin%40example.test?secret=ABCDEF&issuer=ALXPRGS%20SSO";
    const writeText = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("Denied"));
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    apiMock.getMe.mockResolvedValue(admin);
    apiMock.getCapabilities.mockResolvedValue({
      ...disabled,
      totp_enabled: true,
    });
    apiMock.setupTotp.mockResolvedValue({
      secret: "ABCDEF",
      otpauth_url: provisioningUri,
    });
    window.history.replaceState({}, "", "/account/security");
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Настроить TOTP" }),
    );
    expect(
      (await screen.findByTestId("qr-renderer")).getAttribute("data-value"),
    ).toBe(provisioningUri);
    expect(screen.getByTestId("totp-secret").textContent).toContain("ABCDEF");
    fireEvent.click(screen.getByTestId("copy-totp-secret-button"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("ABCDEF"));
    expect(await screen.findByText("Ключ скопирован")).toBeTruthy();
    fireEvent.click(screen.getByTestId("copy-totp-secret-button"));
    expect(await screen.findByText(/Не удалось скопировать ключ/)).toBeTruthy();
  });

  it("changes password in a modal and closes it after success", async () => {
    apiMock.getMe.mockResolvedValue(admin);
    apiMock.changePassword.mockResolvedValue({
      status: "ok",
      message: "Пароль обновлён",
    });
    window.history.replaceState({}, "", "/account/security");
    render(<App />);
    const trigger = await screen.findByRole("button", {
      name: "Изменить пароль",
    });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Смена пароля" });
    const inputs = dialog.querySelectorAll<HTMLInputElement>(
      'input[type="password"]',
    );
    expect(inputs).toHaveLength(3);
    fireEvent.change(inputs[0], { target: { value: "CurrentPassword123!" } });
    fireEvent.change(inputs[1], {
      target: { value: "NewPasswordRegression2026!" },
    });
    fireEvent.change(inputs[2], {
      target: { value: "NewPasswordRegression2026!" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Сохранить новый пароль" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Смена пароля" })).toBeNull(),
    );
    expect(apiMock.changePassword).toHaveBeenCalledWith(
      "CurrentPassword123!",
      "NewPasswordRegression2026!",
    );
    expect(screen.getByText("Пароль обновлён")).toBeTruthy();
  });

  it("shows full audit details and exports the active server filter", async () => {
    apiMock.getMe.mockResolvedValue(admin);
    apiMock.getAuditEvents.mockResolvedValue([
      {
        id: "event-1",
        event_type: "login_failed",
        user_id: null,
        ip_address: "203.0.113.5",
        user_agent: "Synthetic test",
        details: { nested: { reason: "full detail text" } },
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    render(<App />);
    fireEvent.click(
      await screen.findByRole("link", { name: "Администрирование" }),
    );
    fireEvent.click(await screen.findByRole("link", { name: "Журнал аудита" }));
    fireEvent.change(screen.getByTestId("audit-filter-input"), {
      target: { value: "login" },
    });
    await waitFor(() =>
      expect(apiMock.getAuditEvents).toHaveBeenCalledWith(0, 50, "login"),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Показать детали" }),
    );
    expect(
      screen.getByRole("dialog", { name: "Детали события аудита" }).textContent,
    ).toContain("full detail text");
    fireEvent.click(screen.getByRole("button", { name: "Закрыть детали" }));
    fireEvent.click(screen.getByRole("button", { name: "Скачать CSV" }));
    await waitFor(() =>
      expect(apiMock.downloadAudit).toHaveBeenCalledWith("csv", "login"),
    );
  });

  it("keeps passkey and registration controls hidden in the default-off profile", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Войти" });
    expect(screen.queryByTestId("passkey-login-button")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Зарегистрироваться" }),
    ).toBeNull();
    expect(apiMock.getCapabilities).toHaveBeenCalled();
  });

  it("shows enabled controls only from server capabilities", async () => {
    apiMock.getCapabilities.mockResolvedValue({
      ...disabled,
      passkey_enabled: true,
      registration_mode: "open",
    });
    render(<App />);
    expect(await screen.findByTestId("passkey-login-button")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Зарегистрироваться" }),
    ).toBeTruthy();
  });

  it("shows a rejected login error and does not create an account session", async () => {
    apiMock.login.mockRejectedValue(new Error("Неверные учётные данные"));
    render(<App />);
    await screen.findByRole("button", { name: "Войти" });
    await enterPassword();
    expect(await screen.findByText("Неверные учётные данные")).toBeTruthy();
    expect(screen.queryByText("Учётная запись")).toBeNull();
  });

  it("requires the returned MFA method and rejects an invalid TOTP code", async () => {
    apiMock.login.mockResolvedValue({
      mfa_required: true,
      mfa_token: "synthetic-mfa-token",
      available_methods: ["totp"],
    });
    apiMock.verifyTotpLogin.mockRejectedValue(new Error("Неверный код TOTP"));
    render(<App />);
    await screen.findByRole("button", { name: "Войти" });
    await enterPassword();
    const code = await screen.findByLabelText(
      "Одноразовый код или код восстановления",
    );
    expect(screen.queryByTestId("passkey-mfa-button")).toBeNull();
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    expect(await screen.findByText("Неверный код TOTP")).toBeTruthy();
    expect(apiMock.verifyTotpLogin).toHaveBeenCalledWith(
      "123456",
      "synthetic-mfa-token",
    );
    expect(screen.queryByText("Учётная запись")).toBeNull();
  });

  it("limits admin navigation and requires reauthentication before mode changes", async () => {
    apiMock.getMe.mockResolvedValue(admin);
    render(<App />);
    fireEvent.click(
      await screen.findByRole("link", { name: "Администрирование" }),
    );
    fireEvent.click(await screen.findByRole("link", { name: "Конфигурация" }));
    await screen.findByText("Закрыта (closed)");
    const openMode = screen.getByRole("radio", { name: /Открытый режим/ });
    fireEvent.click(openMode);
    const submit = screen.getByRole("button", {
      name: "Применить режим регистрации",
    });
    fireEvent.submit(submit.closest("form")!);
    expect(
      await screen.findByText(
        /Для смены режима регистрации введите пароль администратора/,
      ),
    ).toBeTruthy();
    await waitFor(() =>
      expect(apiMock.updateRegistrationMode).not.toHaveBeenCalled(),
    );
  });

  it("does not expose admin navigation to a normal account", async () => {
    apiMock.getMe.mockResolvedValue({
      ...admin,
      is_superuser: false,
      roles: ["user"],
    });
    render(<App />);
    await screen.findByRole("heading", { name: "Профиль", level: 1 });
    expect(
      screen.queryByRole("link", { name: "Администрирование" }),
    ).toBeNull();
  });
});

// UI contracts use explicit API mocks; PostgreSQL/browser suites verify server security.
describe("redesign routing and feedback regressions", () => {
  it("rejects direct administration navigation for an ordinary server profile", async () => {
    window.history.replaceState({}, "", "/admin/users");
    apiMock.getMe.mockResolvedValue({
      ...admin,
      is_superuser: false,
      roles: ["user"],
    });
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Доступ ограничен" }),
    ).toBeTruthy();
    expect(apiMock.getAdminUsers).not.toHaveBeenCalled();
  });
  it("renders an unknown deep link without falling back to the account", async () => {
    window.history.replaceState({}, "", "/unexpected/deep-link");
    apiMock.getMe.mockResolvedValue(admin);
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Страница не найдена" }),
    ).toBeTruthy();
    await waitFor(() =>
      expect(document.title).toBe("Страница не найдена — ALXPRGS SSO"),
    );
  });
  it("keeps a failed logout visible and permits another attempt", async () => {
    apiMock.getMe.mockResolvedValue(admin);
    apiMock.logout.mockRejectedValueOnce(new Error("Transport unavailable"));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Выйти" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Не удалось завершить сессию. Попробуйте снова.",
    );
    expect(
      screen.getByRole("link", { name: "Администрирование" }),
    ).toBeTruthy();
    apiMock.getMe.mockRejectedValue(new Error("No session"));
    fireEvent.click(screen.getByRole("button", { name: "Выйти" }));
    expect(
      await screen.findByRole("heading", { name: "Вход в ALXPRGS" }),
    ).toBeTruthy();
    expect(apiMock.logout).toHaveBeenCalledTimes(2);
  });
  it("shows and hides the password without submitting credentials", async () => {
    render(<App />);
    const input = await screen.findByLabelText("Пароль", { exact: true });
    fireEvent.change(input, { target: { value: "SyntheticRetainedInput" } });
    fireEvent.click(screen.getByRole("button", { name: "Показать пароль" }));
    expect(input.getAttribute("type")).toBe("text");
    expect(input).toHaveProperty("value", "SyntheticRetainedInput");
    expect(apiMock.login).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Скрыть пароль" }));
    expect(input.getAttribute("type")).toBe("password");
  });
  it("renders server-supplied RP metadata and never query-supplied branding", async () => {
    const authorize =
      "/oauth/authorize?client_id=trusted&redirect_uri=https%3A%2F%2Frp.example.test%2Fcallback&client_name=Forged";
    window.history.replaceState(
      {},
      "",
      "/login?return_to=" + encodeURIComponent(authorize),
    );
    apiMock.getClientContext.mockResolvedValue({
      client_name: "Trusted from server",
      redirect_origin: "https://rp.example.test",
    });
    render(<App />);
    expect(await screen.findByText("Trusted from server")).toBeTruthy();
    expect(screen.queryByText("Forged")).toBeNull();
    expect(apiMock.getClientContext).toHaveBeenCalledWith(
      "trusted",
      "https://rp.example.test/callback",
    );
  });
});

describe("administration form and asynchronous search regressions", () => {
  it("keeps creation failure inside the modal, clears the password on cancel and permits a retry", async () => {
    window.history.replaceState({}, "", "/admin/users");
    apiMock.getMe.mockResolvedValue(admin);
    apiMock.createAdminUser.mockRejectedValueOnce(new Error("Create rejected"));
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Добавить пользователя/ }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Новый пользователь",
    });
    fireEvent.change(
      within(dialog).getByLabelText("Имя пользователя (username)"),
      { target: { value: "synthetic_new" } },
    );
    fireEvent.change(within(dialog).getByLabelText("Email", { exact: true }), {
      target: { value: "new@example.test" },
    });
    fireEvent.change(within(dialog).getByLabelText("Пароль", { exact: true }), {
      target: { value: "SyntheticCreate2026!" },
    });
    fireEvent.submit(
      within(dialog).getByRole("button", { name: "Создать" }).closest("form")!,
    );
    expect(await within(dialog).findByRole("alert")).toBeTruthy();
    await waitFor(() =>
      expect(
        within(dialog)
          .getByRole("button", { name: "Отмена" })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(
      screen.getByRole("button", { name: /Добавить пользователя/ }),
    );
    const retry = await screen.findByRole("dialog", {
      name: "Новый пользователь",
    });
    expect(
      within(retry).getByLabelText("Пароль", { exact: true }),
    ).toHaveProperty("value", "");
    expect(within(retry).queryByRole("alert")).toBeNull();
    apiMock.createAdminUser.mockResolvedValue({});
    fireEvent.change(within(retry).getByLabelText("Пароль", { exact: true }), {
      target: { value: "SyntheticCreate2026!" },
    });
    fireEvent.submit(
      within(retry).getByRole("button", { name: "Создать" }).closest("form")!,
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(apiMock.createAdminUser).toHaveBeenCalledTimes(2);
  });
  it("does not replace current search results with a late previous response", async () => {
    window.history.replaceState({}, "", "/admin/users");
    apiMock.getMe.mockResolvedValue(admin);
    let resolvePrevious!: (value: unknown[]) => void;
    apiMock.getAdminUsers.mockImplementation(
      (_offset: number, _limit: number, query?: string) => {
        if (query === "previous")
          return new Promise((resolve) => {
            resolvePrevious = resolve;
          });
        if (query === "current")
          return Promise.resolve([
            {
              ...admin,
              username: "current_result",
              updated_at: admin.created_at,
            },
          ]);
        return Promise.resolve([]);
      },
    );
    render(<App />);
    const search = await screen.findByPlaceholderText(/Поиск/);
    fireEvent.change(search, { target: { value: "previous" } });
    await waitFor(() => expect(resolvePrevious).toBeTypeOf("function"));
    fireEvent.change(search, { target: { value: "current" } });
    await screen.findByText("current_result");
    resolvePrevious([
      { ...admin, username: "previous_result", updated_at: admin.created_at },
    ]);
    await waitFor(() =>
      expect(screen.queryByText("previous_result")).toBeNull(),
    );
    expect(screen.getByText("current_result")).toBeTruthy();
  });
});
