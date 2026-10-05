import { Alert, Button } from "../components/ui/controls";
import { AuthSurface } from "../components/AuthSurface";
import { Link, useNavigate } from "react-router";
import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { errorMessage } from "../utils/error";

export const VerifyEmailPage: React.FC = () => {
  const navigate = useNavigate();
  const initialToken = useRef(
    new URL(window.location.href).searchParams.get("token"),
  );
  const initialMode = useRef(
    new URL(window.location.href).searchParams.get("mode"),
  );
  const [token, setToken] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    navigate("/verify-email", { replace: true });
    setToken(initialToken.current);
    if (initialMode.current === "registration" && initialToken.current) {
      void api
        .previewRegistrationLink(initialToken.current)
        .then((response) => setDetails(response.request_details))
        .catch(() => setDetails(null));
    }
  }, [navigate]);

  const confirm = async () => {
    if (!token || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (initialMode.current === "registration") {
        await api.confirmRegistrationLink(token);
      } else {
        await api.confirmEmailVerification(token);
      }
      setSuccess(true);
      setToken(null);
    } catch (err: unknown) {
      setError(
        errorMessage(err, "Ссылка недействительна или срок её действия истёк"),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthSurface
      title="Подтверждение адреса электронной почты"
      description="Проверьте сведения и подтвердите адрес, чтобы продолжить."
      step={success ? "confirmed" : "verify"}
    >
      <section className="space-y-4">
        {success ? (
          <Alert tone="success">
            Адрес подтверждён. Теперь можно войти в систему.
          </Alert>
        ) : token ? (
          <>
            <p>
              Нажмите кнопку, чтобы подтвердить адрес. Новая ссылка действует 10
              минут.
            </p>
            {details && (
              <details className="rounded border p-3 text-sm">
                <summary className="cursor-pointer">Сведения о запросе</summary>
                <dl className="mt-2 space-y-1">
                  {Object.entries(details).map(([key, value]) => (
                    <div key={key}>
                      <dt className="inline font-medium">{key}: </dt>
                      <dd className="inline">{value}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            )}
            <Button
              onClick={confirm}
              loading={busy}
              variant="primary"
              className="w-full"
            >
              {busy ? "Подтверждение..." : "Подтвердить адрес"}
            </Button>
          </>
        ) : (
          <Alert tone="warning">
            В ссылке отсутствует токен подтверждения. Откройте ссылку из письма
            целиком.
          </Alert>
        )}
        {error && <Alert>{error}</Alert>}
        <p>
          <Link to="/login" className="text-brand underline">
            Перейти ко входу
          </Link>
        </p>
      </section>
    </AuthSurface>
  );
};
