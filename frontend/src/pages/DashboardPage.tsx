import React, { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import { SessionInfo } from "../types/api";
import { prepareCreationOptions, serializeCreationResponse } from "../utils/webauthn";

export const DashboardPage: React.FC = () => {
  const { user, capabilities } = useAuth();

  // Состояние смены пароля
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordLoading, setPasswordLoading] = useState(false);

  // Состояние сессий
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  // Состояние Passkeys (G4-PASSKEY)
  const [passkeys, setPasskeys] = useState<Array<{ id: string; name: string; sign_count: number }>>([]);
  const [passkeyName, setPasskeyName] = useState("");
  const [passkeyLoading, setPasskeyLoading] = useState(false);
  const [passkeySuccess, setPasskeySuccess] = useState<string | null>(null);
  const [passkeyError, setPasskeyError] = useState<string | null>(null);

  const fetchSessions = async () => {
    setSessionsLoading(true);
    try {
      const data = await api.getSessions();
      setSessions(data);
    } catch (err: any) {
      setSessionError(err.message || "Не удалось загрузить список сессий");
    } finally {
      setSessionsLoading(false);
    }
  };

  const fetchPasskeys = async () => {
    if (!capabilities?.passkey_enabled) return;
    try {
      const data = await api.getPasskeyCredentials();
      setPasskeys(data);
    } catch {
      // Игнорируем
    }
  };

  useEffect(() => {
    fetchSessions();
    fetchPasskeys();
  }, [capabilities?.passkey_enabled]);

  const handleRegisterPasskey = async () => {
    setPasskeyLoading(true);
    setPasskeyError(null);
    setPasskeySuccess(null);
    try {
      const serverOptions = await api.getPasskeyRegistrationOptions();
      const creationOptions = prepareCreationOptions(serverOptions);
      const credential = await navigator.credentials.create(creationOptions);
      if (!credential) {
        throw new Error("Аутентификатор не вернул учетные данные");
      }
      const serialized = serializeCreationResponse(credential);
      const res = await api.verifyPasskeyRegistration(serialized, passkeyName.trim() || "Passkey");
      setPasskeySuccess(res.message || "Passkey успешно зарегистрирован");
      setPasskeyName("");
      await fetchPasskeys();
    } catch (err: any) {
      setPasskeyError(err.message || "Ошибка при регистрации Passkey");
    } finally {
      setPasskeyLoading(false);
    }
  };

  const handleDeletePasskey = async (id: string) => {
    setPasskeyLoading(true);
    setPasskeyError(null);
    setPasskeySuccess(null);
    try {
      await api.deletePasskeyCredential(id);
      setPasskeySuccess("Passkey успешно удален");
      await fetchPasskeys();
    } catch (err: any) {
      setPasskeyError(err.message || "Ошибка при удалении Passkey");
    } finally {
      setPasskeyLoading(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(null);

    if (newPassword !== confirmPassword) {
      setPasswordError("Новые пароли не совпадают");
      return;
    }
    if (newPassword.length < 8) {
      setPasswordError("Пароль должен содержать минимум 8 символов");
      return;
    }

    setPasswordLoading(true);
    try {
      const res = await api.changePassword(currentPassword, newPassword);
      setPasswordSuccess(res.message || "Пароль успешно обновлён");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      await fetchSessions();
    } catch (err: any) {
      setPasswordError(err.message || "Ошибка смены пароля");
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleRevokeSession = async (sessionId: string) => {
    try {
      await api.revokeSession(sessionId);
      await fetchSessions();
    } catch (err: any) {
      alert(err.message || "Не удалось завершить сессию");
    }
  };

  const handleRevokeOtherSessions = async () => {
    if (!confirm("Вы уверены, что хотите завершить все остальные активные сессии?")) return;
    try {
      const res = await api.revokeOtherSessions();
      alert(`Отозвано сессий: ${res.revoked_count}`);
      await fetchSessions();
    } catch (err: any) {
      alert(err.message || "Не удалось отозвать сессии");
    }
  };

  if (!user) return null;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* 1. Карточка профиля */}
      <div className="bg-white shadow rounded-xl p-6 border border-gray-100">
        <h2 className="text-xl font-bold text-gray-900 border-b pb-4 mb-4">Учётная запись</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-500 block">Имя пользователя:</span>
            <span className="font-semibold text-gray-900">{user.username}</span>
          </div>
          <div>
            <span className="text-gray-500 block">Адрес электронной почты:</span>
            <div className="flex items-center space-x-2">
              <span className="font-semibold text-gray-900">{user.email}</span>
              <span
                className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                  user.email_verified ? "bg-green-100 text-green-800" : "bg-yellow-100 text-yellow-800"
                }`}
              >
                {user.email_verified ? "Подтверждён" : "Не подтверждён"}
              </span>
            </div>
          </div>
          <div>
            <span className="text-gray-500 block">Роли в системе:</span>
            <div className="flex space-x-1.5 mt-1">
              {user.roles.map((r) => (
                <span key={r} className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                  {r}
                </span>
              ))}
            </div>
          </div>
          <div>
            <span className="text-gray-500 block">Дата регистрации:</span>
            <span className="text-gray-900">{new Date(user.created_at).toLocaleString("ru-RU")}</span>
          </div>
        </div>
      </div>

      {/* 2. Смена пароля */}
      <div className="bg-white shadow rounded-xl p-6 border border-gray-100">
        <h2 className="text-xl font-bold text-gray-900 border-b pb-4 mb-4">Смена пароля</h2>
        {passwordSuccess && (
          <div className="mb-4 bg-green-50 border-l-4 border-green-500 p-3 rounded text-sm text-green-700">
            {passwordSuccess}
          </div>
        )}
        {passwordError && (
          <div className="mb-4 bg-red-50 border-l-4 border-red-500 p-3 rounded text-sm text-red-700">
            {passwordError}
          </div>
        )}
        <form onSubmit={handleChangePassword} className="max-w-md space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Текущий пароль</label>
            <input
              type="password"
              required
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-lg shadow-sm focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Новый пароль (мин. 8 символов)</label>
            <input
              type="password"
              required
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-lg shadow-sm focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Подтверждение нового пароля</label>
            <input
              type="password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-lg shadow-sm focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={passwordLoading}
            className="py-2 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50"
          >
            {passwordLoading ? "Обновление..." : "Сохранить новый пароль"}
          </button>
        </form>
      </div>

      {/* 3. Активные сессии */}
      <div className="bg-white shadow rounded-xl p-6 border border-gray-100">
        <div className="flex justify-between items-center border-b pb-4 mb-4">
          <div>
            <h2 className="text-xl font-bold text-gray-900">Активные сессии</h2>
            <p className="text-xs text-gray-500 mt-0.5">Управление сеансами входа на различных устройствах</p>
          </div>
          <button
            onClick={handleRevokeOtherSessions}
            className="text-sm font-medium text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1.5 rounded-lg border border-red-200 transition-colors"
          >
            Завершить все другие сессии
          </button>
        </div>

        {sessionsLoading ? (
          <div className="text-sm text-gray-500 py-4">Загрузка сессий...</div>
        ) : sessionError ? (
          <div className="text-sm text-red-600 py-4">{sessionError}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-gray-500">Устройство / Клиент</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-500">IP адрес</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-500">Последняя активность</th>
                  <th className="px-4 py-2 text-right font-medium text-gray-500">Действие</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {sessions.map((s) => (
                  <tr key={s.id} className={s.is_current ? "bg-blue-50/50" : ""}>
                    <td className="px-4 py-3 text-gray-900">
                      <div className="font-medium truncate max-w-md">{s.user_agent || "Неизвестный агент"}</div>
                      {s.is_current && (
                        <span className="inline-flex px-2 py-0.5 rounded text-xs font-semibold bg-green-100 text-green-800 mt-1">
                          Текущий сеанс
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">{s.ip_address || "—"}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {new Date(s.last_activity_at).toLocaleString("ru-RU")}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {!s.is_current ? (
                        <button
                          onClick={() => handleRevokeSession(s.id)}
                          className="text-xs text-red-600 hover:text-red-800 font-medium"
                        >
                          Отозвать
                        </button>
                      ) : (
                        <span className="text-xs text-gray-400">Активна</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 4. Отложенные возможности и MFA (SEC-FLAG-01..03) */}
      <div className="bg-white shadow rounded-xl p-6 border border-gray-100">
        <h2 className="text-xl font-bold text-gray-900 border-b pb-4 mb-4">Безопасность и второй фактор</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* TOTP */}
          <div className="border border-gray-200 rounded-lg p-4 space-y-2">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold text-gray-900">Приложение-аутентификатор (TOTP)</h3>
              <span
                className={`text-xs px-2 py-0.5 rounded font-medium ${
                  capabilities?.totp_enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"
                }`}
              >
                {capabilities?.totp_enabled ? "Доступно" : "Отключено по умолчанию"}
              </span>
            </div>
            <p className="text-xs text-gray-500">
              Генерация одноразовых 6-значных кодов по RFC 6238 (Google Authenticator, YubiKey).
            </p>
            {!capabilities?.totp_enabled && (
              <div className="text-xs text-gray-400 italic">
                Флаг FEATURE_TOTP_ENABLED выключен в конфигурации сервера.
              </div>
            )}
          </div>

          {/* Passkeys */}
          <div className="border border-gray-200 rounded-lg p-4 space-y-3" data-testid="passkeys-section">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold text-gray-900">Ключи доступа Passkey (WebAuthn)</h3>
              <span
                className={`text-xs px-2 py-0.5 rounded font-medium ${
                  capabilities?.passkey_enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"
                }`}
              >
                {capabilities?.passkey_enabled ? "Доступно" : "Отключено по умолчанию"}
              </span>
            </div>
            <p className="text-xs text-gray-500">
              Вход без пароля с использованием биометрии или аппаратного ключа (FIDO2 / WebAuthn).
            </p>
            {!capabilities?.passkey_enabled ? (
              <div className="text-xs text-gray-400 italic">
                Флаг FEATURE_PASSKEY_ENABLED выключен в конфигурации сервера.
              </div>
            ) : (
              <div className="space-y-3 pt-2">
                {passkeySuccess && (
                  <div className="text-xs bg-green-50 text-green-700 p-2 rounded" data-testid="passkey-success">
                    {passkeySuccess}
                  </div>
                )}
                {passkeyError && (
                  <div className="text-xs bg-red-50 text-red-700 p-2 rounded" data-testid="passkey-error">
                    {passkeyError}
                  </div>
                )}
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Название ключа (например, Ноутбук)"
                    value={passkeyName}
                    onChange={(e) => setPasskeyName(e.target.value)}
                    className="flex-1 text-xs border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    data-testid="passkey-name-input"
                  />
                  <button
                    type="button"
                    onClick={handleRegisterPasskey}
                    disabled={passkeyLoading}
                    className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
                    data-testid="register-passkey-button"
                  >
                    {passkeyLoading ? "Регистрация..." : "Зарегистрировать Passkey"}
                  </button>
                </div>

                <div className="space-y-1">
                  <div className="text-xs font-medium text-gray-700">Зарегистрированные ключи:</div>
                  {passkeys.length === 0 ? (
                    <div className="text-xs text-gray-400 italic" data-testid="passkeys-empty">
                      Нет зарегистрированных ключей Passkey
                    </div>
                  ) : (
                    <div className="divide-y divide-gray-100" data-testid="passkeys-list">
                      {passkeys.map((p) => (
                        <div key={p.id} className="py-1.5 flex justify-between items-center text-xs" data-testid={`passkey-row-${p.id}`}>
                          <div>
                            <span className="font-medium text-gray-800">{p.name}</span>
                            <span className="text-gray-400 ml-2">ID: {p.id.slice(0, 12)}... (счётчик: {p.sign_count})</span>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleDeletePasskey(p.id)}
                            disabled={passkeyLoading}
                            className="text-red-600 hover:text-red-800 disabled:opacity-50"
                            data-testid={`delete-passkey-${p.id}`}
                          >
                            Удалить
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Резервные коды */}
          <div className="border border-gray-200 rounded-lg p-4 space-y-2">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold text-gray-900">Резервные коды восстановления</h3>
              <span
                className={`text-xs px-2 py-0.5 rounded font-medium ${
                  capabilities?.recovery_codes_enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"
                }`}
              >
                {capabilities?.recovery_codes_enabled ? "Доступно" : "Отключено по умолчанию"}
              </span>
            </div>
            <p className="text-xs text-gray-500">
              Одноразовые резервные коды для восстановления доступа при утрате второго фактора.
            </p>
            {!capabilities?.recovery_codes_enabled && (
              <div className="text-xs text-gray-400 italic">
                Флаг FEATURE_RECOVERY_CODES_ENABLED выключен в конфигурации сервера.
              </div>
            )}
          </div>

          {/* Подтверждение email */}
          <div className="border border-gray-200 rounded-lg p-4 space-y-2">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold text-gray-900">Подтверждение адреса почты</h3>
              <span
                className={`text-xs px-2 py-0.5 rounded font-medium ${
                  capabilities?.email_verification_enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"
                }`}
              >
                {capabilities?.email_verification_enabled ? "Доступно" : "Отключено по умолчанию"}
              </span>
            </div>
            <p className="text-xs text-gray-500">
              Отправка одноразовой ссылки верификации на адрес электронной почты.
            </p>
            {!capabilities?.email_verification_enabled && (
              <div className="text-xs text-gray-400 italic">
                Флаг FEATURE_EMAIL_VERIFICATION_ENABLED выключен в конфигурации сервера.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
