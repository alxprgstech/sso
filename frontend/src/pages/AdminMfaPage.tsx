import React, { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Navigate, useNavigate } from "react-router";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { Alert, Badge, Button, Input } from "../components/ui/controls";
import type { TOTPSetupResponse } from "../types/api";
import { errorMessage } from "../utils/error";
import {
  prepareCreationOptions,
  prepareRequestOptions,
  serializeCreationResponse,
  serializeRequestResponse,
} from "../utils/webauthn";

function errorText(error: unknown, fallback: string): string {
  const message = errorMessage(error, fallback);
  if (/NotAllowedError/.test(message)) {
    return "Браузер отменил запрос или устройство не подтвердило проверку пользователя.";
  }
  return message;
}

export const AdminMfaPage: React.FC = () => {
  const { user, refreshUser } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [totpSetup, setTotpSetup] = useState<TOTPSetupResponse | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [enrolled, setEnrolled] = useState(false);

  if (!user) return null;
  const admin = user.is_superuser || user.roles.includes("admin");
  if (!admin) {
    return (
      <section className="legal-page">
        <h1>Доступ ограничен</h1>
        <p>Этот раздел доступен администратору.</p>
      </section>
    );
  }
  if (!user.admin_mfa_required) return <Navigate to="/admin" replace />;

  const hasFactor = user.has_totp || user.has_passkey;
  const verificationReady = hasFactor || enrolled;

  const finish = async (message: string) => {
    await refreshUser();
    setNotice(message);
    setBusy(false);
    navigate("/admin", { replace: true });
  };

  const enrollPasskey = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (!window.PublicKeyCredential || !navigator.credentials) {
        throw new Error("Этот браузер не поддерживает Passkey.");
      }
      const options = await api.getPasskeyRegistrationOptions();
      const credential = await navigator.credentials.create(
        prepareCreationOptions(options),
      );
      if (!credential) throw new Error("Регистрация Passkey отменена.");
      await api.verifyPasskeyRegistration(
        serializeCreationResponse(credential),
        "Admin passkey",
      );
      await refreshUser();
      setEnrolled(true);
      setNotice(
        "Passkey зарегистрирован. Подтвердите его ещё раз, чтобы получить доступ к панели.",
      );
    } catch (err) {
      setError(errorText(err, "Не удалось зарегистрировать Passkey"));
    } finally {
      setBusy(false);
    }
  };

  const enrollTotp = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setTotpSetup(await api.setupTotp());
    } catch (err) {
      setError(errorText(err, "Не удалось начать настройку TOTP"));
    } finally {
      setBusy(false);
    }
  };

  const confirmTotp = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.confirmTotp(totpCode.trim());
      setTotpSetup(null);
      setTotpCode("");
      await refreshUser();
      setEnrolled(true);
      setNotice(
        "TOTP подключён. Введите следующий код, чтобы подтвердить новую сессию.",
      );
    } catch (err) {
      setError(errorText(err, "Неверный код подтверждения"));
    } finally {
      setBusy(false);
    }
  };

  const verifyTotp = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.elevateSession("totp", { code: totpCode.trim() });
      await finish("Сессия подтверждена. Панель администратора доступна.");
    } catch (err) {
      setError(errorText(err, "Не удалось подтвердить TOTP"));
      setBusy(false);
    }
  };

  const verifyPasskey = async () => {
    setBusy(true);
    setError(null);
    try {
      if (!window.PublicKeyCredential || !navigator.credentials) {
        throw new Error("Этот браузер не поддерживает Passkey.");
      }
      const options = await api.getSessionElevationPasskeyOptions();
      const assertion = await navigator.credentials.get(
        prepareRequestOptions(options),
      );
      if (!assertion) throw new Error("Подтверждение Passkey отменено.");
      await api.elevateSession("passkey", {
        credential: serializeRequestResponse(assertion),
      });
      await finish("Сессия подтверждена. Панель администратора доступна.");
    } catch (err) {
      setError(errorText(err, "Не удалось подтвердить Passkey"));
      setBusy(false);
    }
  };

  const verifyRecovery = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.elevateSession("recovery_code", {
        code: recoveryCode.trim(),
      });
      await finish("Сессия подтверждена резервным кодом.");
    } catch (err) {
      setError(errorText(err, "Резервный код не принят"));
      setBusy(false);
    }
  };

  return (
    <div className="admin-page space-y-6">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1>Защита панели администратора</h1>
          <Badge tone="warning">Требуется MFA</Badge>
        </div>
        <p className="text-secondary">
          Для доступа к панели администратора необходимо настроить
          двухфакторную аутентификацию и подтвердить её в этой сессии.
        </p>
        <p className="text-secondary text-sm">
          Текущая сессия:{" "}
          {user.mfa_verified ? (
            <Badge tone="success">подтверждена</Badge>
          ) : (
            <Badge tone="warning">только пароль</Badge>
          )}
        </p>
      </header>

      {error && <Alert>{error}</Alert>}
      {notice && (
        <div
          role="status"
          className="rounded-lg border border-success bg-success-soft p-4 text-sm text-success"
        >
          {notice}
        </div>
      )}

      {!verificationReady && (
        <div className="grid gap-4 md:grid-cols-2">
          <section className="section-panel space-y-3">
            <h2 className="text-lg font-semibold">Ключ доступа (Passkey)</h2>
            <p className="text-sm text-secondary">
              Рекомендуемый способ: биометрия или аппаратный ключ. Проверка
              пользователя обязательна.
            </p>
            <Button
              type="button"
              variant="primary"
              disabled={busy}
              onClick={() => void enrollPasskey()}
            >
              {busy ? "Ожидание..." : "Зарегистрировать Passkey"}
            </Button>
          </section>

          <section className="section-panel space-y-3">
            <h2 className="text-lg font-semibold">
              Приложение-аутентификатор (TOTP)
            </h2>
            <p className="text-sm text-secondary">
              Шестизначные коды в приложении-аутентификаторе. Резервные коды
              можно выпустить после подключения фактора.
            </p>
            {totpSetup ? (
              <form onSubmit={confirmTotp} className="space-y-3">
                <div className="qr-surface" data-testid="admin-mfa-qr">
                  <QRCodeSVG
                    role="img"
                    aria-label="QR-код для подключения администратора"
                    value={totpSetup.otpauth_url}
                    size={176}
                  />
                </div>
                <p className="text-xs text-secondary">
                  Секрет:{" "}
                  <span className="font-mono break-all" data-sentry-block>
                    {totpSetup.secret}
                  </span>
                </p>
                <label className="block text-sm" htmlFor="admin-mfa-totp-confirm">
                  Код из приложения
                </label>
                <Input
                  id="admin-mfa-totp-confirm"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  value={totpCode}
                  onChange={(event) => setTotpCode(event.target.value)}
                  className="w-full"
                />
                <div className="flex gap-2">
                  <Button type="submit" variant="primary" disabled={busy}>
                    Подтвердить подключение
                  </Button>
                  <Button
                    type="button"
                    onClick={() => {
                      setTotpSetup(null);
                      setTotpCode("");
                    }}
                  >
                    Отмена
                  </Button>
                </div>
              </form>
            ) : (
              <Button
                type="button"
                variant="primary"
                disabled={busy}
                onClick={() => void enrollTotp()}
              >
                {busy ? "Ожидание..." : "Настроить TOTP"}
              </Button>
            )}
          </section>
        </div>
      )}

      {verificationReady && (
        <section className="section-panel space-y-5">
          <div>
            <h2 className="text-lg font-semibold">Подтвердите второй фактор</h2>
            <p className="text-sm text-secondary">
              Настроенный фактор не даёт административный доступ автоматически:
              подтверждение должно быть выполнено в этой сессии.
            </p>
          </div>
          <div className="flex flex-wrap gap-3 text-sm">
            {user.has_passkey && (
              <Badge tone="success">Passkey настроен</Badge>
            )}
            {user.has_totp && <Badge tone="success">TOTP настроен</Badge>}
          </div>

          {user.has_passkey && (
            <Button
              type="button"
              variant="primary"
              disabled={busy}
              onClick={() => void verifyPasskey()}
            >
              {busy ? "Проверка..." : "Подтвердить Passkey"}
            </Button>
          )}

          {user.has_totp && (
            <form onSubmit={verifyTotp} className="space-y-2 max-w-sm">
              <label className="block text-sm" htmlFor="admin-mfa-totp-verify">
                Код из приложения-аутентификатора
              </label>
              <div className="flex gap-2">
                <Input
                  id="admin-mfa-totp-verify"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  value={totpCode}
                  onChange={(event) => setTotpCode(event.target.value)}
                  className="flex-1"
                />
                <Button
                  type="submit"
                  variant="primary"
                  disabled={busy}
                  aria-label="Подтвердить TOTP"
                >
                  Подтвердить
                </Button>
              </div>
            </form>
          )}

          <details className="rounded-lg border border-line p-4">
            <summary className="cursor-pointer text-sm font-medium">
              Использовать резервный код
            </summary>
            <form onSubmit={verifyRecovery} className="mt-3 space-y-2 max-w-sm">
              <label className="block text-sm" htmlFor="admin-mfa-recovery">
                Одноразовый резервный код
              </label>
              <div className="flex gap-2">
                <Input
                  id="admin-mfa-recovery"
                  type="text"
                  autoComplete="off"
                  required
                  value={recoveryCode}
                  onChange={(event) => setRecoveryCode(event.target.value)}
                  className="flex-1 font-mono"
                />
                <Button
                  type="submit"
                  variant="primary"
                  disabled={busy}
                  aria-label="Подтвердить резервный код"
                >
                  Подтвердить
                </Button>
              </div>
              <p className="text-xs text-secondary">
                Резервный код не подходит для политик, требующих
                phishing-resistant Passkey.
              </p>
            </form>
          </details>
        </section>
      )}
    </div>
  );
};
