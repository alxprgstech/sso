import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import {
  PasskeyControls,
  RecoveryControls,
  type AccountViewModel,
} from "./AccountSections";

vi.mock("qrcode.react", () => ({
  QRCodeSVG: () => <svg data-testid="qr-renderer" />,
}));

const downloadedBlobs: Blob[] = [];

const user = {
  id: "synthetic-user",
  username: "user_test",
  email: "user@example.test",
  is_active: true,
  is_superuser: false,
  email_verified: true,
  roles: ["user"],
  has_totp: false,
  has_passkey: true,
  created_at: "2026-01-01T00:00:00Z",
  legal_acceptance_required: false,
  deletion_pending: false,
  session_purpose: "full",
};

function controller(overrides: Record<string, unknown> = {}) {
  return {
    user,
    capabilities: {},
    recoveryCodes: null,
    recoveryLoading: false,
    recoverySuccess: null,
    recoveryError: null,
    handleGenerateRecoveryCodes: vi.fn(),
    passkeyName: "",
    setPasskeyName: vi.fn(),
    passkeyLoading: false,
    passkeySuccess: null,
    passkeyError: null,
    passkeyWarning: null,
    passkeyNamingOpen: false,
    passkeyNoNameConfirmOpen: false,
    passkeyNameRef: { current: null },
    passkeys: [],
    passkeysReadState: "ready",
    fetchPasskeys: vi.fn(),
    handleStartPasskeyRegistration: vi.fn(),
    handlePasskeyNameSubmit: vi.fn(),
    handleReturnToPasskeyName: vi.fn(),
    handleConfirmEmptyPasskeyName: vi.fn(),
    handleCancelPasskeyNaming: vi.fn(),
    handleDeletePasskey: vi.fn(),
    ...overrides,
  } as unknown as AccountViewModel;
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  downloadedBlobs.length = 0;
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: (blob: Blob) => {
      downloadedBlobs.push(blob);
      return "blob:synthetic";
    },
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("recovery codes export UI", () => {
  it("allows generation with a confirmed Passkey and no TOTP", () => {
    render(<RecoveryControls controller={controller()} />);
    expect(
      screen.getByTestId("generate-recovery-codes-button"),
    ).not.toBeNull();
    expect(
      screen.queryByText(/требуют подтверждённого TOTP или Passkey/),
    ).toBeNull();
  });

  it("keeps generation unavailable without TOTP and Passkey", () => {
    render(
      <RecoveryControls
        controller={controller({
          user: { ...user, has_totp: false, has_passkey: false },
        })}
      />,
    );
    expect(screen.queryByTestId("generate-recovery-codes-button")).toBeNull();
    expect(
      screen.getByText(/требуют подтверждённого TOTP или Passkey/),
    ).not.toBeNull();
  });

  it("downloads the current full set with the account email", async () => {
    const codes = ["AAAA-BBBB-CCCC-DDDD", "EEEE-FFFF-GGGG-HHHH"];
    render(
      <RecoveryControls
        controller={controller({
          recoveryCodes: codes,
          recoverySuccess: "Коды сформированы",
        })}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Копировать все коды" }),
    ).not.toBeNull();
    fireEvent.click(screen.getByTestId("download-recovery-codes-button"));
    expect(downloadedBlobs).toHaveLength(1);
    const text = await downloadedBlobs[0].text();
    expect(text).toContain("Учётная запись: user@example.test");
    expect(text).toContain(codes[0]);
    expect(text).toContain(codes[1]);
    expect(text).toContain("ИНСТРУКЦИЯ");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("shows the download action only with the current displayed set", () => {
    render(<RecoveryControls controller={controller()} />);
    expect(screen.queryByTestId("download-recovery-codes-button")).toBeNull();
  });
});

describe("passkey naming UI", () => {
  it("starts WebAuthn without asking for a name first", () => {
    const start = vi.fn();
    render(
      <PasskeyControls
        controller={controller({ handleStartPasskeyRegistration: start })}
      />,
    );
    expect(screen.queryByTestId("passkey-name-input")).toBeNull();
    fireEvent.click(screen.getByTestId("register-passkey-button"));
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("shows the naming dialog after credential creation", () => {
    const submit = vi.fn();
    render(
      <PasskeyControls
        controller={controller({
          passkeyNamingOpen: true,
          passkeyName: "Passkey на этом устройстве",
          handlePasskeyNameSubmit: submit,
        })}
      />,
    );
    const dialog = screen.getByRole("dialog", {
      name: "Название нового ключа доступа",
    });
    const nameInput = within(dialog).getByLabelText(
      "Название Passkey",
    ) as HTMLInputElement;
    expect(nameInput.value).toBe("Passkey на этом устройстве");
    fireEvent.click(screen.getByTestId("passkey-name-continue-button"));
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("returns to naming from the empty-name confirmation", () => {
    const back = vi.fn();
    const proceed = vi.fn();
    render(
      <PasskeyControls
        controller={controller({
          passkeyNoNameConfirmOpen: true,
          handleReturnToPasskeyName: back,
          handleConfirmEmptyPasskeyName: proceed,
        })}
      />,
    );
    const dialog = screen.getByRole("dialog", {
      name: "Продолжить без названия?",
    });
    expect(
      within(dialog).getByText(/система автоматически присвоит ему название/),
    ).not.toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Вернуться" }));
    expect(back).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Продолжить" }));
    expect(proceed).toHaveBeenCalledTimes(1);
  });

  it("cancels naming without reporting success", () => {
    const cancel = vi.fn();
    render(
      <PasskeyControls
        controller={controller({
          passkeyNamingOpen: true,
          handleCancelPasskeyNaming: cancel,
        })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("passkey-success")).toBeNull();
  });
});
