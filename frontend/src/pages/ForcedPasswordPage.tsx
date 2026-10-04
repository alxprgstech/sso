import { FormEvent, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";

export function ForcedPasswordPage() {
  const { refreshUser, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    if (next !== confirmation) { setError("Новые пароли не совпадают"); return; }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setCurrent(""); setNext(""); setConfirmation("");
      window.history.replaceState({}, "", "/login");
      await refreshUser();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось сменить пароль"); }
    finally { setBusy(false); }
  }
  return <main className="mx-auto w-full max-w-lg p-6">
    <h1 className="text-2xl font-semibold">Смените временный пароль</h1>
    <p className="mt-2 text-gray-600">До смены пароля доступ к приложениям и настройкам ограничен. После смены потребуется новый вход.</p>
    <form onSubmit={submit} className="mt-6 space-y-4">
      <label className="block">Временный пароль<input type="password" required autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} className="block w-full rounded border p-2" /></label>
      <label className="block">Новый пароль<input type="password" required autoComplete="new-password" minLength={15} maxLength={128} value={next} onChange={e => setNext(e.target.value)} className="block w-full rounded border p-2" /></label>
      <label className="block">Повторите новый пароль<input type="password" required autoComplete="new-password" minLength={15} maxLength={128} value={confirmation} onChange={e => setConfirmation(e.target.value)} className="block w-full rounded border p-2" /></label>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <button type="submit" disabled={busy} className="rounded bg-blue-700 px-4 py-2 text-white">{busy ? "Сохранение…" : "Сменить пароль"}</button>
      <button type="button" disabled={busy} onClick={() => { void logout(); }} className="ml-4">Выйти</button>
    </form>
  </main>;
}
