import {
  Alert,
  Button,
  Field,
  Input,
  PasswordInput,
  Select,
} from "./ui/controls";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, SecurityAuthorization } from "../api/client";
import {
  prepareRequestOptions,
  serializeRequestResponse,
} from "../utils/webauthn";
import { preferredFactor } from "../utils/security";
import { DeferredDialog as AccessibleDialog } from "./DeferredDialog";

interface Entry {
  action: string;
  digest: string;
  resolve: (authorization: SecurityAuthorization) => void;
  reject: (error: Error) => void;
}

const CANCELLED = "Операция отменена";

export function ReauthenticationDialog() {
  const [pending, setPending] = useState<Entry | null>(null);
  const [queuedCount, setQueuedCount] = useState(0);
  const current = useRef<Entry | null>(null);
  const queue = useRef<Entry[]>([]);
  const [proof, setProof] = useState<SecurityAuthorization | null>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [method, setMethod] = useState("totp");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retryAfter, setRetryAfter] = useState(0);

  const resetInputs = useCallback(() => {
    setProof(null);
    setPassword("");
    setCode("");
    setError("");
    setRetryAfter(0);
  }, []);

  const activate = useCallback(
    (entry: Entry) => {
      current.current = entry;
      setPending(entry);
      setQueuedCount(queue.current.length);
      resetInputs();
    },
    [resetInputs],
  );

  const finish = useCallback(
    (authorization?: SecurityAuthorization) => {
      const entry = current.current;
      current.current = null;
      if (entry) {
        if (authorization) entry.resolve(authorization);
        else entry.reject(new Error(CANCELLED));
      }
      const next = queue.current.shift();
      if (next) {
        activate(next);
      } else {
        setPending(null);
        setQueuedCount(0);
        resetInputs();
      }
    },
    [activate, resetInputs],
  );

  const cancelAll = useCallback(() => {
    const entry = current.current;
    current.current = null;
    entry?.reject(new Error(CANCELLED));
    for (const queued of queue.current) queued.reject(new Error(CANCELLED));
    queue.current = [];
    setPending(null);
    setQueuedCount(0);
    resetInputs();
  }, [resetInputs]);

  useEffect(() => {
    api.setReauthenticationHandler((action, digest) => {
      // The API client coalesces identical concurrent reads; distinct actions
      // are queued here so a second sensitive request never fails just because
      // the first dialog is still open.
      return new Promise<SecurityAuthorization>((resolve, reject) => {
        const entry = { action, digest, resolve, reject };
        if (current.current) {
          queue.current.push(entry);
          setQueuedCount(queue.current.length);
        } else {
          activate(entry);
        }
      });
    });
    return () => {
      api.setReauthenticationHandler(null);
      const entry = current.current;
      current.current = null;
      entry?.reject(new Error("Подтверждение отменено"));
      for (const queued of queue.current) queued.reject(new Error("Подтверждение отменено"));
      queue.current = [];
    };
  }, [activate]);

  useEffect(() => {
    if (retryAfter <= 0) return;
    const timer = window.setInterval(() => {
      setRetryAfter((value) => (value <= 1 ? 0 : value - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [retryAfter]);

  async function confirmFactor(authorization: SecurityAuthorization) {
    if (method !== "passkey") {
      return api.confirmReauthentication(
        authorization.authorization,
        method,
        code,
      );
    }
    if (!authorization.passkey_options)
      throw new Error("Нет запроса подтверждения Passkey");
    const assertion = await navigator.credentials.get(
      prepareRequestOptions(authorization.passkey_options),
    );
    if (!assertion) throw new Error("Passkey не подтвердил запрос");
    return api.confirmReauthentication(
      authorization.authorization,
      method,
      undefined,
      serializeRequestResponse(assertion),
    );
  }

  async function requestAuthorization(operation: Entry) {
    if (proof) return confirmFactor(proof);
    const result = await api.startReauthentication(
      operation.action,
      operation.digest,
      password,
    );
    setPassword("");
    return result;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!pending) return;
    setBusy(true);
    setError("");
    try {
      const result = await requestAuthorization(pending);
      if (!result.factor_required) finish(result);
      else {
        setProof(result);
        setMethod(preferredFactor(result.methods));
      }
    } catch (caught) {
      if (caught instanceof ApiError) {
        if (caught.code === "reauthentication_required") {
          // The five-minute authorization expired or was invalidated: the
          // password step has to be repeated, the code alone cannot retry.
          setProof(null);
          setPassword("");
        }
        if (caught.code === "totp_code_reused") {
          setRetryAfter(caught.retryAfter ?? 0);
        }
      }
      setError(
        caught instanceof Error ? caught.message : "Подтверждение не удалось",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!pending) return null;
  const sessionRead = pending.action === "GET /api/v1/auth/sessions";
  return (
    <div className="contents">
      <AccessibleDialog
        label="Подтверждение чувствительной операции"
        busy={busy}
        onClose={cancelAll}
        className="max-w-md"
      >
        <h2 className="text-xl font-semibold">Подтвердите операцию</h2>
        <p className="mt-2 text-secondary">
          {sessionRead
            ? "Подтвердите текущий пароль и настроенный второй фактор. Просмотр сессий будет доступен пять минут. Каждый отзыв потребует отдельного подтверждения."
            : "Для изменения данных или настроек безопасности подтвердите текущий пароль и настроенный второй фактор."}
        </p>
        {queuedCount > 0 && (
          <p className="mt-2 text-sm text-secondary" role="status">
            После этого подтверждения потребуется ещё одно: ожидает операций —{" "}
            {queuedCount}.
          </p>
        )}
        <form onSubmit={submit} className="mt-4 space-y-4">
          {!proof ? (
            <Field id="reauth-password" label="Текущий пароль">
              <PasswordInput
                id="reauth-password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={128}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={busy}
              />
            </Field>
          ) : (
            <>
              <Field id="reauth-method" label="Второй фактор">
                <Select
                  id="reauth-method"
                  value={method}
                  onChange={(event) => setMethod(event.target.value)}
                  className="mt-1 w-full"
                >
                  {proof.methods?.map((item) => (
                    <option key={item} value={item}>
                      {item === "totp"
                        ? "Код аутентификатора"
                        : item === "recovery_code"
                          ? "Резервный код"
                          : "Passkey"}
                    </option>
                  ))}
                </Select>
              </Field>
              {method !== "passkey" && (
                <>
                  <Field id="reauth-code" label="Код подтверждения">
                    <Input
                      id="reauth-code"
                      autoComplete="one-time-code"
                      required
                      maxLength={128}
                      value={code}
                      onChange={(event) => setCode(event.target.value)}
                      disabled={busy}
                    />
                  </Field>
                  {method === "totp" && (
                    <p className="text-xs text-secondary">
                      Код одноразовый: он принимается только один раз, даже для
                      другой операции. Если этот код уже использовался, введите
                      следующий — он обновляется каждые 30 секунд. Passkey не
                      имеет этого ограничения.
                    </p>
                  )}
                </>
              )}
            </>
          )}
          {retryAfter > 0 && (
            <p className="text-sm text-warning" role="status">
              Следующий код будет принят через {retryAfter} с.
            </p>
          )}
          {error && <Alert>{error}</Alert>}
          <div className="flex justify-end gap-3">
            <Button type="button" disabled={busy} onClick={cancelAll}>
              Отмена
            </Button>
            <Button type="submit" loading={busy} variant="primary">
              {busy ? "Проверка…" : "Подтвердить"}
            </Button>
          </div>
        </form>
      </AccessibleDialog>
    </div>
  );
}
