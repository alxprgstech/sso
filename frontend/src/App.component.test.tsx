import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import type { Capabilities, UserProfile } from "./types/api";

vi.mock("qrcode.react", () => ({
  QRCodeSVG: ({ value }: { value: string }) => <svg data-testid="qr-renderer" data-value={value} />,
}));

const apiMock = vi.hoisted(() => ({
  getCapabilities: vi.fn(),
  getMe: vi.fn(),
  login: vi.fn(),
  verifyTotpLogin: vi.fn(),
  verifyRecoveryCodeLogin: vi.fn(),
  getSessions: vi.fn(),
  getAdminUsers: vi.fn(),
  getSystemStatus: vi.fn(),
  updateRegistrationMode: vi.fn(),
  changePassword: vi.fn(),
  getAuditEvents: vi.fn(),
  downloadAudit: vi.fn(),
  setupTotp: vi.fn(),
}));
vi.mock("./api/client", () => ({ api: apiMock }));

const disabled: Capabilities = {
  totp_enabled: false,
  passkey_enabled: false,
  recovery_codes_enabled: false,
  email_verification_enabled: false,
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
};

beforeEach(() => {
  vi.resetAllMocks();
  window.history.replaceState({}, "", "/login");
  apiMock.getCapabilities.mockResolvedValue(disabled);
  apiMock.getMe.mockRejectedValue(new Error("No session"));
  apiMock.getSessions.mockResolvedValue([]);
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
  const password = document.querySelector<HTMLInputElement>('input[type="password"]');
  expect(password).not.toBeNull();
  fireEvent.change(username, { target: { value: "synthetic_user" } });
  fireEvent.change(password!, { target: { value: "synthetic_password" } });
  fireEvent.click(screen.getByRole("button", { name: "Войти" }));
}

describe("server capabilities and account flows", () => {
  it("does not expose TOTP setup or QR when the server flag is disabled", async () => {
    apiMock.getMe.mockResolvedValue(admin);
    render(<App />);
    await screen.findByTestId("totp-section");
    expect(screen.queryByTestId("totp-qr-code")).toBeNull();
    expect(screen.queryByTestId("copy-totp-secret-button")).toBeNull();
    expect(screen.queryByRole("button", { name: "Настроить TOTP" })).toBeNull();
  });

  it("renders the server TOTP provisioning URI as QR and copies only the secret", async () => {
    const provisioningUri = "otpauth://totp/ALXPRGS%20SSO:admin%40example.test?secret=ABCDEF&issuer=ALXPRGS%20SSO";
    const writeText = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("Denied"));
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    apiMock.getMe.mockResolvedValue(admin);
    apiMock.getCapabilities.mockResolvedValue({ ...disabled, totp_enabled: true });
    apiMock.setupTotp.mockResolvedValue({ secret: "ABCDEF", otpauth_url: provisioningUri });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Настроить TOTP" }));
    expect((await screen.findByTestId("qr-renderer")).getAttribute("data-value")).toBe(provisioningUri);
    expect(screen.getByTestId("totp-secret").textContent).toContain("ABCDEF");
    fireEvent.click(screen.getByTestId("copy-totp-secret-button"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("ABCDEF"));
    expect(await screen.findByText("Ключ скопирован")).toBeTruthy();
    fireEvent.click(screen.getByTestId("copy-totp-secret-button"));
    expect(await screen.findByText(/Не удалось скопировать ключ/)).toBeTruthy();
  });

  it("changes password in a modal and closes it after success", async () => {
    apiMock.getMe.mockResolvedValue(admin);
    apiMock.changePassword.mockResolvedValue({ status: "ok", message: "Пароль обновлён" });
    render(<App />);
    const trigger = await screen.findByRole("button", { name: "Изменить пароль" });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Смена пароля" });
    const inputs = dialog.querySelectorAll<HTMLInputElement>('input[type="password"]');
    expect(inputs).toHaveLength(3);
    fireEvent.change(inputs[0], { target: { value: "CurrentPassword123!" } });
    fireEvent.change(inputs[1], { target: { value: "NewPassword123!" } });
    fireEvent.change(inputs[2], { target: { value: "NewPassword123!" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить новый пароль" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Смена пароля" })).toBeNull());
    expect(apiMock.changePassword).toHaveBeenCalledWith("CurrentPassword123!", "NewPassword123!");
    expect(screen.getByText("Пароль обновлён")).toBeTruthy();
  });

  it("shows full audit details and exports the active server filter", async () => {
    apiMock.getMe.mockResolvedValue(admin);
    apiMock.getAuditEvents.mockResolvedValue([{
      id: "event-1", event_type: "login_failed", user_id: null, ip_address: "203.0.113.5", user_agent: "Synthetic test",
      details: { nested: { reason: "full detail text" } }, created_at: "2026-01-01T00:00:00Z",
    }]);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Администрирование" }));
    fireEvent.click(screen.getByRole("button", { name: "Журнал аудита" }));
    fireEvent.change(screen.getByTestId("audit-filter-input"), { target: { value: "login" } });
    await waitFor(() => expect(apiMock.getAuditEvents).toHaveBeenCalledWith(0, 50, "login"));
    fireEvent.click(await screen.findByRole("button", { name: "Показать детали" }));
    expect(screen.getByRole("dialog", { name: "Детали события аудита" }).textContent).toContain("full detail text");
    fireEvent.click(screen.getByRole("button", { name: "Скачать CSV" }));
    await waitFor(() => expect(apiMock.downloadAudit).toHaveBeenCalledWith("csv", "login"));
  });

  it("keeps passkey and registration controls hidden in the default-off profile", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Войти" });
    expect(screen.queryByTestId("passkey-login-button")).toBeNull();
    expect(screen.queryByRole("button", { name: "Зарегистрироваться" })).toBeNull();
    expect(screen.getByText("Закрыта (по умолчанию)")).toBeTruthy();
  });

  it("shows enabled controls only from server capabilities", async () => {
    apiMock.getCapabilities.mockResolvedValue({ ...disabled, passkey_enabled: true, registration_mode: "open" });
    render(<App />);
    expect(await screen.findByTestId("passkey-login-button")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Зарегистрироваться" })).toBeTruthy();
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
    apiMock.login.mockResolvedValue({ mfa_required: true, mfa_token: "synthetic-mfa-token", available_methods: ["totp"] });
    apiMock.verifyTotpLogin.mockRejectedValue(new Error("Неверный код TOTP"));
    render(<App />);
    await screen.findByRole("button", { name: "Войти" });
    await enterPassword();
    const code = await screen.findByPlaceholderText("000000");
    expect(screen.queryByTestId("passkey-mfa-button")).toBeNull();
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    expect(await screen.findByText("Неверный код TOTP")).toBeTruthy();
    expect(apiMock.verifyTotpLogin).toHaveBeenCalledWith("123456", "synthetic-mfa-token");
    expect(screen.queryByText("Учётная запись")).toBeNull();
  });

  it("limits admin navigation and requires reauthentication before mode changes", async () => {
    apiMock.getMe.mockResolvedValue(admin);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Администрирование" }));
    fireEvent.click(screen.getByRole("button", { name: "Конфигурация" }));
    await screen.findByText("Закрыта (closed)");
    const openMode = screen.getByRole("radio", { name: /Открытый режим/ });
    fireEvent.click(openMode);
    const submit = screen.getByRole("button", { name: "Применить режим регистрации" });
    fireEvent.submit(submit.closest("form")!);
    expect(await screen.findByText(/Для смены режима регистрации введите пароль администратора/)).toBeTruthy();
    await waitFor(() => expect(apiMock.updateRegistrationMode).not.toHaveBeenCalled());
  });

  it("does not expose admin navigation to a normal account", async () => {
    apiMock.getMe.mockResolvedValue({ ...admin, is_superuser: false, roles: ["user"] });
    render(<App />);
    await screen.findByText("Учётная запись");
    expect(screen.queryByRole("button", { name: "Администрирование" })).toBeNull();
  });
});
