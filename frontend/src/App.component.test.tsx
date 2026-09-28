import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import type { Capabilities, UserProfile } from "./types/api";

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
