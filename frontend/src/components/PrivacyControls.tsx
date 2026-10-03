import { useEffect, useRef, useState, type ReactNode } from "react";
import { PRIVACY_CHANGE, PRIVACY_KEY, readPrivacyChoice, savePrivacyChoice } from "../telemetry/consent";
import type { TelemetryConfig } from "../types/api";

export const COOKIE_SETTINGS = "alxprgs-cookie-settings";
export function LegalFooter() {
  return <footer className="legal-footer"><p>ALXPRGS SSO © 2026</p><nav aria-label="Документы и конфиденциальность">
    <a href="/privacy">Конфиденциальность</a><a href="/terms">Условия использования</a><a href="/cookies">Политика cookies</a><a href="/data-consent">Согласие на обработку данных</a>
    <button id="cookie-settings-trigger" type="button" onClick={() => window.dispatchEvent(new Event(COOKIE_SETTINGS))}>Настройки cookies</button>
  </nav><a href="mailto:alxprgs@gmail.com">alxprgs@gmail.com</a></footer>;
}

function replayAvailable(config: TelemetryConfig | null): boolean {
  if (!config?.enabled) return false;
  return config.environment === "staging" && config.replay_enabled;
}

function useReplayAvailability() {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/v1/auth/telemetry-config", { credentials: "omit", cache: "no-store", signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then((config: TelemetryConfig | null) => setAvailable(replayAvailable(config))).catch(() => {});
    return () => controller.abort();
  }, []);
  return available;
}

function usePrivacyChoice() {
  const [choice, setChoice] = useState(readPrivacyChoice);
  useEffect(() => {
    const changed = () => setChoice(readPrivacyChoice());
    const storage = (event: StorageEvent) => {
      if (event.key === PRIVACY_KEY || event.key === null) changed();
    };
    window.addEventListener(PRIVACY_CHANGE, changed);
    window.addEventListener("storage", storage);
    const timer = window.setInterval(changed, 60_000);
    return () => {
      clearInterval(timer);
      window.removeEventListener(PRIVACY_CHANGE, changed);
      window.removeEventListener("storage", storage);
    };
  }, []);
  return choice;
}

function useCookiePanel() {
  const [opened, setOpened] = useState(false);
  const [settings, setSettings] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const openSettings = () => {
    trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOpened(true); setSettings(true);
  };
  useEffect(() => {
    window.addEventListener(COOKIE_SETTINGS, openSettings);
    return () => window.removeEventListener(COOKIE_SETTINGS, openSettings);
  }, []);
  useEffect(() => {
    if (settings) panel.current?.querySelector<HTMLInputElement>("input")?.focus();
  }, [settings]);
  const close = () => {
    const element = panel.current;
    if (element?.contains(document.activeElement)) {
      const destination = outsideTrigger(element, trigger.current);
      destination?.focus();
    }
    setOpened(false); setSettings(false);
  };
  return { opened, settings, panel, openSettings, close };
}

function outsideTrigger(panel: HTMLElement, trigger: HTMLElement | null) {
  if (trigger?.isConnected && !panel.contains(trigger)) return trigger;
  return document.getElementById("cookie-settings-trigger");
}

function preferenceFlags(choice: ReturnType<typeof readPrivacyChoice>) {
  return { diagnostics: choice?.diagnostics ?? false, replay: choice?.replay ?? false };
}

function useCookiePreferences(choice: ReturnType<typeof readPrivacyChoice>) {
  const initial = preferenceFlags(choice);
  const [diagnostics, setDiagnostics] = useState(initial.diagnostics);
  const [replay, setReplay] = useState(initial.replay);
  useEffect(() => {
    const flags = preferenceFlags(choice);
    setDiagnostics(flags.diagnostics); setReplay(flags.replay);
  }, [choice]);
  const changeDiagnostics = (enabled: boolean) => {
    setDiagnostics(enabled);
    if (!enabled) setReplay(false);
  };
  return { diagnostics, replay, setReplay, changeDiagnostics };
}

function CookiePreferences({ choice, available, save }: {
  choice: ReturnType<typeof readPrivacyChoice>; available: boolean;
  save: (diagnostics: boolean, replay: boolean) => void;
}) {
  const { diagnostics, replay, setReplay, changeDiagnostics } = useCookiePreferences(choice);
  return <>
    <fieldset><legend>Необязательные возможности</legend>
      <label><input type="checkbox" checked={diagnostics} onChange={event => changeDiagnostics(event.target.checked)} /> Диагностика ошибок и производительности</label>
      <label><input type="checkbox" checked={replay && available} disabled={!diagnostics || !available} onChange={event => setReplay(event.target.checked)} /> Запись сессии Replay (только разрешённый staging)</label>
    </fieldset>
    <CookieActions save={save}><button type="button" onClick={() => save(diagnostics, replay)}>Сохранить выбор</button></CookieActions>
  </>;
}

function CookieActions({ save, children }: { save: (diagnostics: boolean, replay: boolean) => void; children: ReactNode }) {
  return <div className="privacy-actions">
    <button type="button" onClick={() => save(false, false)}>Только необходимые</button>
    <button type="button" onClick={() => save(true, false)}>Разрешить диагностику</button>
    {children}
  </div>;
}

export function CookieBanner() {
  const choice = usePrivacyChoice();
  const controls = useCookiePanel();
  const available = useReplayAvailability();
  const [notice, setNotice] = useState("");
  const save = (diagnostics: boolean, replay: boolean) => {
    const persisted = savePrivacyChoice(diagnostics, replay && available);
    controls.close();
    setNotice(persisted ? "" : "Выбор сохранён только в этой вкладке: браузерное хранение недоступно.");
  };
  if (choice && !controls.opened) return notice ? <p role="status" className="privacy-notice">{notice}</p> : null;
  return <section ref={controls.panel} className="cookie-banner" aria-labelledby="cookie-title"><div className="cookie-content">
    <h2 id="cookie-title">Cookies и диагностика</h2>
    <p>Технические cookies нужны для входа. Браузерная диагностика необязательна. <a href="/cookies">Подробнее</a></p>
    {controls.settings ? <CookiePreferences choice={choice} available={available} save={save} /> :
      <CookieActions save={save}><button type="button" onClick={controls.openSettings}>Настроить</button></CookieActions>}
  </div></section>;
}
