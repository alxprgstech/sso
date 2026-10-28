import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { webcrypto } from "node:crypto";
import { api } from "../api/client";
import { ReauthenticationDialog } from "./ReauthenticationDialog";

afterEach(() => {
  cleanup();
  api.setReauthenticationHandler(null);
  api.setCsrfToken(null);
  vi.unstubAllGlobals();
});

it("queues concurrent sensitive operations instead of failing the second dialog", async () => {
  // Complete the lazy dialog import before asserting its rendered state.
  await import("../components/ui/Dialog");
  api.setCsrfToken("synthetic-csrf");
  vi.stubGlobal("crypto", webcrypto);
  const started: string[] = [];
  const completed: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options: RequestInit = {}) => {
      const grant = new Headers(options.headers).get("X-Reauthentication");
      if (url === "/api/v1/auth/reauthentication") {
        started.push("prompt");
        return new Response(
          JSON.stringify({
            authorization: `synthetic-${started.length}`,
            factor_required: false,
            expires_at: new Date(Date.now() + 300_000).toISOString(),
          }),
          { status: 200 },
        );
      }
      if (!grant) {
        return new Response(JSON.stringify({ error: "reauthentication_required" }), {
          status: 401,
        });
      }
      completed.push(url);
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    }),
  );

  render(<ReauthenticationDialog />);
  const first = api.revokeSession("11111111-1111-1111-1111-111111111111");
  const second = api.revokeSession("22222222-2222-2222-2222-222222222222");
  const dialog = await screen.findByRole("dialog", {
    name: "Подтверждение чувствительной операции",
  });
  expect(dialog).toBeTruthy();

  fireEvent.change(screen.getByLabelText("Текущий пароль"), {
    target: { value: "synthetic-password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
  await waitFor(() => expect(started).toHaveLength(1));

  // The first proof resolves its request and the queued action immediately
  // gets its own prompt instead of an "wait for the current confirmation" error.
  await waitFor(() =>
    expect(screen.getByLabelText("Текущий пароль")).toHaveProperty("value", ""),
  );
  await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("Текущий пароль"), {
    target: { value: "synthetic-password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));

  await expect(Promise.all([first, second])).resolves.toEqual([undefined, undefined]);
  expect(started).toHaveLength(2);
  expect(completed).toEqual([
    "/api/v1/auth/sessions/11111111-1111-1111-1111-111111111111",
    "/api/v1/auth/sessions/22222222-2222-2222-2222-222222222222",
  ]);
});

it("shows the one-time-code hint and a countdown after a spent TOTP step", async () => {
  await import("../components/ui/Dialog");
  api.setCsrfToken("synthetic-csrf");
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/v1/auth/reauthentication") {
        return new Response(
          JSON.stringify({
            authorization: "synthetic-authorization",
            factor_required: true,
            methods: ["totp"],
            expires_at: new Date(Date.now() + 300_000).toISOString(),
          }),
          { status: 200 },
        );
      }
      if (url === "/api/v1/auth/reauthentication/factor") {
        return new Response(
          JSON.stringify({
            error: "totp_code_reused",
            detail: "Этот код уже был использован. Введите следующий код из приложения-аутентификатора.",
            retry_after: 12,
          }),
          { status: 401 },
        );
      }
      return new Response(JSON.stringify({ error: "reauthentication_required" }), {
        status: 401,
      });
    }),
  );

  render(<ReauthenticationDialog />);
  const request = api.revokeSession("33333333-3333-3333-3333-333333333333");
  request.catch(() => undefined);
  await screen.findByRole("dialog");
  fireEvent.change(screen.getByLabelText("Текущий пароль"), {
    target: { value: "synthetic-password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
  fireEvent.change(await screen.findByLabelText("Код подтверждения"), {
    target: { value: "123456" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
  expect(
    await screen.findByText(/Этот код уже был использован/),
  ).toBeTruthy();
  expect(await screen.findByText(/Следующий код будет принят через \d+ с/)).toBeTruthy();
  expect(
    screen.getByText(/Код одноразовый: он принимается только один раз/),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
  await expect(request).rejects.toThrow("Операция отменена");
});
