import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { errorMessage } from "../utils/error";

export const VerifyEmailPage: React.FC = () => {
  const initialToken = useRef(new URL(window.location.href).searchParams.get("token"));
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    window.history.replaceState(window.history.state, "", "/verify-email");
    setToken(initialToken.current);
  }, []);

  const confirm = async () => {
    if (!token || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.confirmEmailVerification(token);
      setSuccess(true);
      setToken(null);
    } catch (err: unknown) {
      setError(errorMessage(err, "Ссылка недействительна или срок её действия истёк"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
      <section className="max-w-md w-full rounded-lg bg-white p-6 shadow space-y-4">
        <h1 className="text-xl font-semibold">Подтверждение адреса электронной почты</h1>
        {success ? (
          <p role="status">Адрес подтверждён. Теперь можно войти в систему.</p>
        ) : token ? (
          <>
            <p>Нажмите кнопку, чтобы подтвердить адрес. Ссылка действует 24 часа.</p>
            <button type="button" onClick={confirm} disabled={busy} className="rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-50">
              {busy ? "Подтверждение..." : "Подтвердить адрес"}
            </button>
          </>
        ) : (
          <p>В ссылке отсутствует токен подтверждения.</p>
        )}
        {error && <p role="alert" className="text-red-700">{error}</p>}
        <p><a href="/login" className="text-blue-700 underline">Перейти ко входу</a></p>
      </section>
    </main>
  );
};
