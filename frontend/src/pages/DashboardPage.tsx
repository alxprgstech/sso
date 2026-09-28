import { errorMessage } from "../utils/error";
import React, { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import { SessionInfo, TOTPSetupResponse } from "../types/api";
import { prepareCreationOptions, serializeCreationResponse } from "../utils/webauthn";
import { QRCodeSVG } from "qrcode.react";

export const DashboardPage: React.FC = () => {
  const { user, capabilities, refreshUser } = useAuth();

  // Состояние смены пароля
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const passwordTriggerRef = useRef<HTMLButtonElement>(null);
  const currentPasswordRef = useRef<HTMLInputElement>(null);
  const passwordDialogRef = useRef<HTMLDivElement>(null);

  const closePasswordModal = () => {
    if (passwordLoading) return;
    setShowPasswordModal(false);
    setPasswordError(null);
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    window.setTimeout(() => passwordTriggerRef.current?.focus(), 0);
  };

  useEffect(() => {
    if (!showPasswordModal) return;
    currentPasswordRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closePasswordModal();
      if (event.key === "Tab") {
        const focusable = Array.from(passwordDialogRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled)") || []);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showPasswordModal, passwordLoading]);

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

  // Состояние TOTP (SEC-FLAG-01)
  const [totpSetupData, setTotpSetupData] = useState<TOTPSetupResponse | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [totpLoading, setTotpLoading] = useState(false);
  const [totpSuccess, setTotpSuccess] = useState<string | null>(null);
  const [totpError, setTotpError] = useState<string | null>(null);
  const [totpCopyMessage, setTotpCopyMessage] = useState<string | null>(null);

  // Состояние Recovery Codes (SEC-FLAG-02)
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const [recoverySuccess, setRecoverySuccess] = useState<string | null>(null);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);

  // Состояние Email Verification (SEC-FLAG-07)
  const [emailToken, setEmailToken] = useState("");
  const [emailLoading, setEmailLoading] = useState(false);
  const [emailSuccess, setEmailSuccess] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);

  const handleSetupTotp = async () => {
    setTotpLoading(true);
    setTotpError(null);
    setTotpSuccess(null);
    setTotpCopyMessage(null);
    try {
      const data = await api.setupTotp();
      setTotpSetupData(data);
    } catch (err: unknown) {
      setTotpError(errorMessage(err, "Не удалось настроить TOTP"));
    } finally {
      setTotpLoading(false);
    }
  };

  const handleCopyTotpSecret = async () => {
    if (!totpSetupData) return;
    try {
      await navigator.clipboard.writeText(totpSetupData.secret);
      setTotpCopyMessage("Ключ скопирован");
    } catch {
      setTotpCopyMessage("Не удалось скопировать ключ. Выделите его и скопируйте вручную.");
    }
  };

  const handleConfirmTotp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!totpCode.trim()) return;
    setTotpLoading(true);
    setTotpError(null);
    try {
      const res = await api.confirmTotp(totpCode.trim());
      setTotpSuccess(res.message || "TOTP успешно активирован");
      setTotpSetupData(null);
      setTotpCode("");
      setTotpCopyMessage(null);
      await refreshUser();
    } catch (err: unknown) {
      setTotpError(errorMessage(err, "Неверный код TOTP"));
    } finally {
      setTotpLoading(false);
    }
  };

  const handleDeleteTotp = async () => {
    if (!confirm("Вы уверены, что хотите отключить TOTP? Связанные резервные коды также будут отозваны.")) return;
    setTotpLoading(true);
    setTotpError(null);
    try {
      const res = await api.deleteTotp();
      setTotpSuccess(res.message || "TOTP успешно отключен");
      setTotpSetupData(null);
      setRecoveryCodes(null);
      await refreshUser();
    } catch (err: unknown) {
      setTotpError(errorMessage(err, "Ошибка при отключении TOTP"));
    } finally {
      setTotpLoading(false);
    }
  };

  const handleGenerateRecoveryCodes = async () => {
    setRecoveryLoading(true);
    setRecoveryError(null);
    setRecoverySuccess(null);
    try {
      const data = await api.generateRecoveryCodes();
      setRecoveryCodes(data.recovery_codes);
      setRecoverySuccess("Резервные коды успешно сформированы. Сохраните их в безопасном месте!");
    } catch (err: unknown) {
      setRecoveryError(errorMessage(err, "Ошибка генерации резервных кодов"));
    } finally {
      setRecoveryLoading(false);
    }
  };

  const handleRequestEmailVerification = async () => {
    setEmailLoading(true);
    setEmailError(null);
    setEmailSuccess(null);
    try {
      const res = await api.requestEmailVerification();
      setEmailSuccess(res.message || "Письмо с подтверждением отправлено");
    } catch (err: unknown) {
      setEmailError(errorMessage(err, "Ошибка отправки подтверждения"));
    } finally {
      setEmailLoading(false);
    }
  };

  const handleConfirmEmailVerification = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!emailToken.trim()) return;
    setEmailLoading(true);
    setEmailError(null);
    setEmailSuccess(null);
    try {
      const res = await api.confirmEmailVerification(emailToken.trim());
      setEmailSuccess(res.message || "Email успешно подтвержден!");
      setEmailToken("");
      await refreshUser();
    } catch (err: unknown) {
      setEmailError(errorMessage(err, "Неверный или просроченный токен верификации"));
    } finally {
      setEmailLoading(false);
    }
  };

  const fetchSessions = async () => {
    setSessionsLoading(true);
    try {
      const data = await api.getSessions();
      setSessions(data);
    } catch (err: unknown) {
      setSessionError(errorMessage(err, "Не удалось загрузить список сессий"));
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
    } catch (err: unknown) {
      setPasskeyError(errorMessage(err, "Ошибка при регистрации Passkey"));
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
    } catch (err: unknown) {
      setPasskeyError(errorMessage(err, "Ошибка при удалении Passkey"));
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
      setShowPasswordModal(false);
      window.setTimeout(() => passwordTriggerRef.current?.focus(), 0);
    } catch (err: unknown) {
      setPasswordError(errorMessage(err, "Ошибка смены пароля"));
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleRevokeSession = async (sessionId: string) => {
    try {
      await api.revokeSession(sessionId);
      await fetchSessions();
    } catch (err: unknown) {
      alert(errorMessage(err, "Не удалось завершить сессию"));
    }
  };

  const handleRevokeOtherSessions = async () => {
    if (!confirm("Вы уверены, что хотите завершить все остальные активные сессии?")) return;
    try {
      const res = await api.revokeOtherSessions();
      alert(`Отозвано сессий: ${res.revoked_count}`);
      await fetchSessions();
    } catch (err: unknown) {
      alert(errorMessage(err, "Не удалось отозвать сессии"));
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
        <div className="flex justify-between items-center"><h2 className="text-xl font-bold text-gray-900">Смена пароля</h2><button ref={passwordTriggerRef} type="button" onClick={() => { setPasswordSuccess(null); setShowPasswordModal(true); }} className="py-2 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700">Изменить пароль</button></div>
        {passwordSuccess && (
          <div role="status" className="mt-4 bg-green-50 border-l-4 border-green-500 p-3 rounded text-sm text-green-700">
            {passwordSuccess}
          </div>
        )}
      </div>

      {showPasswordModal && (
      <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) closePasswordModal(); }}>
      <div ref={passwordDialogRef} role="dialog" aria-modal="true" aria-labelledby="change-password-title" className="bg-white rounded-xl p-6 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between mb-4"><h2 id="change-password-title" className="text-xl font-bold">Смена пароля</h2><button type="button" onClick={closePasswordModal} disabled={passwordLoading} aria-label="Закрыть окно смены пароля">✕</button></div>
        {passwordError && (
          <div role="alert" className="mb-4 bg-red-50 border-l-4 border-red-500 p-3 rounded text-sm text-red-700">
            {passwordError}
          </div>
        )}
        <form onSubmit={handleChangePassword} className="max-w-md space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Текущий пароль</label>
            <input
              ref={currentPasswordRef}
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
          <div className="flex gap-3"><button type="submit" disabled={passwordLoading} className="py-2 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50">{passwordLoading ? "Обновление..." : "Сохранить новый пароль"}</button><button type="button" onClick={closePasswordModal} disabled={passwordLoading} className="py-2 px-4 rounded-lg text-sm bg-gray-100">Отмена</button></div>
        </form>
      </div>
      </div>
      )}

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
          <div className="border border-gray-200 rounded-lg p-4 space-y-3" data-testid="totp-section">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold text-gray-900">Приложение-аутентификатор (TOTP)</h3>
              <span
                className={`text-xs px-2 py-0.5 rounded font-medium ${
                  capabilities?.totp_enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"
                }`}
              >
                {capabilities?.totp_enabled ? (user.has_totp ? "Активен" : "Доступно") : "Отключено по умолчанию"}
              </span>
            </div>
            <p className="text-xs text-gray-500">
              Генерация одноразовых 6-значных кодов по RFC 6238 (Google Authenticator, YubiKey).
            </p>
            {!capabilities?.totp_enabled ? (
              <div className="text-xs text-gray-400 italic">
                Флаг FEATURE_TOTP_ENABLED выключен в конфигурации сервера.
              </div>
            ) : (
              <div className="space-y-3 pt-2">
                {totpSuccess && (
                  <div className="text-xs bg-green-50 text-green-700 p-2 rounded" data-testid="totp-success">
                    {totpSuccess}
                  </div>
                )}
                {totpError && (
                  <div className="text-xs bg-red-50 text-red-700 p-2 rounded" data-testid="totp-error">
                    {totpError}
                  </div>
                )}
                {user.has_totp ? (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-green-700 font-medium">✓ Двухфакторная аутентификация TOTP включена</span>
                    <button
                      type="button"
                      onClick={handleDeleteTotp}
                      disabled={totpLoading}
                      className="text-xs text-red-600 hover:text-red-800 font-medium disabled:opacity-50"
                      data-testid="disable-totp-button"
                    >
                      Отключить
                    </button>
                  </div>
                ) : totpSetupData ? (
                  <form onSubmit={handleConfirmTotp} className="space-y-3 bg-gray-50 p-3 rounded-lg border">
                    <div className="text-xs text-gray-700">Отсканируйте QR-код приложением-аутентификатором:</div>
                    <div className="flex justify-center" data-testid="totp-qr-code">
                      <QRCodeSVG value={totpSetupData.otpauth_url} size={192} level="M" marginSize={4} title="QR-код для подключения ALXPRGS SSO" />
                    </div>
                    <div className="text-xs text-gray-600">Или введите секретный ключ вручную:</div>
                    <div className="flex items-center gap-2">
                      <div className="min-w-0 flex-1 text-xs font-mono font-bold bg-white p-2 rounded border break-all select-all text-blue-900" data-testid="totp-secret">
                        {totpSetupData.secret}
                      </div>
                      <button type="button" onClick={handleCopyTotpSecret} className="text-xs bg-white border border-gray-300 px-3 py-2 rounded hover:bg-gray-100" data-testid="copy-totp-secret-button">Копировать</button>
                    </div>
                    {totpCopyMessage && <div role="status" className="text-xs text-gray-700">{totpCopyMessage}</div>}
                    <div className="text-xs text-gray-600">Введите 6-значный код для подтверждения:</div>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        required
                        placeholder="000000"
                        maxLength={6}
                        value={totpCode}
                        onChange={(e) => setTotpCode(e.target.value)}
                        className="flex-1 text-xs border border-gray-300 rounded px-2 py-1.5 font-mono text-center tracking-widest"
                        data-testid="totp-code-input"
                      />
                      <button
                        type="submit"
                        disabled={totpLoading}
                        className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
                        data-testid="confirm-totp-button"
                      >
                        {totpLoading ? "Проверка..." : "Подтвердить"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setTotpSetupData(null)}
                        className="text-xs text-gray-600 bg-gray-200 px-3 py-1.5 rounded hover:bg-gray-300"
                      >
                        Отмена
                      </button>
                    </div>
                  </form>
                ) : (
                  <button
                    type="button"
                    onClick={handleSetupTotp}
                    disabled={totpLoading}
                    className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
                    data-testid="setup-totp-button"
                  >
                    {totpLoading ? "Загрузка..." : "Настроить TOTP"}
                  </button>
                )}
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
          <div className="border border-gray-200 rounded-lg p-4 space-y-3" data-testid="recovery-codes-section">
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
            {!capabilities?.recovery_codes_enabled ? (
              <div className="text-xs text-gray-400 italic">
                Флаг FEATURE_RECOVERY_CODES_ENABLED выключен в конфигурации сервера.
              </div>
            ) : (
              <div className="space-y-3 pt-2">
                {recoverySuccess && (
                  <div className="text-xs bg-green-50 text-green-700 p-2 rounded" data-testid="recovery-success">
                    {recoverySuccess}
                  </div>
                )}
                {recoveryError && (
                  <div className="text-xs bg-red-50 text-red-700 p-2 rounded" data-testid="recovery-error">
                    {recoveryError}
                  </div>
                )}
                {!user.has_totp ? (
                  <div className="text-xs text-amber-700 bg-amber-50 p-2 rounded border border-amber-200">
                    Резервные коды требуют предварительной активации TOTP аутентификатора.
                  </div>
                ) : (
                  <div>
                    <button
                      type="button"
                      onClick={handleGenerateRecoveryCodes}
                      disabled={recoveryLoading}
                      className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50 mb-2"
                      data-testid="generate-recovery-codes-button"
                    >
                      {recoveryLoading ? "Генерация..." : "Сгенерировать новые коды"}
                    </button>
                    {recoveryCodes && (
                      <div className="bg-amber-50 p-3 rounded-lg border border-amber-200 space-y-2 mt-2" data-testid="recovery-codes-display">
                        <div className="text-xs font-semibold text-amber-800">
                          ⚠️ Сохраните эти коды прямо сейчас! Они отображаются только один раз:
                        </div>
                        <div className="grid grid-cols-2 gap-1.5 font-mono text-xs select-all text-gray-900">
                          {recoveryCodes.map((code, idx) => (
                            <div key={idx} className="bg-white p-1.5 rounded border text-center font-bold">
                              {code}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Подтверждение email */}
          <div className="border border-gray-200 rounded-lg p-4 space-y-3" data-testid="email-verification-section">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold text-gray-900">Подтверждение адреса почты</h3>
              <span
                className={`text-xs px-2 py-0.5 rounded font-medium ${
                  capabilities?.email_verification_enabled
                    ? user.email_verified
                      ? "bg-green-100 text-green-800"
                      : "bg-yellow-100 text-yellow-800"
                    : "bg-gray-100 text-gray-600"
                }`}
              >
                {capabilities?.email_verification_enabled
                  ? user.email_verified
                    ? "Подтверждён"
                    : "Не подтверждён"
                  : "Отключено по умолчанию"}
              </span>
            </div>
            <p className="text-xs text-gray-500">
              Отправка одноразовой ссылки верификации на адрес электронной почты.
            </p>
            {!capabilities?.email_verification_enabled ? (
              <div className="text-xs text-gray-400 italic">
                Флаг FEATURE_EMAIL_VERIFICATION_ENABLED выключен в конфигурации сервера.
              </div>
            ) : (
              <div className="space-y-3 pt-2">
                {emailSuccess && (
                  <div className="text-xs bg-green-50 text-green-700 p-2 rounded" data-testid="email-success">
                    {emailSuccess}
                  </div>
                )}
                {emailError && (
                  <div className="text-xs bg-red-50 text-red-700 p-2 rounded" data-testid="email-error">
                    {emailError}
                  </div>
                )}
                {user.email_verified ? (
                  <div className="text-xs text-green-700 font-medium">
                    ✓ Ваш адрес электронной почты ({user.email}) успешно подтверждён.
                  </div>
                ) : (
                  <div className="space-y-2">
                    <button
                      type="button"
                      onClick={handleRequestEmailVerification}
                      disabled={emailLoading}
                      className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
                      data-testid="request-email-verification-button"
                    >
                      {emailLoading ? "Отправка..." : "Отправить письмо с подтверждением"}
                    </button>
                    <form onSubmit={handleConfirmEmailVerification} className="flex gap-2 pt-1">
                      <input
                        type="text"
                        required
                        placeholder="Токен подтверждения из письма"
                        value={emailToken}
                        onChange={(e) => setEmailToken(e.target.value)}
                        className="flex-1 text-xs border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
                        data-testid="email-token-input"
                      />
                      <button
                        type="submit"
                        disabled={emailLoading}
                        className="text-xs bg-green-600 text-white px-3 py-1.5 rounded hover:bg-green-700 disabled:opacity-50"
                        data-testid="confirm-email-button"
                      >
                        Подтвердить
                      </button>
                    </form>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
