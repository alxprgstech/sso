import { AuthSurface } from "../components/AuthSurface";
import {
  Alert,
  Button,
  Field,
  Input,
  OTPInput,
  PasswordInput,
  Skeleton,
} from "../components/ui/controls";
import { errorMessage } from "../utils/error";
import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import type { RegisterResponse } from "../types/api";
import { ConsentFields, useLegalDocuments } from "./LegalPage";

interface RegisterPageProps {
  onNavigateToLogin: () => void;
}

export const RegisterPage: React.FC<RegisterPageProps> = ({
  onNavigateToLogin,
}) => {
  const { capabilities } = useAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [challenge, setChallenge] = useState<RegisterResponse | null>(null);
  const [code, setCode] = useState("");
  const [verified, setVerified] = useState(false);
  const { documents, error: documentError } = useLegalDocuments();
  const [terms, setTerms] = useState(false);
  const [consent, setConsent] = useState(false);

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const isClosed = capabilities && capabilities.registration_mode !== "open";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setFieldErrors({});
    if (!documents || !terms || !consent) {
      setError(
        "Прочитайте документы и подтвердите условия и согласие на обработку данных.",
      );
      return;
    }

    // Валидация на клиенте
    if (username.trim().length < 3) {
      setFieldErrors({
        username: "Имя пользователя должно содержать не менее 3 символов.",
      });
      return;
    }

    if (password.length < 15) {
      setFieldErrors({
        password: "Длина пароля должна быть не менее 15 символов.",
      });
      return;
    }

    if (password !== confirmPassword) {
      setFieldErrors({ confirmation: "Введенные пароли не совпадают." });
      return;
    }

    setLoading(true);

    try {
      const res = await api.register({
        username: username.trim(),
        email: email.trim(),
        password,
        confirm_password: confirmPassword,
        terms_accepted: true,
        data_processing_consent: true,
        legal_versions: documents.required_versions,
      });

      setChallenge(res);
      setPassword("");
      setConfirmPassword("");
      setSuccess(
        "Письмо отправлено. Введите код из 6 цифр или откройте ссылку в письме.",
      );
    } catch (err: unknown) {
      setError(errorMessage(err, "Ошибка при регистрации учётной записи."));
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!challenge || !/^[0-9]{6}$/.test(code)) return;
    setLoading(true);
    setError(null);
    try {
      await api.confirmRegistrationCode(challenge.challenge_id, code);
      setVerified(true);
      setCode("");
      setSuccess(
        "Адрес подтверждён, учётная запись создана. Теперь можно войти.",
      );
    } catch (err: unknown) {
      setError(errorMessage(err, "Неверный или просроченный код."));
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    if (!challenge) return;
    setLoading(true);
    setError(null);
    try {
      setChallenge(await api.resendRegistration(challenge.challenge_id));
      setSuccess(
        "Новый код отправлен. Предыдущий код и ссылка больше не действуют.",
      );
      setCode("");
    } catch (err: unknown) {
      setError(errorMessage(err, "Не удалось повторно отправить письмо."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthSurface
      title={
        verified
          ? "Адрес подтверждён"
          : challenge
            ? "Проверьте вашу почту"
            : "Регистрация в ALXPRGS SSO"
      }
      description={
        challenge
          ? "Введите код из письма, чтобы завершить создание учётной записи."
          : "Создайте учётную запись для сервисов инфраструктуры."
      }
      step={verified ? "success" : challenge ? "verification" : "registration"}
    >
      {!capabilities ? (
        <Skeleton label="Проверка доступности регистрации" />
      ) : isClosed ? (
        <div className="space-y-5">
          <Alert tone="info">
            Самостоятельная регистрация закрыта. Для получения доступа
            обратитесь к администратору организации.
          </Alert>
          <Button className="w-full" onClick={onNavigateToLogin}>
            Вернуться на страницу входа
          </Button>
        </div>
      ) : (
        <>
          {(error || documentError) && (
            <div id="registration-error" className="mb-5">
              <Alert>{error || documentError}</Alert>
            </div>
          )}
          {success && (
            <div className="mb-5">
              <Alert tone="success">{success}</Alert>
            </div>
          )}
          {verified ? (
            <Button
              variant="primary"
              className="w-full"
              onClick={onNavigateToLogin}
            >
              Перейти ко входу
            </Button>
          ) : challenge ? (
            <div className="space-y-5">
              <form onSubmit={handleVerify} className="space-y-4">
                <Field id="registration-code" label="Код из письма">
                  <OTPInput
                    id="registration-code"
                    value={code}
                    onChange={(e) =>
                      setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                    }
                    required
                    disabled={loading}
                  />
                  <p className="field-description">Код действует 10 минут.</p>
                </Field>
                <Button
                  variant="primary"
                  className="w-full"
                  type="submit"
                  loading={loading}
                  disabled={code.length !== 6}
                >
                  Подтвердить адрес
                </Button>
              </form>
              <Button variant="ghost" disabled={loading} onClick={handleResend}>
                Отправить новый код
              </Button>
              <details className="text-xs text-secondary">
                <summary className="cursor-pointer py-2">
                  Сведения о запросе
                </summary>
                <dl className="space-y-2">
                  {Object.entries(challenge.request_details).map(
                    ([key, value]) => (
                      <div key={key}>
                        <dt>
                          {(
                            {
                              ip: "IP-адрес",
                              os: "Система",
                              browser: "Браузер",
                              device: "Устройство",
                              time: "Время",
                            } as Record<string, string>
                          )[key] || key}
                        </dt>
                        <dd>{value}</dd>
                      </div>
                    ),
                  )}
                </dl>
              </details>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <Field
                id="registerpage-field-1"
                label="Имя пользователя (логин)"
                description="От 3 до 64 символов: латинские буквы, цифры, _ и -."
                error={fieldErrors.username}
              >
                <Input
                  id="registerpage-field-1"
                  name="username"
                  autoComplete="username"
                  required
                  minLength={3}
                  maxLength={64}
                  pattern="[a-zA-Z0-9_-]+"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="alex_ivanov"
                  aria-invalid={Boolean(fieldErrors.username)}
                  aria-describedby={
                    fieldErrors.username
                      ? "registerpage-field-1-error"
                      : "registerpage-field-1-description"
                  }
                  disabled={loading}
                />
              </Field>
              <Field id="registerpage-field-2" label="Email адрес">
                <Input
                  id="registerpage-field-2"
                  name="email"
                  autoComplete="email"
                  type="email"
                  required
                  maxLength={255}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="alex@alxprgs.tech"
                  disabled={loading}
                />
              </Field>
              <Field
                id="registerpage-field-3"
                label="Пароль"
                description="Не менее 15 символов."
                error={fieldErrors.password}
              >
                <PasswordInput
                  id="registerpage-field-3"
                  name="password"
                  autoComplete="new-password"
                  required
                  minLength={15}
                  maxLength={128}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={loading}
                  aria-invalid={Boolean(fieldErrors.password)}
                  aria-describedby={
                    fieldErrors.password
                      ? "registerpage-field-3-error"
                      : "registerpage-field-3-description"
                  }
                />
              </Field>
              <Field
                id="registerpage-field-4"
                label="Подтверждение пароля"
                error={fieldErrors.confirmation}
              >
                <PasswordInput
                  id="registerpage-field-4"
                  name="password_confirmation"
                  autoComplete="new-password"
                  required
                  minLength={15}
                  maxLength={128}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={loading}
                  aria-invalid={Boolean(fieldErrors.confirmation)}
                  aria-describedby={
                    fieldErrors.confirmation
                      ? "registerpage-field-4-error"
                      : undefined
                  }
                />
              </Field>
              <ConsentFields
                terms={terms}
                consent={consent}
                onTerms={setTerms}
                onConsent={setConsent}
              />
              <Button
                type="submit"
                variant="primary"
                className="w-full"
                loading={loading}
                disabled={Boolean(success) || !documents || !terms || !consent}
              >
                Зарегистрироваться
              </Button>
            </form>
          )}
          <p className="mt-6 text-secondary">
            Уже есть учётная запись?{" "}
            <Button variant="ghost" onClick={onNavigateToLogin}>
              Войти
            </Button>
          </p>
        </>
      )}
    </AuthSurface>
  );
};
