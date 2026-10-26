import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { StepUpPage } from "./StepUpPage";

const apiMock = vi.hoisted(() => ({
  getStepUpRequest: vi.fn(),
  getStepUpPasskeyOptions: vi.fn(),
  verifyStepUpFactor: vi.fn(),
  denyStepUpRequest: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("../api/client", () => {
  class ApiError extends Error {
    readonly name = "ApiError";
    constructor(
      message: string,
      readonly status: number,
      readonly code: string,
      readonly route = "",
    ) {
      super(message);
    }
  }
  return { api: apiMock, ApiError };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const TOKEN = "abcdefghijklmnopqrstuvwxyz123456"; // pragma: allowlist secret

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/step-up/${TOKEN}`]}>
      <Routes>
        <Route path="/step-up/:token" element={<StepUpPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

it("shows the trusted client and bound operation, then denies without proof", async () => {
  apiMock.getStepUpRequest.mockResolvedValue({
    client_name: "Synthetic RP",
    action: "critical_settings_change",
    description: "Изменение критических настроек приложения",
    payload_hash: "a".repeat(64),
    assurance: "reauth_basic",
    assurance_label: "Базовая повторная проверка",
    plans: [
      {
        id: "password",
        label: "Текущий пароль",
        methods: ["password"],
      },
    ],
    verified_methods: [],
    plan: null,
    status: "pending",
    passkey_enabled: false,
    expires_at: new Date(Date.now() + 120000).toISOString(),
  });
  apiMock.denyStepUpRequest.mockResolvedValue({ status: "denied" });

  renderPage();

  expect(await screen.findByText("Synthetic RP")).toBeTruthy();
  expect(screen.getByText("Изменение критических настроек приложения")).toBeTruthy();
  expect(screen.getByText("critical_settings_change")).toBeTruthy();
  expect(screen.getByLabelText("Текущий пароль")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Отменить действие" }));
  expect(await screen.findByText("Действие отменено")).toBeTruthy();
  expect(apiMock.denyStepUpRequest).toHaveBeenCalledWith(TOKEN);
});

it("does not render a challenge for an invalid step-up URL", async () => {
  render(
    <MemoryRouter initialEntries={["/step-up/short"]}>
      <Routes>
        <Route path="/step-up/:token" element={<StepUpPage />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText("Некорректная ссылка подтверждения.")).toBeTruthy();
  expect(apiMock.getStepUpRequest).not.toHaveBeenCalled();
});
