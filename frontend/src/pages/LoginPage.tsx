import { errorMessage } from "../utils/error";
import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import {
  prepareRequestOptions,
  serializeRequestResponse,
} from "../utils/webauthn";
import { useNavigate } from "react-router";
import { Fingerprint, ArrowRight, ShieldCheck } from "lucide-react";
import { AuthSurface } from "../components/AuthSurface";
import {
  Alert,
  Button,
  Field,
  Input,
  OTPInput,
  PasswordInput,
} from "../components/ui/controls";
import { sanitizeReturnTo } from "../utils/security";
import { RelyingPartyContext } from "../components/RelyingPartyContext";

interface LoginPageProps {
  onNavigateToRegister?: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({
  onNavigateToRegister,
}) => {
  const navigate = useNavigate();
  const { login, capabilities, refreshUser } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // MFA состояние (если включен второй фактор)
  const [mfaStep, setMfaStep] = useState(false);
  const [mfaToken, setMfaToken] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [mfaMethods, setMfaMethods] = useState<string[]>([]);

  // Поддержка OIDC перенаправления (return_to / redirect_uri)
  const urlParams = new URLSearchParams(window.location.search);
  const rawReturnTo =
    urlParams.get("return_to") || urlParams.get("redirect_uri");
  const returnTo = sanitizeReturnTo(rawReturnTo);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await login(username, password);
      if ("mfa_required" in res && res.mfa_required) {
        setPassword("");
        setMfaStep(true);
        setMfaToken(res.mfa_token);
        setMfaMethods(res.available_methods || []);
      } else {
        if (
          returnTo &&
          !("user" in res && res.user.session_purpose === "password_change")
        ) {
          window.location.href = returnTo;
        }
      }
    } catch (err: unknown) {
      setError(errorMessage(err, "Ошибка аутентификации"));
    } finally {
      setLoading(false);
    }
  };

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mfaToken || !mfaCode.trim()) {
      setError("Введите одноразовый код");
      return;
    }

    setError(null);
    setLoading(true);

    const cleanCode = mfaCode.trim();
    try {
      let loginSuccess = false;

      // Если метод TOTP и введен 6-значный цифровой код
      if (mfaMethods.includes("totp") && /^\d{6}$/.test(cleanCode)) {
        try {
          await api.verifyTotpLogin(cleanCode, mfaToken);
          loginSuccess = true;
        } catch (totpErr: unknown) {
          if (mfaMethods.includes("recovery_code")) {
            await api.verifyRecoveryCodeLogin(cleanCode, mfaToken);
            loginSuccess = true;
          } else {
            throw totpErr;
          }
        }
      } else if (mfaMethods.includes("recovery_code")) {
        await api.verifyRecoveryCodeLogin(cleanCode, mfaToken);
        loginSuccess = true;
      } else if (mfaMethods.includes("totp")) {
        await api.verifyTotpLogin(cleanCode, mfaToken);
        loginSuccess = true;
      } else {
        throw new Error(
          "Нет доступных методов второго фактора для данного кода",
        );
      }

      if (loginSuccess) {
        await refreshUser();
        if (returnTo) {
          window.location.href = returnTo;
        }
      }
    } catch (err: unknown) {
      setError(errorMessage(err, "Неверный код подтверждения"));
    } finally {
      setLoading(false);
    }
  };

  const handlePasskeyLogin = async () => {
    setError(null);
    setLoading(true);
    try {
      const serverOptions = await api.getPasskeyAuthOptions();
      const requestOptions = prepareRequestOptions(serverOptions);
      const assertion = await navigator.credentials.get(requestOptions);
      if (!assertion) {
        throw new Error("Аутентификатор не вернул подтверждение ключа");
      }
      const serialized = serializeRequestResponse(assertion);
      await api.verifyPasskeyAuth(serialized, mfaToken || undefined);
      await refreshUser();
      if (returnTo) {
        window.location.href = returnTo;
      }
    } catch (err: unknown) {
      setError(errorMessage(err, "Ошибка входа по Passkey"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthSurface
      title={mfaStep ? "Подтвердите вход" : "Вход в ALXPRGS"}
      description={
        mfaStep
          ? "Подтвердите доступ с помощью настроенного второго фактора."
          : "Одна учётная запись для сервисов инфраструктуры."
      }
      step={mfaStep ? "mfa" : "password"}
    >
      <RelyingPartyContext returnTo={returnTo} />
      {error && (
        <div className="mb-6" id="login-error">
          <Alert>{error}</Alert>
        </div>
      )}
      {!mfaStep ? (
        <>
          {capabilities?.passkey_enabled && (
            <div className="mb-6 space-y-3">
              <Button
                variant="primary"
                className="w-full"
                loading={loading}
                onClick={handlePasskeyLogin}
                data-testid="passkey-login-button"
              >
                <Fingerprint size={20} aria-hidden="true" />
                Войти с помощью ключа доступа
              </Button>
              <p className="text-xs text-secondary">
                Браузер предложит подтвердить вход на устройстве или ключе
                безопасности.
              </p>
              <div className="flex items-center gap-4 text-xs text-tertiary">
                <div className="h-px flex-1 bg-line" />
                или с паролем
                <div className="h-px flex-1 bg-line" />
              </div>
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-5">
            <Field id="loginpage-field-1" label="Имя пользователя или Email">
              <Input
                id="loginpage-field-1"
                name="username"
                autoComplete="username"
                required
                maxLength={64}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="user@alxprgs.tech"
                disabled={loading}
              />
            </Field>
            <Field id="loginpage-field-2" label="Пароль">
              <PasswordInput
                id="loginpage-field-2"
                name="password"
                autoComplete="current-password"
                required
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
              />
            </Field>
            <Button
              type="submit"
              variant="primary"
              loading={loading}
              className="w-full"
            >
              {loading ? "Выполняется вход..." : "Войти"}
              <ArrowRight size={18} aria-hidden="true" />
            </Button>
          </form>
          {capabilities?.registration_mode === "open" &&
            onNavigateToRegister && (
              <p className="mt-6 text-sm text-secondary">
                Нет учётной записи?{" "}
                <Button variant="ghost" onClick={onNavigateToRegister}>
                  Зарегистрироваться
                </Button>
              </p>
            )}
        </>
      ) : (
        <form onSubmit={handleMfaSubmit} className="space-y-5">
          {(mfaMethods.includes("totp") ||
            mfaMethods.includes("recovery_code")) && (
            <Field
              id="loginpage-field-3"
              label="Одноразовый код или код восстановления"
            >
              {mfaMethods.includes("recovery_code") ? (
                <Input
                  id="loginpage-field-3"
                  autoComplete="one-time-code"
                  required
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value)}
                  disabled={loading}
                />
              ) : (
                <OTPInput
                  id="loginpage-field-3"
                  required
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value)}
                  disabled={loading}
                />
              )}
            </Field>
          )}
          {(mfaMethods.includes("totp") ||
            mfaMethods.includes("recovery_code")) && (
            <Button
              type="submit"
              variant="primary"
              loading={loading}
              className="w-full"
            >
              Подтвердить
            </Button>
          )}
          {mfaMethods.includes("passkey") && (
            <Button
              variant="primary"
              onClick={handlePasskeyLogin}
              loading={loading}
              className="w-full"
              data-testid="passkey-mfa-button"
            >
              <Fingerprint size={18} />
              Подтвердить через ключ доступа
            </Button>
          )}
          <Button
            className="w-full"
            disabled={loading}
            onClick={() => {
              setMfaStep(false);
              setMfaToken("");
              setMfaCode("");
              setError(null);
              navigate(window.location.pathname + window.location.search, {
                replace: true,
              });
            }}
          >
            Назад
          </Button>
        </form>
      )}
      <div className="mt-8 flex items-center gap-2 text-xs text-secondary">
        <ShieldCheck size={16} aria-hidden="true" />
        Единая система входа ALXPRGS
      </div>
    </AuthSurface>
  );
};
