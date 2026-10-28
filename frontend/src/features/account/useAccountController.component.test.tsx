import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAccountController } from "./useAccountController";

const apiMock = vi.hoisted(() => ({
  getPasskeyRegistrationOptions: vi.fn(),
  verifyPasskeyRegistration: vi.fn(),
  getPasskeyCredentials: vi.fn(),
}));
const authMock = vi.hoisted(() => ({
  user: {
    id: "synthetic-user",
    username: "user_test",
    email: "user@example.test",
    has_totp: false,
    has_passkey: false,
  },
  capabilities: { passkey_enabled: true },
  refreshUser: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../api/client", () => ({ api: apiMock }));
vi.mock("../../context/AuthContext", () => ({ useAuth: () => authMock }));
vi.mock("../../components/ui/Feedback", () => ({
  useFeedback: () => ({ confirm: vi.fn(), notify: vi.fn() }),
}));
vi.mock("react-router", () => ({
  useParams: () => ({ section: "security" }),
}));

const createMock = vi.fn();

function fakeCredential(
  attachment: AuthenticatorAttachment | null = "platform",
  transports: AuthenticatorTransport[] = ["internal"],
) {
  return {
    id: "credential-id",
    rawId: new Uint8Array([1, 2, 3]).buffer,
    type: "public-key",
    authenticatorAttachment: attachment,
    response: {
      clientDataJSON: new Uint8Array([4]).buffer,
      attestationObject: new Uint8Array([5]).buffer,
      getTransports: () => transports,
    },
  };
}

const creationOptions = {
  challenge: "AA",
  rp: { id: "localhost", name: "ALXPRGS" },
  user: { id: "AA", name: "user", displayName: "User" },
  pubKeyCredParams: [],
};

const submitEvent = () =>
  ({ preventDefault: vi.fn() }) as unknown as React.FormEvent;

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.getPasskeyRegistrationOptions.mockResolvedValue(creationOptions);
  apiMock.getPasskeyCredentials.mockResolvedValue([]);
  apiMock.verifyPasskeyRegistration.mockResolvedValue({
    status: "ok",
    message: "Passkey успешно зарегистрирован",
  });
  authMock.refreshUser.mockResolvedValue(undefined);
  createMock.mockResolvedValue(fakeCredential());
  Object.defineProperty(navigator, "credentials", {
    configurable: true,
    value: { create: createMock },
  });
});
afterEach(() => {
  Reflect.deleteProperty(navigator, "credentials");
});

describe("useAccountController passkey registration", () => {
  it("creates the credential first and only then opens the naming dialog", async () => {
    const { result } = renderHook(() => useAccountController());
    await waitFor(() => expect(result.current.passkeysReadState).toBe("ready"));

    await act(async () => {
      await result.current.handleStartPasskeyRegistration();
    });

    expect(createMock).toHaveBeenCalledTimes(1);
    expect(result.current.passkeyNamingOpen).toBe(true);
    expect(result.current.passkeyName).toBe("Passkey на этом устройстве");
    expect(apiMock.verifyPasskeyRegistration).not.toHaveBeenCalled();
  });

  it("verifies the pending credential with the edited name before success", async () => {
    const { result } = renderHook(() => useAccountController());
    await act(async () => {
      await result.current.handleStartPasskeyRegistration();
    });
    act(() => result.current.setPasskeyName("  Мой ноутбук  "));
    await act(async () => {
      await result.current.handlePasskeyNameSubmit(submitEvent());
    });

    expect(apiMock.verifyPasskeyRegistration).toHaveBeenCalledWith(
      expect.objectContaining({ id: "credential-id" }),
      "Мой ноутбук",
    );
    expect(result.current.passkeySuccess).toBe(
      "Passkey успешно зарегистрирован",
    );
    expect(result.current.passkeyNamingOpen).toBe(false);
    expect(authMock.refreshUser).toHaveBeenCalledTimes(1);
  });

  it("requires confirmation for an empty name and generates a local timestamp name", async () => {
    const { result } = renderHook(() => useAccountController());
    await act(async () => {
      await result.current.handleStartPasskeyRegistration();
    });
    act(() => result.current.setPasskeyName("   "));
    await act(async () => {
      await result.current.handlePasskeyNameSubmit(submitEvent());
    });

    expect(apiMock.verifyPasskeyRegistration).not.toHaveBeenCalled();
    expect(result.current.passkeyNamingOpen).toBe(false);
    expect(result.current.passkeyNoNameConfirmOpen).toBe(true);

    await act(async () => {
      await result.current.handleConfirmEmptyPasskeyName();
    });

    expect(apiMock.verifyPasskeyRegistration).toHaveBeenCalledTimes(1);
    expect(apiMock.verifyPasskeyRegistration.mock.calls[0][1]).toMatch(
      /^Passkey_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$/,
    );
    expect(result.current.passkeyNoNameConfirmOpen).toBe(false);
    expect(result.current.passkeySuccess).toBeTruthy();
  });

  it("returns to naming without creating another credential", async () => {
    const { result } = renderHook(() => useAccountController());
    await act(async () => {
      await result.current.handleStartPasskeyRegistration();
    });
    act(() => result.current.setPasskeyName(""));
    await act(async () => {
      await result.current.handlePasskeyNameSubmit(submitEvent());
    });
    act(() => result.current.handleReturnToPasskeyName());

    expect(result.current.passkeyNamingOpen).toBe(true);
    expect(result.current.passkeyNoNameConfirmOpen).toBe(false);
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(apiMock.verifyPasskeyRegistration).not.toHaveBeenCalled();
  });

  it("warns on cancellation and never reports success", async () => {
    const { result } = renderHook(() => useAccountController());
    await act(async () => {
      await result.current.handleStartPasskeyRegistration();
    });
    act(() => result.current.handleCancelPasskeyNaming());

    expect(result.current.passkeyNamingOpen).toBe(false);
    expect(result.current.passkeySuccess).toBeNull();
    expect(result.current.passkeyWarning).toMatch(/не завершена/);
    expect(apiMock.verifyPasskeyRegistration).not.toHaveBeenCalled();
  });

  it("reports a backend failure with the unused-key warning", async () => {
    apiMock.verifyPasskeyRegistration.mockRejectedValue(
      new Error("Ошибка проверки регистрации"),
    );
    const { result } = renderHook(() => useAccountController());
    await act(async () => {
      await result.current.handleStartPasskeyRegistration();
    });
    act(() => result.current.setPasskeyName("Ключ"));
    await act(async () => {
      await result.current.handlePasskeyNameSubmit(submitEvent());
    });

    expect(result.current.passkeySuccess).toBeNull();
    expect(result.current.passkeyError).toBe("Ошибка проверки регистрации");
    expect(result.current.passkeyWarning).toMatch(/мог остаться/);
    expect(result.current.passkeyNamingOpen).toBe(false);
  });

  it("sends the verification request only once on double submit", async () => {
    let resolveVerify: ((value: { status: string; message: string }) => void) | undefined;
    apiMock.verifyPasskeyRegistration.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveVerify = resolve;
        }),
    );
    const { result } = renderHook(() => useAccountController());
    await act(async () => {
      await result.current.handleStartPasskeyRegistration();
    });
    act(() => result.current.setPasskeyName("Ключ"));

    await act(async () => {
      const first = result.current.handlePasskeyNameSubmit(submitEvent());
      const second = result.current.handlePasskeyNameSubmit(submitEvent());
      resolveVerify?.({ status: "ok", message: "Passkey успешно зарегистрирован" });
      await Promise.all([first, second]);
    });

    expect(apiMock.verifyPasskeyRegistration).toHaveBeenCalledTimes(1);
  });
});
