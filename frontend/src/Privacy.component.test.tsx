import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CookieBanner, LegalFooter } from "./components/PrivacyControls";
import { AccessibleDialog } from "./components/AccessibleDialog";
import {
  permitsDiagnostics,
  permitsReplay,
  PRIVACY_KEY,
  readPrivacyChoice,
  savePrivacyChoice,
} from "./telemetry/consent";
import { initializeTelemetry } from "./telemetry/sentry";
import type { TelemetryConfig } from "./types/api";

beforeEach(() => {
  localStorage.clear();
  savePrivacyChoice(false, false);
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  savePrivacyChoice(false, false);
  localStorage.clear();
});

describe("browser-only privacy choice", () => {
  it("defaults to no diagnostics, rejects malformed/expired choices, and records only flags", () => {
    expect(permitsDiagnostics()).toBe(false);
    savePrivacyChoice(true, false);
    expect(permitsDiagnostics()).toBe(true);
    expect(permitsReplay()).toBe(false);
    const stored = JSON.parse(localStorage.getItem(PRIVACY_KEY)!);
    expect(Object.keys(stored).sort()).toEqual([
      "diagnostics",
      "expiresAt",
      "replay",
      "version",
    ]);
    localStorage.setItem(
      PRIVACY_KEY,
      JSON.stringify({ ...stored, expiresAt: Date.now() - 1 }),
    );
    expect(readPrivacyChoice()).toBeNull();
    localStorage.setItem(PRIVACY_KEY, "invalid JSON");
    expect(permitsDiagnostics()).toBe(false);
    savePrivacyChoice(false, true);
    expect(permitsReplay()).toBe(false);
  });
  it("honors revocation even when storage writes fail and old permission remains on disk", () => {
    savePrivacyChoice(true, true);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Unavailable");
    });
    expect(savePrivacyChoice(false, false)).toBe(false);
    expect(permitsDiagnostics()).toBe(false);
    expect(permitsReplay()).toBe(false);
  });
  it("does not initialize the real Sentry SDK before diagnostics consent", () => {
    const config: TelemetryConfig = {
      enabled: true,
      dsn: "https://public@o1.ingest.de.sentry.io/1",
      environment: "production",
      traces_sample_rate: 0,
      replay_enabled: false,
      replays_session_sample_rate: 0,
      replays_on_error_sample_rate: 0,
      trace_propagation_targets: [],
    };
    expect(initializeTelemetry(config)).toBe(false);
  });
  it("separates staging Replay, diagnostics, refusal, and cross-tab updates", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          enabled: true,
          environment: "staging",
          replay_enabled: true,
        }),
      ),
    );
    render(
      <>
        <LegalFooter />
        <CookieBanner />
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Настроить" }));
    const diagnostics = screen.getByRole("checkbox", {
      name: /Диагностика ошибок/,
    });
    const replay = screen.getByRole("checkbox", {
      name: /Запись сессии/,
    }) as HTMLInputElement;
    expect(replay.disabled).toBe(true);
    fireEvent.click(diagnostics);
    await waitFor(() => expect(replay.disabled).toBe(false));
    expect(replay.checked).toBe(false);
    fireEvent.click(replay);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить выбор" }));
    expect(permitsReplay()).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Настройки cookies" }));
    fireEvent.click(screen.getByRole("button", { name: "Только необходимые" }));
    expect(permitsDiagnostics()).toBe(false);
    localStorage.removeItem(PRIVACY_KEY);
    fireEvent(
      window,
      new StorageEvent("storage", { key: PRIVACY_KEY, newValue: null }),
    );
    expect(
      screen.getByRole("heading", { name: "Cookies и диагностика" }),
    ).toBeTruthy();
  });
});

it("traps Tab/Shift+Tab, closes on Escape and returns focus to the trigger", async () => {
  const keyboard = userEvent.setup();
  function DialogFixture() {
    const [open, setOpen] = React.useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>Открыть</button>
        {open && (
          <AccessibleDialog
            label="Проверка"
            onClose={() => setOpen(false)}
            className="test"
          >
            <button>Первый</button>
            <button>Последний</button>
          </AccessibleDialog>
        )}
      </>
    );
  }
  render(<DialogFixture />);
  const trigger = screen.getByRole("button", { name: "Открыть" });
  trigger.focus();
  fireEvent.click(trigger);
  const first = screen.getByRole("button", { name: "Первый" });
  const last = screen.getByRole("button", { name: "Последний" });
  expect(document.activeElement).toBe(first);
  await keyboard.tab({ shift: true });
  expect(document.activeElement).toBe(last);
  await keyboard.tab();
  expect(document.activeElement).toBe(first);
  await keyboard.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  await waitFor(() => expect(document.activeElement).toBe(trigger));
});

it("keeps an empty busy dialog focused, handles dynamic controls and disconnected triggers", async () => {
  const keyboard = userEvent.setup();
  const onClose = vi.fn();
  const trigger = document.createElement("button");
  document.body.append(trigger);
  trigger.focus();
  const view = render(
    <AccessibleDialog
      label="Динамический"
      onClose={onClose}
      className="test"
      busy
    >
      <span>Ожидание</span>
    </AccessibleDialog>,
  );
  const dialog = screen.getByRole("dialog");
  expect(document.activeElement).toBe(dialog);
  await keyboard.tab({ shift: true });
  expect(document.activeElement).toBe(dialog);
  await keyboard.keyboard("{Escape}");
  expect(onClose).not.toHaveBeenCalled();
  view.rerender(
    <AccessibleDialog label="Динамический" onClose={onClose} className="test">
      <button disabled>Недоступен</button>
      <div hidden>
        <button>Скрыт</button>
      </div>
      <button>Новый</button>
    </AccessibleDialog>,
  );
  trigger.focus();
  await keyboard.tab();
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "Новый" }),
  );
  await keyboard.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalledOnce();
  trigger.remove();
  view.unmount();
  expect(document.activeElement).toBe(document.body);
});

it("keeps a parent portal inert only while the nested confirmation is mounted", async () => {
  const keyboard = userEvent.setup();
  function NestedFixture() {
    const [nested, setNested] = React.useState(false);
    return (
      <AccessibleDialog label="Родитель" onClose={() => undefined}>
        <button onClick={() => setNested(true)}>Подтвердить доступ</button>
        {nested && (
          <AccessibleDialog label="Второй" onClose={() => setNested(false)}>
            <button>Внутренний</button>
          </AccessibleDialog>
        )}
      </AccessibleDialog>
    );
  }
  render(<NestedFixture />);
  const parent = screen.getByRole("dialog", { name: "Родитель" });
  const trigger = screen.getByRole("button", { name: "Подтвердить доступ" });
  trigger.focus();
  fireEvent.click(trigger);
  const nested = await screen.findByRole("dialog", { name: "Второй" });
  await waitFor(() => expect((parent as HTMLElement).inert).toBe(true));
  expect((nested as HTMLElement).inert).toBe(false);
  await keyboard.keyboard("{Escape}");
  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "Второй" })).toBeNull(),
  );
  expect((parent as HTMLElement).inert).toBe(false);
  await waitFor(() => expect(document.activeElement).toBe(trigger));
});
