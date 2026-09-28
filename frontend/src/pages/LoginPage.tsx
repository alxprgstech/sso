import { errorMessage } from "../utils/error";
import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import { prepareRequestOptions, serializeRequestResponse } from "../utils/webauthn";
import { sanitizeReturnTo } from "../utils/security";

interface LoginPageProps {
  onNavigateToRegister?: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onNavigateToRegister }) => {
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
  const rawReturnTo = urlParams.get("return_to") || urlParams.get("redirect_uri");
  const returnTo = sanitizeReturnTo(rawReturnTo);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await login(username, password);
      if ("mfa_required" in res && res.mfa_required) {
        setMfaStep(true);
        setMfaToken(res.mfa_token);
        setMfaMethods(res.available_methods || []);
      } else {
        if (returnTo) {
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
        throw new Error("Нет доступных методов второго фактора для данного кода");
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
    <div className="min-h-[calc(100vh-4rem)] flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="w-12 h-12 bg-blue-600 rounded-xl mx-auto flex items-center justify-center text-white font-bold text-2xl shadow-md">
          A
        </div>
        <h2 className="mt-4 text-center text-3xl font-extrabold text-gray-900 tracking-tight">
          Единая система входа ALXPRGS
        </h2>
        <p className="mt-2 text-center text-sm text-gray-600">
          Вход в учетную запись инфраструктуры <span className="font-semibold text-gray-800">alxprgs.tech</span>
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <div className="bg-white py-8 px-4 shadow-xl sm:rounded-xl sm:px-10 border border-gray-100">
          {error && (
            <div className="mb-4 bg-red-50 border-l-4 border-red-500 p-3 rounded text-sm text-red-700">
              {error}
            </div>
          )}

          {!mfaStep ? (
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Имя пользователя или Email
                </label>
                <div className="mt-1">
                  <input
                    type="text"
                    required
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="appearance-none block w-full px-3 py-2.5 border border-gray-300 rounded-lg shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
                    placeholder="user@alxprgs.tech"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700">Пароль</label>
                <div className="mt-1">
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="appearance-none block w-full px-3 py-2.5 border border-gray-300 rounded-lg shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
                  />
                </div>
              </div>

              <div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex justify-center py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 transition-colors"
                >
                  {loading ? "Выполняется вход..." : "Войти"}
                </button>
              </div>

              {capabilities?.passkey_enabled && (
                <button
                  type="button"
                  onClick={handlePasskeyLogin}
                  disabled={loading}
                  className="w-full mt-3 flex justify-center py-2.5 px-4 border border-blue-600 rounded-lg shadow-sm text-sm font-medium text-blue-600 bg-white hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
                  data-testid="passkey-login-button"
                >
                  Войти с помощью Passkey (WebAuthn)
                </button>
              )}

              {/* Ссылка на регистрацию (отображается ТОЛЬКО при открытом режиме, REG-01, REG-03) */}
              {capabilities?.registration_mode === "open" && onNavigateToRegister && (
                <div className="pt-2 text-center">
                  <span className="text-sm text-gray-600">Нет учётной записи? </span>
                  <button
                    type="button"
                    onClick={onNavigateToRegister}
                    className="text-sm font-medium text-blue-600 hover:text-blue-500 focus:outline-none underline"
                  >
                    Зарегистрироваться
                  </button>
                </div>
              )}
            </form>
          ) : (
            <form onSubmit={handleMfaSubmit} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Одноразовый код (TOTP или код восстановления)
                </label>
                <div className="mt-1">
                  <input
                    type="text"
                    required
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value)}
                    className="appearance-none block w-full px-3 py-2.5 border border-gray-300 rounded-lg shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm text-center tracking-widest text-lg font-mono"
                    placeholder="000000"
                  />
                </div>
              </div>

              <div className="flex space-x-3">
                {(mfaMethods.includes("totp") || mfaMethods.includes("recovery_code")) && (
                  <button
                    type="submit"
                    className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700"
                  >
                    Подтвердить
                  </button>
                )}
                {mfaMethods.includes("passkey") && (
                  <button
                    type="button"
                    onClick={handlePasskeyLogin}
                    disabled={loading}
                    className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700"
                    data-testid="passkey-mfa-button"
                  >
                    Подтвердить через Passkey
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setMfaStep(false)}
                  className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200"
                >
                  Назад
                </button>
              </div>
            </form>
          )}

          {/* Информационная панель флагов возможностей сервера */}
          {capabilities && (
            <div className="mt-6 pt-5 border-t border-gray-100 text-xs text-gray-500 space-y-1">
              <div className="font-semibold text-gray-600 mb-1">Политика безопасности (default-профиль):</div>
              <div className="flex justify-between">
                <span>Парольный вход:</span>
                <span className="text-green-600 font-medium">Активен (Argon2id)</span>
              </div>
              <div className="flex justify-between">
                <span>Регистрация пользователей:</span>
                <span className={capabilities.registration_mode === "open" ? "text-green-600 font-medium" : "text-gray-400"}>
                  {capabilities.registration_mode === "open" ? "Открыта" : "Закрыта (по умолчанию)"}
                </span>
              </div>
              <div className="flex justify-between">
                <span>TOTP аутентификатор:</span>
                <span className={capabilities.totp_enabled ? "text-green-600" : "text-gray-400"}>
                  {capabilities.totp_enabled ? "Включено" : "Отключено по умолчанию"}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Passkey (WebAuthn):</span>
                <span className={capabilities.passkey_enabled ? "text-green-600" : "text-gray-400"}>
                  {capabilities.passkey_enabled ? "Включено" : "Отключено по умолчанию"}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Резервные коды:</span>
                <span className={capabilities.recovery_codes_enabled ? "text-green-600" : "text-gray-400"}>
                  {capabilities.recovery_codes_enabled ? "Включено" : "Отключено по умолчанию"}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
