import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AdminMfaPage } from "./AdminMfaPage";
import type { UserProfile } from "../types/api";

const apiMock = vi.hoisted(() => ({
  setupTotp: vi.fn(),
  confirmTotp: vi.fn(),
  elevateSession: vi.fn(),
  getPasskeyRegistrationOptions: vi.fn(),
  verifyPasskeyRegistration: vi.fn(),
  getSessionElevationPasskeyOptions: vi.fn(),
}));
const refreshUser = vi.hoisted(() => vi.fn());
let currentUser: UserProfile;

vi.mock("../api/client", () => ({ api: apiMock }));
vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ user: currentUser, refreshUser }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const baseUser: UserProfile = {
  id: "admin-id",
  username: "admin",
  email: "admin@example.test",
  is_active: true,
  is_superuser: true,
  email_verified: true,
  roles: ["admin"],
  has_totp: false,
  has_passkey: false,
  created_at: "2026-01-01T00:00:00Z",
  mfa_verified: false,
  admin_mfa_required: true,
  session_purpose: "admin_mfa_enrollment",
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <Routes>
        <Route path="/admin" element={<AdminMfaPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

it("requires enrolment and never renders the admin panel", async () => {
  currentUser = { ...baseUser };
  apiMock.setupTotp.mockResolvedValue({
    secret: "JBSWY3DPEHPK3PXP",
    otpauth_url: "otpauth://totp/ALXPRGS:admin?secret=JBSWY3DPEHPK3PXP",
  });
  renderPage();
  expect(
    screen.getByText(
      "Для доступа к панели администратора необходимо настроить двухфакторную аутентификацию и подтвердить её в этой сессии.",
    ),
  ).toBeTruthy();
  expect(screen.queryByText("Административная панель")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Настроить TOTP" }));
  await waitFor(() => expect(apiMock.setupTotp).toHaveBeenCalled());
  expect(await screen.findByText("JBSWY3DPEHPK3PXP")).toBeTruthy();
  expect(screen.getByRole("img", { name: "QR-код для подключения администратора" })).toBeTruthy();
});

it("confirms TOTP enrolment and then elevates the exact session", async () => {
  currentUser = { ...baseUser, has_totp: true };
  apiMock.elevateSession.mockResolvedValue({
    ...baseUser,
    has_totp: true,
    mfa_verified: true,
    admin_mfa_required: false,
    session_purpose: "full",
  });
  renderPage();
  expect(screen.getByText("Подтвердите второй фактор")).toBeTruthy();
  fireEvent.change(
    screen.getByLabelText("Код из приложения-аутентификатора"),
    { target: { value: "123456" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Подтвердить TOTP" }),
  );
  await waitFor(() =>
    expect(apiMock.elevateSession).toHaveBeenCalledWith("totp", {
      code: "123456",
    }),
  );
  expect(refreshUser).toHaveBeenCalled();
});

it("does not show admin content to a non-admin", () => {
  currentUser = {
    ...baseUser,
    is_superuser: false,
    roles: ["user"],
    admin_mfa_required: false,
  };
  renderPage();
  expect(screen.getByText("Доступ ограничен")).toBeTruthy();
});
