import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { PRIVACY_CHANGE, PRIVACY_KEY, readPrivacyChoice, savePrivacyChoice } from "../telemetry/consent";
import type { TelemetryConfig } from "../types/api";

export const COOKIE_SETTINGS = "alxprgs-cookie-settings";
export function LegalFooter() {
  return <footer className="legal-footer"><p>ALXPRGS SSO © 2026</p><nav aria-label="Документы и конфиденциальность">
    <a href="/privacy">Конфиденциальность</a><a href="/terms">Условия использования</a><a href="/cookies">Политика cookies</a><a href="/data-consent">Согласие на обработку данных</a>
    <button id="cookie-settings-trigger" type="button" onClick={() => window.dispatchEvent(new Event(COOKIE_SETTINGS))}>Настройки cookies</button>
  </nav><a href="mailto:alxprgs@gmail.com">alxprgs@gmail.com</a></footer>;
}

export function CookieBanner() {
  const [choice, setChoice] = useState(readPrivacyChoice);
  const [opened, setOpened] = useState(false);
  const [settings, setSettings] = useState(false);
  const [diagnostics, setDiagnostics] = useState(choice?.diagnostics ?? false);
  const [replay, setReplay] = useState(choice?.replay ?? false);
  const [availability, setAvailability] = useState(false);
  const [notice, setNotice] = useState("");
  const panel = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const visible = !choice || opened;
  useLayoutEffect(() => {
    const element = panel.current;
    if (!element) return;
    const measure = () => document.documentElement.style.setProperty("--cookie-banner-height", `${element.getBoundingClientRect().height}px`);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); document.documentElement.style.removeProperty("--cookie-banner-height"); };
  }, [visible, settings]);
  useEffect(() => {
    if (settings && visible) panel.current?.querySelector<HTMLInputElement>("input")?.focus();
  }, [settings, visible]);
  useEffect(() => {
    const changed = () => { const next = readPrivacyChoice(); setChoice(next); setDiagnostics(next?.diagnostics ?? false); setReplay(next?.replay ?? false); };
    const storage = (event: StorageEvent) => { if (event.key === PRIVACY_KEY || event.key === null) changed(); };
    const open = () => { trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setOpened(true); setSettings(true); };
    window.addEventListener(PRIVACY_CHANGE, changed); window.addEventListener("storage", storage); window.addEventListener(COOKIE_SETTINGS, open);
    const timer = window.setInterval(changed, 60_000);
    const controller = new AbortController();
    void fetch("/api/v1/auth/telemetry-config", { credentials: "omit", cache: "no-store", signal: controller.signal })
      .then(response => response.ok ? response.json() : null).then((config: TelemetryConfig | null) => setAvailability(Boolean(config?.enabled && config.environment === "staging" && config.replay_enabled))).catch(() => {});
    return () => { clearInterval(timer); controller.abort(); window.removeEventListener(PRIVACY_CHANGE, changed); window.removeEventListener("storage", storage); window.removeEventListener(COOKIE_SETTINGS, open); };
  }, []);
  const save = (diagnosticChoice: boolean, replayChoice: boolean) => {
    const persisted = savePrivacyChoice(diagnosticChoice, replayChoice && availability);
    setOpened(false); setSettings(false);
    setNotice(persisted ? "" : "Выбор сохранён только в этой вкладке: браузерное хранение недоступно.");
    if (panel.current?.contains(document.activeElement)) {
      const destination = trigger.current?.isConnected && !panel.current.contains(trigger.current) ? trigger.current : document.getElementById("cookie-settings-trigger");
      destination?.focus();
    }
  };
  return <>{notice && <p role="status" className="privacy-notice">{notice}</p>}{visible && <section ref={panel} className="cookie-banner" aria-labelledby="cookie-title"><div className="cookie-content">
    <h2 id="cookie-title">Cookies и диагностика</h2>
    <p>Технические cookies нужны для входа. Браузерная диагностика необязательна. <a href="/cookies">Подробнее</a></p>
    {settings && <fieldset><legend>Необязательные возможности</legend>
      <label><input type="checkbox" checked={diagnostics} onChange={event => { setDiagnostics(event.target.checked); if (!event.target.checked) setReplay(false); }} /> Диагностика ошибок и производительности</label>
      <label><input type="checkbox" checked={replay && availability} disabled={!diagnostics || !availability} onChange={event => setReplay(event.target.checked)} /> Запись сессии Replay (только разрешённый staging)</label>
    </fieldset>}
    <div className="privacy-actions"><button type="button" onClick={() => save(false, false)}>Только необходимые</button><button type="button" onClick={() => save(true, false)}>Разрешить диагностику</button>
      {settings ? <button type="button" onClick={() => save(diagnostics, replay)}>Сохранить выбор</button> : <button type="button" onClick={() => { trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setSettings(true); }}>Настроить</button>}
    </div>
  </div></section>}</>;
}
