import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type { DeletionAuthorization, DeletionStatus } from "../types/api";
import { errorMessage } from "../utils/error";
import { prepareRequestOptions, serializeRequestResponse } from "../utils/webauthn";

const date = (value: string | null) => value ? new Date(value).toLocaleString("ru-RU", { dateStyle: "long", timeStyle: "long" }) : "—";

export function AccountDeletionPage() {
  const { refreshUser, logout } = useAuth();
  const [status, setStatus] = useState<DeletionStatus | null>(null);
  const [password, setPassword] = useState(""); const [code, setCode] = useState("");
  const [proof, setProof] = useState<DeletionAuthorization | null>(null);
  const [method, setMethod] = useState("totp"); const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const action = status?.pending ? "cancel" : "request";
  useEffect(() => { let active = true; void api.getDeletionStatus().then(value => { if (active) setStatus(value); }).catch(() => { if (active) setError("Не удалось получить статус удаления. Обновите страницу."); }); return () => { active = false; }; }, []);
  const reauthenticate = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try { const value = await api.reauthenticateDeletion(action, password); setProof(value); setMethod(value.methods?.[0] ?? "totp"); }
    catch (failure) { setError(errorMessage(failure, "Подтверждение не удалось.")); }
    finally { setPassword(""); setBusy(false); }
  };
  const factor = async (event: React.FormEvent) => {
    event.preventDefault(); if (!proof) return; setBusy(true); setError("");
    try {
      let credential: unknown;
      if (method === "passkey") {
        if (!proof.passkey_options) throw new Error("Опции Passkey недоступны.");
        const response = await navigator.credentials.get(prepareRequestOptions(proof.passkey_options));
        if (!response) throw new Error("Подтверждение ключом отменено.");
        credential = serializeRequestResponse(response);
      }
      setProof(await api.confirmDeletionFactor({ action, authorization: proof.authorization, method, code: method === "passkey" ? undefined : code, credential }));
    } catch (failure) { setError(errorMessage(failure, "Второй фактор не прошёл проверку.")); }
    finally { setCode(""); setBusy(false); }
  };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!proof) return;
    if (proof.factor_required) return;
    if (!confirmed) return;
    setBusy(true); setError("");
    try {
      const result = await api.submitDeletion(action, proof.authorization); setStatus(result); setProof(null); setConfirmed(false);
      await refreshUser();
      if (action === "cancel") window.location.assign("/login");
    } catch (failure) { setProof(null); setConfirmed(false); setError(errorMessage(failure, "Операция не выполнена. Подтвердите доступ заново.")); }
    finally { setBusy(false); }
  };
  const coolingDown = Boolean(status?.request_allowed_at && Date.parse(status.request_allowed_at) > Date.now());
  const deadlinePassed = Boolean(status?.scheduled_for && Date.parse(status.scheduled_for) <= Date.now());
  return <section className="legal-page" aria-labelledby="deletion-heading"><h1 id="deletion-heading">Удаление аккаунта</h1>
    {!status && !error && <p role="status">Загрузка статуса…</p>}
    {error && <div role="alert" className="deletion-alert"><strong>{error}</strong></div>}
    {status?.pending ? <><p role="status">Окончательное удаление запланировано на <strong>{date(status.scheduled_for)}</strong>.</p><p>До этой даты можно отменить заявку. Вход не отменяет её автоматически. Обычный доступ и SSO приостановлены.</p></> : <p>Данные SSO будут удалены через 14 дней после заявки. До назначенного срока заявку можно отменить. После отмены новая обычная заявка доступна через 7 дней.</p>}
    <p>Удаление не охватывает данные других приложений. Резервные копии хранятся не более 30 дней; автономно проверяемые JWT могут действовать до истечения своего срока (по default до пяти минут).</p>
    {coolingDown && !status?.pending && <p role="status">Повторная заявка доступна с {date(status?.request_allowed_at ?? null)}.</p>}
    {deadlinePassed && <p role="status">Срок отмены истёк. Заявка ожидает окончательной обработки.</p>}
    {status && !deadlinePassed && (!coolingDown || status.pending) && (!proof ? <form onSubmit={reauthenticate}>
      <label htmlFor="deletion-password">Текущий пароль</label><input id="deletion-password" type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} disabled={busy} />
      <button type="submit" disabled={busy}>Подтвердить доступ для {action === "cancel" ? "отмены" : "удаления"}</button>
    </form> : proof.factor_required ? <form onSubmit={factor}><label htmlFor="deletion-method">Второй фактор</label><select id="deletion-method" value={method} onChange={event => setMethod(event.target.value)} disabled={busy}>{proof.methods?.map(value => <option key={value} value={value}>{value === "totp" ? "Код TOTP" : value === "recovery_code" ? "Резервный код" : "Passkey"}</option>)}</select>
      {method !== "passkey" && <><label htmlFor="deletion-code">Код подтверждения</label><input id="deletion-code" autoComplete="one-time-code" required value={code} onChange={event => setCode(event.target.value)} disabled={busy} /></>}
      <button type="submit" disabled={busy}>Подтвердить второй фактор</button>
    </form> : <form onSubmit={submit}><label><input type="checkbox" required checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /> {action === "cancel" ? "Подтверждаю отмену удаления; потребуется новый вход, повторная заявка — через 7 дней." : "Понимаю последствия и подтверждаю удаление через 14 дней."}</label><button type="submit" disabled={busy || !confirmed}>{action === "cancel" ? "Отменить удаление" : "Запланировать удаление"}</button></form>)}
    {proof && <p>Подтверждение действует до {date(proof.expires_at)}. <button type="button" disabled={busy} onClick={() => { setProof(null); setCode(""); setConfirmed(false); }}>Подтвердить доступ заново</button></p>}
    <div className="privacy-actions">{!status?.pending && <a className="ui-button ui-secondary" href="/">В личный кабинет</a>}<button className="ui-button ui-secondary" type="button" onClick={() => void logout()}>Выйти</button></div>
    <p>Обращения о персональных данных и административных ограничениях: <a href="mailto:alxprgs@gmail.com">alxprgs@gmail.com</a>. Пауза заявок не ограничивает обращения по закону.</p>
  </section>;
}
