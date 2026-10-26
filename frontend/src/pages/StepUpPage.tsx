import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { useLocation } from "react-router";
import {
  Badge,
  Button,
  Field,
  OTPInput,
  PasswordInput,
  Skeleton,
  Alert,
} from "../components/ui/controls";
import { AuthSurface } from "../components/AuthSurface";
import { api, ApiError } from "../api/client";
import type {
  StepUpDetails,
  StepUpMethod,
  StepUpPlan,
  StepUpVerifyResult,
} from "../types/api";
import { errorMessage } from "../utils/error";
import {
  prepareRequestOptions,
  serializeRequestResponse,
} from "../utils/webauthn";
import {
  CheckCircle2,
  Clock3,
  Fingerprint,
  KeyRound,
  LockKeyhole,
  ShieldCheck,
  XCircle,
} from "lucide-react";

const TOKEN_PATTERN = /^\/step-up\/([A-Za-z0-9_-]{16,128})$/;

const METHOD_LABELS: Record<StepUpMethod, string> = {
  password: "Текущий пароль",
  totp: "Код из аутентификатора",
  passkey: "Passkey",
};

type Screen = "loading" | "form" | "success" | "cancelled" | "error";

interface StepUpErrorState {
  message: string;
  code?: string;
}

function mapError(error: unknown): StepUpErrorState {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "step_up_subject_mismatch":
        return {
          message:
            "В SSO открыта другая учётная запись. Войдите под пользователем, для которого создан запрос.",
          code: error.code,
        };
      case "step_up_expired":
      case "proof_expired":
        return {
          message: "Срок действия запроса истёк. Запросите подтверждение заново.",
          code: error.code,
        };
      case "step_up_invalidated":
      case "step_up_client_policy_changed":
        return {
          message:
            "Настройки безопасности изменились. Запросите подтверждение заново.",
          code: error.code,
        };
      case "step_up_session_mismatch":
        return {
          message:
            "Подтверждение уже начато в другой сессии. Запросите его заново.",
          code: error.code,
        };
      case "step_up_factor_rejected":
        return {
          message: "Не удалось проверить выбранный фактор. Попробуйте ещё раз.",
          code: error.code,
        };
      case "step_up_factor_unavailable":
        return {
          message: "Этот способ сейчас недоступен. Выберите другой.",
          code: error.code,
        };
      case "step_up_not_enabled":
      case "feature_disabled":
        return {
          message: "Подтверждение действий для этого приложения недоступно.",
          code: error.code,
        };
      case "step_up_not_found":
        return {
          message: "Запрос не найден. Проверьте ссылку или запросите новое подтверждение.",
          code: error.code,
        };
      default:
        return { message: error.message, code: error.code };
    }
  }
  return { message: errorMessage(error, "Не удалось выполнить подтверждение") };
}

function methodsLabel(methods: string[]): string {
  return methods
    .map((method) => METHOD_LABELS[method as StepUpMethod] ?? method)
    .join(" → ");
}

function PlanChoice({
  plan,
  selected,
  disabled,
  onSelect,
}: {
  plan: StepUpPlan;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <label className={`step-up-plan ${selected ? "step-up-plan-selected" : ""}`}>
      <input
        type="radio"
        name="step-up-plan"
        value={plan.id}
        checked={selected}
        disabled={disabled}
        onChange={onSelect}
      />
      <span>
        <strong>{plan.label}</strong>
        <small>{methodsLabel(plan.methods)}</small>
      </span>
    </label>
  );
}

export function StepUpPage() {
  const location = useLocation();
  const match = TOKEN_PATTERN.exec(location.pathname);
  const token = match?.[1] ?? "";
  const [details, setDetails] = useState<StepUpDetails | null>(null);
  const [screen, setScreen] = useState<Screen>("loading");
  const [selectedPlan, setSelectedPlan] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<StepUpErrorState | null>(null);
  const [busy, setBusy] = useState(false);
  const [redirectTo, setRedirectTo] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) {
      setScreen("error");
      setError({ message: "Некорректная ссылка подтверждения." });
      return;
    }
    setScreen("loading");
    setError(null);
    try {
      const value = await api.getStepUpRequest(token);
      setDetails(value);
      setSelectedPlan(value.plan || value.plans[0]?.id || "");
      setScreen("form");
    } catch (caught: unknown) {
      setScreen("error");
      setError(mapError(caught));
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (screen !== "success" || !redirectTo) return;
    const timer = window.setTimeout(() => {
      window.location.assign(redirectTo);
    }, 1100);
    return () => window.clearTimeout(timer);
  }, [screen, redirectTo]);

  const plans = details?.plans ?? [];
  const plan = useMemo(
    () => plans.find((item) => item.id === selectedPlan) ?? null,
    [plans, selectedPlan],
  );
  const verified = details?.verified_methods ?? [];
  const remaining = plan
    ? plan.methods.filter((method) => !verified.includes(method))
    : [];

  function applyResult(result: StepUpVerifyResult) {
    if (result.completed && result.redirect_to) {
      setDetails((current) =>
        current
          ? {
              ...current,
              verified_methods: result.verified_methods,
              plan: selectedPlan,
            }
          : current,
      );
      setRedirectTo(result.redirect_to);
      setScreen("success");
      return;
    }
    setDetails((current) =>
      current
        ? {
            ...current,
            verified_methods: result.verified_methods,
            plan: selectedPlan,
          }
        : current,
    );
    setPassword("");
    setCode("");
  }

  async function verify(
    method: StepUpMethod,
    values: { password?: string; code?: string; credential?: object },
  ) {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.verifyStepUpFactor(
        token,
        plan.id,
        method,
        values,
      );
      applyResult(result);
    } catch (caught: unknown) {
      setError(mapError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function submitPassword(event: FormEvent) {
    event.preventDefault();
    if (!password) {
      setError({ message: "Введите текущий пароль." });
      return;
    }
    await verify("password", { password });
  }

  async function submitCode(event: FormEvent) {
    event.preventDefault();
    if (!code.trim()) {
      setError({ message: "Введите одноразовый код." });
      return;
    }
    await verify("totp", { code: code.trim() });
  }

  async function usePasskey() {
    if (!plan || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (!navigator.credentials) {
        throw new Error("Браузер не поддерживает Passkey");
      }
      const options = await api.getStepUpPasskeyOptions(token, plan.id);
      const assertion = await navigator.credentials.get(
        prepareRequestOptions(options),
      );
      if (!assertion) {
        throw new Error("Аутентификатор не подтвердил запрос");
      }
      setBusy(false);
      await verify("passkey", {
        credential: serializeRequestResponse(assertion),
      });
    } catch (caught: unknown) {
      setBusy(false);
      if (
        caught instanceof DOMException &&
        (caught.name === "NotAllowedError" || caught.name === "AbortError")
      ) {
        setError({ message: "Подтверждение Passkey отменено." });
      } else {
        setError(mapError(caught));
      }
    }
  }

  async function cancel() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.denyStepUpRequest(token);
      setScreen("cancelled");
    } catch (caught: unknown) {
      setError(mapError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function switchAccount() {
    try {
      await api.logout();
    } finally {
      const returnTo = encodeURIComponent(location.pathname);
      window.location.assign(`/login?return_to=${returnTo}`);
    }
  }

  if (screen === "loading") {
    return (
      <AuthSurface
        title="Подтверждение действия"
        description="Проверяем запрос доверенного приложения."
        step="step-up-loading"
      >
        <Skeleton label="Загрузка запроса подтверждения" rows={4} />
      </AuthSurface>
    );
  }

  if (screen === "success") {
    return (
      <AuthSurface
        title="Личность подтверждена"
        description="Возвращаем вас в приложение. Если переход не начался, используйте кнопку ниже."
        step="step-up-success"
      >
        <div className="step-up-outcome" role="status" aria-live="polite">
          <CheckCircle2 size={28} aria-hidden="true" />
          <p>Подтверждение принято. Оно действует только для этой операции.</p>
        </div>
        {redirectTo && (
          <Button
            variant="primary"
            className="w-full"
            onClick={() => window.location.assign(redirectTo)}
          >
            Вернуться в приложение
          </Button>
        )}
      </AuthSurface>
    );
  }

  if (screen === "cancelled") {
    return (
      <AuthSurface
        title="Действие отменено"
        description="Разрешение не выдано. Приложение не получит подтверждение."
        step="step-up-cancelled"
      >
        <div className="step-up-outcome step-up-outcome-cancelled" role="status">
          <XCircle size={28} aria-hidden="true" />
          <p>Вы можете закрыть эту страницу и вернуться в приложение.</p>
        </div>
        <Button className="w-full" onClick={() => window.location.assign("/")}>
          Перейти в SSO
        </Button>
      </AuthSurface>
    );
  }

  if (screen === "error" || !details) {
    return (
      <AuthSurface
        title="Подтверждение недоступно"
        description="Запрос не может быть выполнен."
        step="step-up-error"
      >
        {error && <Alert>{error.message}</Alert>}
        {error?.code === "step_up_subject_mismatch" && (
          <Button className="mt-4 w-full" onClick={switchAccount}>
            Войти под другим пользователем
          </Button>
        )}
      </AuthSurface>
    );
  }

  const expiresAt = new Date(details.expires_at);
  const expiresLabel = Number.isNaN(expiresAt.getTime())
    ? "ограниченное время"
    : new Intl.DateTimeFormat("ru-RU", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(expiresAt);
  const secondsLeft = Number.isNaN(expiresAt.getTime())
    ? 0
    : Math.max(0, Math.ceil((expiresAt.getTime() - Date.now()) / 1000));

  return (
    <AuthSurface
      title="Подтверждение действия"
      description="Доверенное приложение запрашивает повторное подтверждение личности."
      step="step-up-form"
    >
      <div className="step-up-summary">
        <div className="step-up-summary-heading">
          <ShieldCheck size={22} aria-hidden="true" />
          <div>
            <span className="text-xs text-secondary">Приложение</span>
            <strong>{details.client_name}</strong>
          </div>
        </div>
        <dl>
          <div>
            <dt>Операция</dt>
            <dd>{details.description}</dd>
          </div>
          <div>
            <dt>Идентификатор</dt>
            <dd>
              <code>{details.action}</code>
            </dd>
          </div>
          <div>
            <dt>Требуемый уровень</dt>
            <dd>
              <Badge tone="warning">{details.assurance_label}</Badge>
            </dd>
          </div>
          <div>
            <dt>Действует до</dt>
            <dd>
              <Clock3 size={15} aria-hidden="true" /> {expiresLabel}
            </dd>
          </div>
        </dl>
        <p className="step-up-warning">
          Подтверждайте только ту операцию, которую вы действительно
          инициировали. Изменение данных после подтверждения сделает его
          недействительным.
        </p>
      </div>

      {error && (
        <div className="mt-4" role="alert">
          <Alert>{error.message}</Alert>
        </div>
      )}

      {!details.plan && plans.length > 1 && (
        <fieldset className="step-up-plans" disabled={busy}>
          <legend>Способ подтверждения</legend>
          {plans.map((item) => (
            <PlanChoice
              key={item.id}
              plan={item}
              selected={selectedPlan === item.id}
              disabled={busy}
              onSelect={() => setSelectedPlan(item.id)}
            />
          ))}
        </fieldset>
      )}

      {plan && (
        <section className="step-up-factors" aria-label="Подтверждение личности">
          <p className="text-sm text-secondary">
            Для продолжения подтвердите свою личность:{" "}
            <strong>{methodsLabel(plan.methods)}</strong>.
          </p>

          {remaining.includes("password") && (
            <form onSubmit={submitPassword} className="space-y-3">
              <Field id="step-up-password" label="Текущий пароль">
                <PasswordInput
                  id="step-up-password"
                  autoComplete="current-password"
                  maxLength={128}
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={busy}
                />
              </Field>
              <Button type="submit" variant="primary" loading={busy}>
                Подтвердить пароль
              </Button>
            </form>
          )}

          {remaining.includes("totp") && (
            <form onSubmit={submitCode} className="space-y-3">
              <Field id="step-up-code" label="Код из приложения-аутентификатора">
                <OTPInput
                  id="step-up-code"
                  required
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  disabled={busy}
                />
              </Field>
              <Button type="submit" variant="primary" loading={busy}>
                Подтвердить код
              </Button>
            </form>
          )}

          {remaining.includes("passkey") && (
            <Button
              variant="primary"
              className="w-full"
              loading={busy}
              onClick={() => void usePasskey()}
            >
              <Fingerprint size={18} aria-hidden="true" />
              Использовать Passkey
            </Button>
          )}

          {remaining.length === 0 && (
            <p className="text-sm text-secondary" role="status">
              Все необходимые факторы подтверждены. Завершаем операцию…
            </p>
          )}
        </section>
      )}

      <div className="step-up-actions">
        <Button
          type="button"
          variant="secondary"
          className="w-full"
          disabled={busy}
          onClick={() => void cancel()}
        >
          Отменить действие
        </Button>
        <p className="text-xs text-tertiary">
          <LockKeyhole size={13} aria-hidden="true" /> Пароль и коды вводятся
          только на стороне ALXPRGS SSO и не передаются приложению.
        </p>
        <p className="text-xs text-tertiary">
          <KeyRound size={13} aria-hidden="true" /> Одноразовое подтверждение
          действует только до истечения запроса
          {secondsLeft > 0 ? ` (${secondsLeft} с)` : ""}.
        </p>
      </div>
    </AuthSurface>
  );
}
