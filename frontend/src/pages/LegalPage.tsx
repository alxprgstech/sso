import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import type { LegalDocuments } from "../types/api";
import { useAuth } from "../context/AuthContext";
import { errorMessage } from "../utils/error";
import { sanitizeReturnTo } from "../utils/security";

export function useLegalDocuments() {
  const [documents, setDocuments] = useState<LegalDocuments | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { let active = true; void api.getLegalDocuments().then(value => { if (active) setDocuments(value); }).catch(() => { if (active) setError("Не удалось загрузить документы. Попробуйте обновить страницу."); }); return () => { active = false; }; }, []);
  return { documents, error };
}

export function ConsentFields({ terms, consent, onTerms, onConsent }: { terms: boolean; consent: boolean; onTerms: (value: boolean) => void; onConsent: (value: boolean) => void }) {
  return <fieldset className="consent-fields"><legend>Документы регистрации</legend>
    <label><input type="checkbox" required checked={terms} onChange={event => onTerms(event.target.checked)} /> Принимаю <a href="/terms" target="_blank" rel="noopener">условия использования (новая вкладка)</a></label>
    <label><input type="checkbox" required checked={consent} onChange={event => onConsent(event.target.checked)} /> Даю отдельное <a href="/data-consent" target="_blank" rel="noopener">согласие на обработку данных (новая вкладка)</a></label>
    <p>Прочитайте <a href="/privacy" target="_blank" rel="noopener">политику конфиденциальности (новая вкладка)</a>. Диагностика выбирается отдельно.</p>
  </fieldset>;
}

export function LegalPage({ path }: { path: string }) {
  const { documents, error } = useLegalDocuments();
  const document = documents?.documents.find(item => item.path === path);
  return <section className="legal-page"><a href="/login">К странице входа</a>
    {error ? <p role="alert">{error}</p> : !documents ? <p role="status">Загрузка документа…</p> : document ? <article><h1>{document.title}</h1><p>Проектный документ · Версия {document.version}</p>{document.paragraphs.map((text, index) => <p key={index}>{text}</p>)}</article> : <h1>Документ не найден</h1>}
  </section>;
}

function resumeAuthorization() {
  const target = sanitizeReturnTo(new URLSearchParams(location.search).get("return_to"));
  if (!target) return;
  if (new URL(target, location.origin).pathname === "/oauth/authorize") location.assign(target);
}

function useDocumentAcceptance(documents: LegalDocuments | null, refreshUser: () => Promise<void>) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const accept = async () => {
    if (!documents) return;
    setBusy(true); setError("");
    try {
      await api.acceptLegalDocuments(documents.required_versions);
      await refreshUser();
      resumeAuthorization();
    } catch (failure) { setError(errorMessage(failure, "Не удалось сохранить согласия. Обновите документы.")); }
    finally { setBusy(false); }
  };
  return { error, busy, accept };
}

export function AcceptancePage() {
  const { documents, error: loadingError } = useLegalDocuments();
  const { refreshUser, logout } = useAuth();
  const [terms, setTerms] = useState(false); const [consent, setConsent] = useState(false);
  const { error, busy, accept } = useDocumentAcceptance(documents, refreshUser);
  const accepted = terms && consent;
  const canSubmit = Boolean(documents) && accepted && !busy;
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (canSubmit) void accept();
  };
  return <section className="legal-page"><h1>Подтвердите документы</h1><p>Для продолжения работы прочитайте актуальные условия и согласие. Вы также можете выйти или запросить удаление аккаунта.</p>
    {(error || loadingError) && <p role="alert">{error || loadingError}</p>}
    <form onSubmit={submit}><ConsentFields terms={terms} consent={consent} onTerms={setTerms} onConsent={setConsent} /><button className="ui-button ui-primary" type="submit" disabled={!canSubmit}>Подтвердить и продолжить</button></form>
    <div className="privacy-actions"><a className="ui-button ui-secondary" href="/account-deletion">Удаление аккаунта</a><button className="ui-button ui-secondary" type="button" onClick={() => void logout()}>Выйти</button></div>
  </section>;
}
