import { FormEvent, useEffect, useRef, useState } from "react";
import { api, SecurityAuthorization } from "../api/client";
import { prepareRequestOptions, serializeRequestResponse } from "../utils/webauthn";
import { AccessibleDialog } from "./AccessibleDialog";

interface Pending {
  action: string;
  digest: string;
  resolve: (authorization: string) => void;
  reject: (error: Error) => void;
}

export function ReauthenticationDialog() {
  const [pending, setPending] = useState<Pending | null>(null);
  const current = useRef<Pending | null>(null);
  const [proof, setProof] = useState<SecurityAuthorization | null>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [method, setMethod] = useState("totp");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.setReauthenticationHandler((action, digest) => new Promise((resolve, reject) => {
      if (current.current) { reject(new Error("Дождитесь завершения текущего подтверждения")); return; }
      const value = { action, digest, resolve, reject };
      current.current = value;
      setProof(null); setPassword(""); setCode(""); setError(""); setPending(value);
    }));
    return () => {
      api.setReauthenticationHandler(null);
      current.current?.reject(new Error("Подтверждение отменено"));
      current.current = null;
    };
  }, []);

  function finish(authorization?: string) {
    if (authorization) current.current?.resolve(authorization);
    else current.current?.reject(new Error("Операция отменена"));
    current.current = null; setPending(null); setPassword(""); setCode(""); setProof(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!pending) return;
    setBusy(true); setError("");
    try {
      let result: SecurityAuthorization;
      if (!proof) {
        result = await api.startReauthentication(pending.action, pending.digest, password);
        setPassword("");
      } else if (method === "passkey") {
        if (!proof.passkey_options) throw new Error("Нет запроса подтверждения Passkey");
        const assertion = await navigator.credentials.get(prepareRequestOptions(proof.passkey_options));
        if (!assertion) throw new Error("Passkey не подтвердил запрос");
        result = await api.confirmReauthentication(proof.authorization, method, undefined, serializeRequestResponse(assertion));
      } else {
        result = await api.confirmReauthentication(proof.authorization, method, code);
      }
      if (!result.factor_required) finish(result.authorization);
      else { setProof(result); setMethod(result.methods?.[0] || "totp"); }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Подтверждение не удалось");
    } finally { setBusy(false); }
  }

  if (!pending) return null;
  return <div className="reauthentication-overlay fixed inset-0 flex items-center justify-center p-4">
    <AccessibleDialog label="Подтверждение чувствительной операции" busy={busy} onClose={() => finish()} className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
      <h2 className="text-xl font-semibold">Подтвердите операцию</h2>
      <p className="mt-2 text-gray-600">Для изменения данных или настроек безопасности подтвердите текущий доступ.</p>
      <form onSubmit={submit} className="mt-4 space-y-4">
        {!proof ? <label className="block">Текущий пароль<input type="password" autoComplete="current-password" required maxLength={128} value={password} onChange={event => setPassword(event.target.value)} className="mt-1 block w-full rounded border p-2" /></label>
          : <><label className="block">Второй фактор<select value={method} onChange={event => setMethod(event.target.value)} className="mt-1 block w-full rounded border p-2">{proof.methods?.map(item => <option key={item} value={item}>{item === "totp" ? "Код аутентификатора" : item === "recovery_code" ? "Резервный код" : "Passkey"}</option>)}</select></label>
            {method !== "passkey" && <label className="block">Код подтверждения<input autoComplete="one-time-code" required maxLength={128} value={code} onChange={event => setCode(event.target.value)} className="mt-1 block w-full rounded border p-2" /></label>}</>}
        {error && <p role="alert" className="text-red-700">{error}</p>}
        <div className="flex justify-end gap-3"><button type="button" disabled={busy} onClick={() => finish()}>Отмена</button><button type="submit" disabled={busy} className="rounded bg-blue-700 px-4 py-2 text-white">{busy ? "Проверка…" : "Подтвердить"}</button></div>
      </form>
    </AccessibleDialog>
  </div>;
}
