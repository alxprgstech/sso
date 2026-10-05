import type { ReactNode } from "react";
import { Link } from "react-router";
import { DataTable } from "../../components/ui/DataTable";
import { Badge } from "../../components/ui/controls";
import {
  Alert,
  Button,
  CopyButton,
  Input,
  OTPInput,
  PasswordInput,
  Skeleton,
} from "../../components/ui/controls";
import { QRCodeSVG } from "qrcode.react";
import { AccessibleDialog } from "../../components/AccessibleDialog";
import type { useAccountController } from "./useAccountController";

export type AccountViewModel = ReturnType<typeof useAccountController> & {
  user: NonNullable<ReturnType<typeof useAccountController>["user"]>;
};

function FeatureStatus({
  enabled,
  label = "Доступно",
  warning = false,
}: {
  enabled: boolean;
  label?: string;
  warning?: boolean;
}) {
  const enabledTone = warning
    ? "bg-warning-soft text-warning"
    : "bg-success-soft text-success";
  const tone = enabled ? enabledTone : "bg-raised text-secondary";
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-medium ${tone}`}>
      {enabled ? label : "Недоступно"}
    </span>
  );
}

export function AccountSecurity({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const { showPasswordModal, closePasswordModal } = controller;
  return (
    <>
      <AccountPassword controller={controller} />
      {showPasswordModal && (
        <div
          className="contents"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closePasswordModal();
          }}
        >
          <PasswordChangeDialog controller={controller} />
        </div>
      )}
      <div className="section-panel">
        <h2 className="text-xl font-bold text-primary border-b pb-4 mb-4">
          Безопасность и второй фактор
        </h2>
        <div className="space-y-6">
          {securityFeatures(controller).map((feature) => (
            <SecurityFeature key={feature.testId} {...feature} />
          ))}
        </div>
      </div>
    </>
  );
}

export function AccountProfile({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const { user } = controller;
  return (
    <>
      <div className="section-panel">
        <h2 className="text-xl font-semibold text-primary mb-6">
          Учётная запись
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-secondary block">Имя пользователя:</span>
            <span className="font-semibold text-primary">{user.username}</span>
          </div>
          <div>
            <span className="text-secondary block">
              Адрес электронной почты:
            </span>
            <div className="flex items-center space-x-2">
              <span className="font-semibold text-primary">{user.email}</span>
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
            <span className="text-secondary block">Дата регистрации:</span>
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
  );
}

export function AccountPassword({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const {
    passwordSuccess,
    setPasswordSuccess,
    setShowPasswordModal,
    passwordTriggerRef,
  } = controller;
  return (
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
  );
}

export function PasswordChangeDialog({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const {
    passwordError,
    passwordLoading,
    currentPasswordRef,
    closePasswordModal,
  } = controller;
  return (
    <AccessibleDialog
      label="Смена пароля"
      onClose={closePasswordModal}
      busy={passwordLoading}
      initialFocus={currentPasswordRef}
      className="max-w-md"
    >
      <div className="flex items-center justify-between mb-4">
        <h2 id="change-password-title" className="text-xl font-bold">
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
      <PasswordChangeForm controller={controller} />
    </AccessibleDialog>
  );
}

export function PasswordChangeForm({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const { passwordLoading, closePasswordModal, handleChangePassword } =
    controller;
  return (
    <form onSubmit={handleChangePassword} className="max-w-md space-y-4">
      <PasswordFields controller={controller} />
      <div className="flex gap-3">
        <Button type="submit" disabled={passwordLoading} variant="primary">
          {passwordLoading ? "Обновление..." : "Сохранить новый пароль"}
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
  );
}

function passwordFields(controller: AccountViewModel) {
  return [
    {
      id: "dashboardpage-field-1",
      label: "Текущий пароль",
      value: controller.currentPassword,
      setValue: controller.setCurrentPassword,
      autoComplete: "current-password",
      reference: controller.currentPasswordRef,
      minimum: undefined,
    },
    {
      id: "dashboardpage-field-2",
      label: "Новый пароль (мин. 15 символов)",
      value: controller.newPassword,
      setValue: controller.setNewPassword,
      autoComplete: "new-password",
      minimum: 15,
    },
    {
      id: "dashboardpage-field-3",
      label: "Подтверждение нового пароля",
      value: controller.confirmPassword,
      setValue: controller.setConfirmPassword,
      autoComplete: "new-password",
      minimum: 15,
    },
  ];
}

function PasswordFields({ controller }: { controller: AccountViewModel }) {
  return (
    <>
      {passwordFields(controller).map((field) => (
        <div key={field.id}>
          <label
            htmlFor={field.id}
            className="block text-sm font-medium text-primary"
          >
            {field.label}
          </label>
          <PasswordInput
            id={field.id}
            ref={field.reference}
            type="password"
            required
            autoComplete={field.autoComplete}
            minLength={field.minimum}
            maxLength={128}
            disabled={controller.passwordLoading}
            value={field.value}
            onChange={(event) => field.setValue(event.target.value)}
            className="mt-1 w-full"
          />
        </div>
      ))}
    </>
  );
}

export function AccountSessions({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const { handleRevokeOtherSessions } = controller;
  return (
    <>
      <div className="section-panel">
        <div className="flex flex-wrap gap-3 justify-between items-center border-b pb-4 mb-4">
          <div>
            <h2 className="text-xl font-bold text-primary">Активные сессии</h2>
            <p className="text-xs text-secondary mt-0.5">
              Управление сеансами входа на различных устройствах
            </p>
          </div>
          <Button onClick={handleRevokeOtherSessions} variant="danger">
            Завершить все другие сессии
          </Button>
        </div>

        <AccountSessionTable controller={controller} />
      </div>
    </>
  );
}

export function AccountSessionTable({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const { sessions, sessionsLoading, sessionError, handleRevokeSession } =
    controller;
  return (
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
              {s.is_current && <Badge tone="success">Текущий сеанс</Badge>}
            </div>
          ),
        },
        {
          id: "ip",
          label: "IP адрес",
          render: (s) => (
            <span className="font-mono text-xs">{s.ip_address || "—"}</span>
          ),
        },
        {
          id: "activity",
          label: "Последняя активность",
          sortValue: (s) => s.last_activity_at,
          render: (s) => new Date(s.last_activity_at).toLocaleString("ru-RU"),
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
  );
}

export function TotpControls({ controller }: { controller: AccountViewModel }) {
  const {
    user,
    totpSetupData,
    totpLoading,
    totpSuccess,
    totpError,
    handleSetupTotp,
    handleDeleteTotp,
  } = controller;
  return (
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
        <TotpEnrollment controller={controller} />
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
  );
}

export function TotpEnrollment({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const {
    totpSetupData,
    setTotpSetupData,
    totpCode,
    setTotpCode,
    totpLoading,
    totpCopyMessage,
    handleCopyTotpSecret,
    handleConfirmTotp,
  } = controller;
  if (!totpSetupData) return null;
  return (
    <form
      onSubmit={handleConfirmTotp}
      className="space-y-3 bg-canvas p-3 rounded-lg border"
    >
      <div className="text-xs text-primary">
        Отсканируйте QR-код приложением-аутентификатором:
      </div>
      <TotpQrCode controller={controller} />
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
        <Button type="button" onClick={() => setTotpSetupData(null)}>
          Отмена
        </Button>
      </div>
    </form>
  );
}

export function TotpQrCode({ controller }: { controller: AccountViewModel }) {
  const { totpSetupData } = controller;
  if (!totpSetupData) return null;
  return (
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
  );
}

export function PasskeyControls({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const {
    passkeyName,
    setPasskeyName,
    passkeyLoading,
    passkeySuccess,
    passkeyError,
    handleRegisterPasskey,
  } = controller;
  return (
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
          {passkeyLoading ? "Регистрация..." : "Зарегистрировать Passkey"}
        </Button>
      </div>

      <PasskeyReadState controller={controller} />
    </div>
  );
}

export function PasskeyReadState({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const { passkeys, passkeysReadState, fetchPasskeys } = controller;
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-primary">
        Зарегистрированные ключи:
      </div>
      {passkeysReadState === "idle" || passkeysReadState === "loading" ? (
        <Skeleton label="Загрузка ключей доступа" rows={2} />
      ) : passkeysReadState === "error" ? (
        <div className="space-y-3">
          <Alert>Не удалось загрузить ключи доступа.</Alert>
          <Button type="button" onClick={() => void fetchPasskeys()}>
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
        <PasskeyList controller={controller} />
      )}
    </div>
  );
}

export function PasskeyList({ controller }: { controller: AccountViewModel }) {
  const { passkeys, passkeyLoading, handleDeletePasskey } = controller;
  return (
    <div className="divide-y divide-line" data-testid="passkeys-list">
      {passkeys.map((p) => (
        <div
          key={p.id}
          className="py-1.5 flex flex-wrap gap-3 justify-between items-center text-xs"
          data-testid={`passkey-row-${p.id}`}
        >
          <div>
            <span className="font-medium text-primary">{p.name}</span>
            <span className="text-tertiary ml-2">Ключ доступа</span>
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
  );
}

export function RecoveryControls({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const {
    user,
    recoveryCodes,
    recoveryLoading,
    recoverySuccess,
    recoveryError,
    handleGenerateRecoveryCodes,
  } = controller;
  return (
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
          Резервные коды требуют предварительной активации TOTP аутентификатора.
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
            {recoveryLoading ? "Генерация..." : "Сгенерировать новые коды"}
          </Button>
          {recoveryCodes && <RecoveryCodeDisplay controller={controller} />}
        </div>
      )}
    </div>
  );
}

export function RecoveryCodeDisplay({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const { recoveryCodes } = controller;
  if (!recoveryCodes) return null;
  return (
    <div
      className="bg-warning-soft p-3 rounded-lg border border-warning space-y-2 mt-2"
      data-sentry-block
      data-sso-sensitive="true"
      data-testid="recovery-codes-display"
    >
      <div className="text-xs font-semibold text-warning">
        Сохраните эти коды сейчас. Они отображаются только один раз:
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
  );
}

export function EmailVerificationControls({
  controller,
}: {
  controller: AccountViewModel;
}) {
  const {
    user,
    emailToken,
    setEmailToken,
    emailLoading,
    emailSuccess,
    emailError,
    handleRequestEmailVerification,
    handleConfirmEmailVerification,
  } = controller;
  return (
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
          ✓ Ваш адрес электронной почты ({user.email}) успешно подтверждён.
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
            {emailLoading ? "Отправка..." : "Отправить письмо с подтверждением"}
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
  );
}

export function AccountPrivacy() {
  return (
    <section
      className="mt-6 bg-surface border border-line rounded-xl p-6"
      aria-labelledby="privacy-account-title"
    >
      <h2 id="privacy-account-title" className="text-xl font-bold">
        Управление данными
      </h2>
      <p>Удаление через 14 дней с возможностью отмены до назначенного срока.</p>
      <a href="/account-deletion" className="underline text-danger">
        Удаление аккаунта
      </a>
      <p className="mt-4 text-secondary">
        Необязательная аналитика и запись сеанса включаются только с вашего
        согласия. Выбор можно изменить в панели «Cookie и аналитика».
      </p>
    </section>
  );
}

type SecurityFeatureProps = {
  enabled: boolean;
  label?: string;
  warning?: boolean;
  testId: string;
  title: string;
  description: string;
  disabledText: string;
  children: ReactNode;
};

function SecurityFeature(feature: SecurityFeatureProps) {
  return (
    <div className="security-item space-y-4" data-testid={feature.testId}>
      <div className="flex flex-wrap gap-3 justify-between items-center">
        <h3 className="font-semibold text-primary">{feature.title}</h3>
        <FeatureStatus
          enabled={feature.enabled}
          label={feature.label}
          warning={feature.warning}
        />
      </div>
      <p className="text-xs text-secondary">{feature.description}</p>
      {feature.enabled ? (
        feature.children
      ) : (
        <div className="text-xs text-tertiary italic">
          {feature.disabledText}
        </div>
      )}
    </div>
  );
}

function securityFeatures(
  controller: AccountViewModel,
): SecurityFeatureProps[] {
  const { capabilities, user } = controller;
  return [
    {
      enabled: Boolean(capabilities?.totp_enabled),
      label: user.has_totp ? "Активен" : "Доступно",
      testId: "totp-section",
      title: "Приложение-аутентификатор (TOTP)",
      description:
        "Подтверждайте вход шестизначным кодом из приложения-аутентификатора.",
      disabledText: "Администратор пока не включил этот способ защиты.",
      children: <TotpControls controller={controller} />,
    },
    {
      enabled: Boolean(capabilities?.passkey_enabled),
      testId: "passkeys-section",
      title: "Ключи доступа (Passkey)",
      description:
        "Вход без пароля с использованием биометрии или аппаратного ключа на вашем устройстве.",
      disabledText: "Администратор пока не включил ключи доступа.",
      children: <PasskeyControls controller={controller} />,
    },
    {
      enabled: Boolean(capabilities?.recovery_codes_enabled),
      testId: "recovery-codes-section",
      title: "Резервные коды восстановления",
      description:
        "Одноразовые резервные коды для восстановления доступа при утрате второго фактора.",
      disabledText: "Администратор пока не включил резервные коды.",
      children: <RecoveryControls controller={controller} />,
    },
    {
      enabled: Boolean(capabilities?.email_verification_enabled),
      label: user.email_verified ? "Подтверждён" : "Не подтверждён",
      warning: !user.email_verified,
      testId: "email-verification-section",
      title: "Подтверждение адреса почты",
      description:
        "Отправка шестизначного кода и одноразовой ссылки на адрес электронной почты.",
      disabledText: "Не удалось загрузить доступность подтверждения почты.",
      children: <EmailVerificationControls controller={controller} />,
    },
  ];
}
