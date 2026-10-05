import React from "react";
import { Link, useParams } from "react-router";
import { SectionNavigation } from "../components/SectionNavigation";
import { DataTable } from "../components/ui/DataTable";
import { Badge } from "../components/ui/controls";
import {
  Alert,
  Button,
  CopyButton,
  Input,
  OTPInput,
  PasswordInput,
  Skeleton,
} from "../components/ui/controls";
import { QRCodeSVG } from "qrcode.react";
import { AccessibleDialog } from "../components/AccessibleDialog";
import { useAccountController } from "../features/account/useAccountController";
export const DashboardPage: React.FC = () => {
  const {
    user,
    capabilities,
    pageError,
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    confirmPassword,
    setConfirmPassword,
    passwordSuccess,
    setPasswordSuccess,
    passwordError,
    passwordLoading,
    showPasswordModal,
    setShowPasswordModal,
    passwordTriggerRef,
    currentPasswordRef,
    closePasswordModal,
    sessions,
    sessionsLoading,
    sessionError,
    passkeys,
    passkeyName,
    setPasskeyName,
    passkeyLoading,
    passkeySuccess,
    passkeyError,
    passkeysReadState,
    fetchPasskeys,
    totpSetupData,
    setTotpSetupData,
    totpCode,
    setTotpCode,
    totpLoading,
    totpSuccess,
    totpError,
    totpCopyMessage,
    recoveryCodes,
    recoveryLoading,
    recoverySuccess,
    recoveryError,
    emailToken,
    setEmailToken,
    emailLoading,
    emailSuccess,
    emailError,
    handleSetupTotp,
    handleCopyTotpSecret,
    handleConfirmTotp,
    handleDeleteTotp,
    handleGenerateRecoveryCodes,
    handleRequestEmailVerification,
    handleConfirmEmailVerification,
    handleRegisterPasskey,
    handleDeletePasskey,
    handleChangePassword,
    handleRevokeSession,
    handleRevokeOtherSessions,
  } = useAccountController();
  const { section = "profile" } = useParams();
  const titles: Record<string, string> = {
    profile: "Профиль",
    security: "Безопасность",
    sessions: "Активные сессии",
    privacy: "Конфиденциальность",
  };
  if (!user) return null;
  if (!(section in titles))
    return (
      <SectionNavigation mode="account">
        <h1>Раздел не найден</h1>
        <Link to="/">К профилю</Link>
      </SectionNavigation>
    );

  return (
    <SectionNavigation mode="account">
      <div className="space-y-8 max-w-5xl">
        <header>
          <h1>{titles[section]}</h1>
          <p className="mt-2 text-secondary">
            Управление учётной записью и доступом к сервисам.
          </p>
        </header>
        {pageError && <Alert>{pageError}</Alert>}
        {section === "profile" && (
          <>
            <div className="section-panel">
              <h2 className="text-xl font-semibold text-primary mb-6">
                Учётная запись
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-secondary block">
                    Имя пользователя:
                  </span>
                  <span className="font-semibold text-primary">
                    {user.username}
                  </span>
                </div>
                <div>
                  <span className="text-secondary block">
                    Адрес электронной почты:
                  </span>
                  <div className="flex items-center space-x-2">
                    <span className="font-semibold text-primary">
                      {user.email}
                    </span>
                    <span
                      className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                        user.email_verified
                          ? "bg-success-soft text-success"
                          : "bg-warning-soft text-warning"
                      }`}
                    >
                      {user.email_verified ? "Подтверждён" : "Не подтверждён"}
                    </span>
                  </div>
                </div>
                <div>
                  <span className="text-secondary block">Роли в системе:</span>
                  <div className="flex space-x-1.5 mt-1">
                    {user.roles.map((r) => (
                      <Badge key={r}>{r}</Badge>
                    ))}
                  </div>
                </div>
                <div>
                  <span className="text-secondary block">
                    Дата регистрации:
                  </span>
                  <span className="text-primary">
                    {new Date(user.created_at).toLocaleString("ru-RU")}
                  </span>
                </div>
              </div>
            </div>

            <Link to="/account/security" className="text-brand underline">
              Настроить безопасность учётной записи
            </Link>
          </>
        )}
        {section === "security" && (
          <>
            <div className="section-panel">
              <div className="flex flex-wrap gap-3 justify-between items-center">
                <h2 className="text-xl font-bold text-primary">Смена пароля</h2>
                <Button
                  ref={passwordTriggerRef}
                  type="button"
                  onClick={() => {
                    setPasswordSuccess(null);
                    setShowPasswordModal(true);
                  }}
                  variant="primary"
                >
                  Изменить пароль
                </Button>
              </div>
              {passwordSuccess && (
                <div
                  role="status"
                  className="mt-4 bg-success-soft border-l-4 border-success p-3 rounded text-sm text-success"
                >
                  {passwordSuccess}
                </div>
              )}
            </div>

            {showPasswordModal && (
              <div
                className="contents"
                onMouseDown={(e) => {
                  if (e.target === e.currentTarget) closePasswordModal();
                }}
              >
                <AccessibleDialog
                  label="Смена пароля"
                  onClose={closePasswordModal}
                  busy={passwordLoading}
                  initialFocus={currentPasswordRef}
                  className="max-w-md"
                >
                  <div className="flex items-center justify-between mb-4">
                    <h2
                      id="change-password-title"
                      className="text-xl font-bold"
                    >
                      Смена пароля
                    </h2>
                    <Button
                      type="button"
                      onClick={closePasswordModal}
                      disabled={passwordLoading}
                      aria-label="Закрыть окно смены пароля"
                    >
                      Закрыть
                    </Button>
                  </div>
                  {passwordError && (
                    <div
                      role="alert"
                      className="mb-4 bg-danger-soft border-l-4 border-danger p-3 rounded text-sm text-danger"
                    >
                      {passwordError}
                    </div>
                  )}
                  <form
                    onSubmit={handleChangePassword}
                    className="max-w-md space-y-4"
                  >
                    <div>
                      <label
                        htmlFor="dashboardpage-field-1"
                        className="block text-sm font-medium text-primary"
                      >
                        Текущий пароль
                      </label>
                      <PasswordInput
                        id="dashboardpage-field-1"
                        ref={currentPasswordRef}
                        autoComplete="current-password"
                        maxLength={128}
                        disabled={passwordLoading}
                        type="password"
                        required
                        value={currentPassword}
                        onChange={(e) => setCurrentPassword(e.target.value)}
                        className="mt-1 w-full"
                      />
                    </div>
                    <div>
                      <label
                        htmlFor="dashboardpage-field-2"
                        className="block text-sm font-medium text-primary"
                      >
                        Новый пароль (мин. 15 символов)
                      </label>
                      <PasswordInput
                        id="dashboardpage-field-2"
                        type="password"
                        autoComplete="new-password"
                        minLength={15}
                        maxLength={128}
                        disabled={passwordLoading}
                        required
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        className="mt-1 w-full"
                      />
                    </div>
                    <div>
                      <label
                        htmlFor="dashboardpage-field-3"
                        className="block text-sm font-medium text-primary"
                      >
                        Подтверждение нового пароля
                      </label>
                      <PasswordInput
                        id="dashboardpage-field-3"
                        type="password"
                        autoComplete="new-password"
                        minLength={15}
                        maxLength={128}
                        disabled={passwordLoading}
                        required
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        className="mt-1 w-full"
                      />
                    </div>
                    <div className="flex gap-3">
                      <Button
                        type="submit"
                        disabled={passwordLoading}
                        variant="primary"
                      >
                        {passwordLoading
                          ? "Обновление..."
                          : "Сохранить новый пароль"}
                      </Button>
                      <Button
                        type="button"
                        onClick={closePasswordModal}
                        disabled={passwordLoading}
                      >
                        Отмена
                      </Button>
                    </div>
                  </form>
                </AccessibleDialog>
              </div>
            )}
          </>
        )}
        {section === "sessions" && (
          <>
            <div className="section-panel">
              <div className="flex flex-wrap gap-3 justify-between items-center border-b pb-4 mb-4">
                <div>
                  <h2 className="text-xl font-bold text-primary">
                    Активные сессии
                  </h2>
                  <p className="text-xs text-secondary mt-0.5">
                    Управление сеансами входа на различных устройствах
                  </p>
                </div>
                <Button onClick={handleRevokeOtherSessions} variant="danger">
                  Завершить все другие сессии
                </Button>
              </div>

              <DataTable
                caption="Активные сессии"
                rows={sessions}
                rowKey={(s) => s.id}
                loading={sessionsLoading}
                error={sessionError || undefined}
                empty="Других активных сессий нет"
                columns={[
                  {
                    id: "device",
                    label: "Устройство / Клиент",
                    render: (s) => (
                      <div className="space-y-2">
                        <p className="break-words">
                          {s.user_agent || "Неизвестное устройство"}
                        </p>
                        {s.is_current && (
                          <Badge tone="success">Текущий сеанс</Badge>
                        )}
                      </div>
                    ),
                  },
                  {
                    id: "ip",
                    label: "IP адрес",
                    render: (s) => (
                      <span className="font-mono text-xs">
                        {s.ip_address || "—"}
                      </span>
                    ),
                  },
                  {
                    id: "activity",
                    label: "Последняя активность",
                    sortValue: (s) => s.last_activity_at,
                    render: (s) =>
                      new Date(s.last_activity_at).toLocaleString("ru-RU"),
                  },
                  {
                    id: "action",
                    label: "Действие",
                    render: (s) =>
                      s.is_current ? (
                        <span className="text-secondary">Активна</span>
                      ) : (
                        <Button
                          variant="danger"
                          onClick={() => handleRevokeSession(s.id)}
                        >
                          Отозвать
                        </Button>
                      ),
                  },
                ]}
              />
            </div>
          </>
        )}
        {section === "security" && (
          <>
            {/* 4. Отложенные возможности и MFA (SEC-FLAG-01..03) */}
            <div className="section-panel">
              <h2 className="text-xl font-bold text-primary border-b pb-4 mb-4">
                Безопасность и второй фактор
              </h2>
              <div className="space-y-6">
                {/* TOTP */}
                <div
                  className="security-item space-y-4"
                  data-testid="totp-section"
                >
                  <div className="flex flex-wrap gap-3 justify-between items-center">
                    <h3 className="font-semibold text-primary">
                      Приложение-аутентификатор (TOTP)
                    </h3>
                    <span
                      className={`text-xs px-2 py-0.5 rounded font-medium ${
                        capabilities?.totp_enabled
                          ? "bg-success-soft text-success"
                          : "bg-raised text-secondary"
                      }`}
                    >
                      {capabilities?.totp_enabled
                        ? user.has_totp
                          ? "Активен"
                          : "Доступно"
                        : "Недоступно"}
                    </span>
                  </div>
                  <p className="text-xs text-secondary">
                    Подтверждайте вход шестизначным кодом из
                    приложения-аутентификатора.
                  </p>
                  {!capabilities?.totp_enabled ? (
                    <div className="text-xs text-tertiary italic">
                      Администратор пока не включил этот способ защиты.
                    </div>
                  ) : (
                    <div className="space-y-3 pt-2">
                      {totpSuccess && (
                        <div
                          className="text-xs bg-success-soft text-success p-2 rounded"
                          role="status"
                          data-testid="totp-success"
                        >
                          {totpSuccess}
                        </div>
                      )}
                      {totpError && (
                        <div
                          className="text-xs bg-danger-soft text-danger p-2 rounded"
                          role="alert"
                          data-testid="totp-error"
                        >
                          {totpError}
                        </div>
                      )}
                      {user.has_totp ? (
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-success font-medium">
                            ✓ Двухфакторная аутентификация TOTP включена
                          </span>
                          <Button
                            type="button"
                            onClick={handleDeleteTotp}
                            disabled={totpLoading}
                            variant="danger"
                            data-testid="disable-totp-button"
                          >
                            Отключить
                          </Button>
                        </div>
                      ) : totpSetupData ? (
                        <form
                          onSubmit={handleConfirmTotp}
                          className="space-y-3 bg-canvas p-3 rounded-lg border"
                        >
                          <div className="text-xs text-primary">
                            Отсканируйте QR-код приложением-аутентификатором:
                          </div>
                          <div
                            className="flex justify-center"
                            data-sentry-block
                            data-sso-sensitive="true"
                            data-testid="totp-qr-code"
                          >
                            <div className="qr-surface">
                              <QRCodeSVG
                                role="img"
                                aria-label="QR-код для подключения ALXPRGS SSO"
                                value={totpSetupData.otpauth_url}
                                size={192}
                                level="M"
                                marginSize={4}
                                title="QR-код для подключения ALXPRGS SSO"
                              />
                            </div>
                          </div>
                          <div className="text-xs text-secondary">
                            Или введите секретный ключ вручную:
                          </div>
                          <div className="flex items-center gap-2">
                            <div
                              className="min-w-0 flex-1 text-xs font-mono font-bold bg-surface p-2 rounded border break-all select-all text-brand"
                              data-sentry-block
                              data-sso-sensitive="true"
                              data-testid="totp-secret"
                            >
                              {totpSetupData.secret}
                            </div>
                            <Button
                              type="button"
                              onClick={handleCopyTotpSecret}
                              data-testid="copy-totp-secret-button"
                            >
                              Копировать
                            </Button>
                          </div>
                          {totpCopyMessage && (
                            <div role="status" className="text-xs text-primary">
                              {totpCopyMessage}
                            </div>
                          )}
                          <div className="text-xs text-secondary">
                            Введите 6-значный код для подтверждения:
                          </div>
                          <div className="flex gap-2">
                            <Input
                              type="text"
                              aria-label="Код приложения-аутентификатора"
                              autoComplete="one-time-code"
                              inputMode="numeric"
                              pattern="[0-9]{6}"
                              required
                              placeholder="000000"
                              maxLength={6}
                              value={totpCode}
                              onChange={(e) => setTotpCode(e.target.value)}
                              className="flex-1"
                              data-testid="totp-code-input"
                            />
                            <Button
                              type="submit"
                              disabled={totpLoading}
                              variant="primary"
                              data-testid="confirm-totp-button"
                            >
                              {totpLoading ? "Проверка..." : "Подтвердить"}
                            </Button>
                            <Button
                              type="button"
                              onClick={() => setTotpSetupData(null)}
                            >
                              Отмена
                            </Button>
                          </div>
                        </form>
                      ) : (
                        <Button
                          type="button"
                          onClick={handleSetupTotp}
                          disabled={totpLoading}
                          variant="primary"
                          data-testid="setup-totp-button"
                        >
                          {totpLoading ? "Загрузка..." : "Настроить TOTP"}
                        </Button>
                      )}
                    </div>
                  )}
                </div>

                {/* Passkeys */}
                <div
                  className="security-item space-y-4"
                  data-testid="passkeys-section"
                >
                  <div className="flex flex-wrap gap-3 justify-between items-center">
                    <h3 className="font-semibold text-primary">
                      Ключи доступа (Passkey)
                    </h3>
                    <span
                      className={`text-xs px-2 py-0.5 rounded font-medium ${
                        capabilities?.passkey_enabled
                          ? "bg-success-soft text-success"
                          : "bg-raised text-secondary"
                      }`}
                    >
                      {capabilities?.passkey_enabled
                        ? "Доступно"
                        : "Недоступно"}
                    </span>
                  </div>
                  <p className="text-xs text-secondary">
                    Вход без пароля с использованием биометрии или аппаратного
                    ключа на вашем устройстве.
                  </p>
                  {!capabilities?.passkey_enabled ? (
                    <div className="text-xs text-tertiary italic">
                      Администратор пока не включил ключи доступа.
                    </div>
                  ) : (
                    <div className="space-y-3 pt-2">
                      {passkeySuccess && (
                        <div
                          className="text-xs bg-success-soft text-success p-2 rounded"
                          role="status"
                          data-testid="passkey-success"
                        >
                          {passkeySuccess}
                        </div>
                      )}
                      {passkeyError && (
                        <div
                          className="text-xs bg-danger-soft text-danger p-2 rounded"
                          role="alert"
                          data-testid="passkey-error"
                        >
                          {passkeyError}
                        </div>
                      )}
                      <div className="flex gap-2">
                        <Input
                          type="text"
                          aria-label="Название ключа доступа"
                          maxLength={128}
                          placeholder="Название ключа (например, Ноутбук)"
                          value={passkeyName}
                          onChange={(e) => setPasskeyName(e.target.value)}
                          className="flex-1"
                          data-testid="passkey-name-input"
                        />
                        <Button
                          type="button"
                          onClick={handleRegisterPasskey}
                          disabled={passkeyLoading}
                          variant="primary"
                          data-testid="register-passkey-button"
                        >
                          {passkeyLoading
                            ? "Регистрация..."
                            : "Зарегистрировать Passkey"}
                        </Button>
                      </div>

                      <div className="space-y-1">
                        <div className="text-xs font-medium text-primary">
                          Зарегистрированные ключи:
                        </div>
                        {passkeysReadState === "idle" ||
                        passkeysReadState === "loading" ? (
                          <Skeleton label="Загрузка ключей доступа" rows={2} />
                        ) : passkeysReadState === "error" ? (
                          <div className="space-y-3">
                            <Alert>
                              Не удалось загрузить ключи доступа.
                            </Alert>
                            <Button
                              type="button"
                              onClick={() => void fetchPasskeys()}
                            >
                              Повторить загрузку ключей
                            </Button>
                          </div>
                        ) : passkeys.length === 0 ? (
                          <div
                            className="text-xs text-tertiary italic"
                            data-testid="passkeys-empty"
                          >
                            Нет зарегистрированных ключей Passkey
                          </div>
                        ) : (
                          <div
                            className="divide-y divide-line"
                            data-testid="passkeys-list"
                          >
                            {passkeys.map((p) => (
                              <div
                                key={p.id}
                                className="py-1.5 flex flex-wrap gap-3 justify-between items-center text-xs"
                                data-testid={`passkey-row-${p.id}`}
                              >
                                <div>
                                  <span className="font-medium text-primary">
                                    {p.name}
                                  </span>
                                  <span className="text-tertiary ml-2">
                                    Ключ доступа
                                  </span>
                                </div>
                                <Button
                                  type="button"
                                  onClick={() => handleDeletePasskey(p.id)}
                                  disabled={passkeyLoading}
                                  variant="danger"
                                  data-testid={`delete-passkey-${p.id}`}
                                >
                                  Удалить
                                </Button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Резервные коды */}
                <div
                  className="security-item space-y-4"
                  data-testid="recovery-codes-section"
                >
                  <div className="flex flex-wrap gap-3 justify-between items-center">
                    <h3 className="font-semibold text-primary">
                      Резервные коды восстановления
                    </h3>
                    <span
                      className={`text-xs px-2 py-0.5 rounded font-medium ${
                        capabilities?.recovery_codes_enabled
                          ? "bg-success-soft text-success"
                          : "bg-raised text-secondary"
                      }`}
                    >
                      {capabilities?.recovery_codes_enabled
                        ? "Доступно"
                        : "Недоступно"}
                    </span>
                  </div>
                  <p className="text-xs text-secondary">
                    Одноразовые резервные коды для восстановления доступа при
                    утрате второго фактора.
                  </p>
                  {!capabilities?.recovery_codes_enabled ? (
                    <div className="text-xs text-tertiary italic">
                      Администратор пока не включил резервные коды.
                    </div>
                  ) : (
                    <div className="space-y-3 pt-2">
                      {recoverySuccess && (
                        <div
                          className="text-xs bg-success-soft text-success p-2 rounded"
                          role="status"
                          data-testid="recovery-success"
                        >
                          {recoverySuccess}
                        </div>
                      )}
                      {recoveryError && (
                        <div
                          className="text-xs bg-danger-soft text-danger p-2 rounded"
                          role="alert"
                          data-testid="recovery-error"
                        >
                          {recoveryError}
                        </div>
                      )}
                      {!user.has_totp ? (
                        <div className="text-xs text-warning bg-warning-soft p-2 rounded border border-warning">
                          Резервные коды требуют предварительной активации TOTP
                          аутентификатора.
                        </div>
                      ) : (
                        <div>
                          <Button
                            type="button"
                            onClick={handleGenerateRecoveryCodes}
                            disabled={recoveryLoading}
                            className="mb-2"
                            variant="primary"
                            data-testid="generate-recovery-codes-button"
                          >
                            {recoveryLoading
                              ? "Генерация..."
                              : "Сгенерировать новые коды"}
                          </Button>
                          {recoveryCodes && (
                            <div
                              className="bg-warning-soft p-3 rounded-lg border border-warning space-y-2 mt-2"
                              data-sentry-block
                              data-sso-sensitive="true"
                              data-testid="recovery-codes-display"
                            >
                              <div className="text-xs font-semibold text-warning">
                                Сохраните эти коды сейчас. Они отображаются
                                только один раз:
                              </div>
                              <CopyButton
                                value={recoveryCodes.join("\n")}
                                label="Копировать все коды"
                              />
                              <div className="grid grid-cols-2 gap-1.5 font-mono text-xs select-all text-primary">
                                {recoveryCodes.map((code, idx) => (
                                  <div
                                    key={idx}
                                    className="bg-surface p-1.5 rounded border text-center font-bold"
                                  >
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
                <div
                  className="security-item space-y-4"
                  data-testid="email-verification-section"
                >
                  <div className="flex flex-wrap gap-3 justify-between items-center">
                    <h3 className="font-semibold text-primary">
                      Подтверждение адреса почты
                    </h3>
                    <span
                      className={`text-xs px-2 py-0.5 rounded font-medium ${
                        capabilities?.email_verification_enabled
                          ? user.email_verified
                            ? "bg-success-soft text-success"
                            : "bg-warning-soft text-warning"
                          : "bg-raised text-secondary"
                      }`}
                    >
                      {capabilities?.email_verification_enabled
                        ? user.email_verified
                          ? "Подтверждён"
                          : "Не подтверждён"
                        : "Недоступно"}
                    </span>
                  </div>
                  <p className="text-xs text-secondary">
                    Отправка шестизначного кода и одноразовой ссылки на адрес
                    электронной почты.
                  </p>
                  {!capabilities?.email_verification_enabled ? (
                    <div className="text-xs text-tertiary italic">
                      Не удалось загрузить доступность подтверждения почты.
                    </div>
                  ) : (
                    <div className="space-y-3 pt-2">
                      {emailSuccess && (
                        <div
                          className="text-xs bg-success-soft text-success p-2 rounded"
                          role="status"
                          data-testid="email-success"
                        >
                          {emailSuccess}
                        </div>
                      )}
                      {emailError && (
                        <div
                          className="text-xs bg-danger-soft text-danger p-2 rounded"
                          role="alert"
                          data-testid="email-error"
                        >
                          {emailError}
                        </div>
                      )}
                      {user.email_verified ? (
                        <div className="text-xs text-success font-medium">
                          ✓ Ваш адрес электронной почты ({user.email}) успешно
                          подтверждён.
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <Button
                            type="button"
                            onClick={handleRequestEmailVerification}
                            disabled={emailLoading}
                            variant="primary"
                            data-testid="request-email-verification-button"
                          >
                            {emailLoading
                              ? "Отправка..."
                              : "Отправить письмо с подтверждением"}
                          </Button>
                          <form
                            onSubmit={handleConfirmEmailVerification}
                            className="flex gap-2 pt-1"
                          >
                            <OTPInput
                              type="text"
                              required
                              placeholder="Код из 6 цифр"
                              aria-label="Код подтверждения email"
                              inputMode="numeric"
                              pattern="[0-9]{6}"
                              maxLength={6}
                              value={emailToken}
                              onChange={(e) => setEmailToken(e.target.value)}
                              className="flex-1"
                              data-testid="email-token-input"
                            />
                            <Button
                              type="submit"
                              disabled={emailLoading}
                              variant="primary"
                              data-testid="confirm-email-button"
                            >
                              Подтвердить
                            </Button>
                          </form>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
        {section === "privacy" && (
          <section
            className="mt-6 bg-surface border border-line rounded-xl p-6"
            aria-labelledby="privacy-account-title"
          >
            <h2 id="privacy-account-title" className="text-xl font-bold">
              Управление данными
            </h2>
            <p>
              Удаление через 14 дней с возможностью отмены до назначенного
              срока.
            </p>
            <a href="/account-deletion" className="underline text-danger">
              Удаление аккаунта
            </a>
            <p className="mt-4 text-secondary">
              Необязательная аналитика и запись сеанса включаются только с
              вашего согласия. Выбор можно изменить в панели «Cookie и
              аналитика».
            </p>
          </section>
        )}
      </div>
    </SectionNavigation>
  );
};
