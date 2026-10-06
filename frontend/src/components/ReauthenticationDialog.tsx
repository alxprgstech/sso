import {
  Alert,
  Button,
  Field,
  Input,
  PasswordInput,
  Select,
} from "./ui/controls";
import { FormEvent, useEffect, useRef, useState } from "react";
import { api, SecurityAuthorization } from "../api/client";
import {
  prepareRequestOptions,
  serializeRequestResponse,
} from "../utils/webauthn";
import { DeferredDialog as AccessibleDialog } from "./DeferredDialog";

interface Pending {
  action: string;
  digest: string;
  resolve: (authorization: string) => void;
  reject: (error: Error) => void;
}

export function ReauthenticationDialog() {
  const [pending, setPending] = useState<Pending | null>(null);
  const current = useRef<Pending | null>(null);
  const [proof, setProof] = useState<SecurityAuthorization | null>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [method, setMethod] = useState("totp");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.setReauthenticationHandler(
      (action, digest) =>
        new Promise((resolve, reject) => {
          if (current.current) {
            reject(new Error("Дождитесь завершения текущего подтверждения"));
            return;
          }
          const value = { action, digest, resolve, reject };
          current.current = value;
          setProof(null);
          setPassword("");
          setCode("");
          setError("");
          setPending(value);
        }),
    );
    return () => {
      api.setReauthenticationHandler(null);
      current.current?.reject(new Error("Подтверждение отменено"));
      current.current = null;
    };
  }, []);

  function finish(authorization?: string) {
    if (authorization) current.current?.resolve(authorization);
    else current.current?.reject(new Error("Операция отменена"));
    current.current = null;
    setPending(null);
    setPassword("");
    setCode("");
    setProof(null);
  }

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

  async function requestAuthorization(operation: Pending) {
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
      if (!result.factor_required) finish(result.authorization);
      else {
        setProof(result);
        setMethod(result.methods?.[0] || "totp");
      }
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Подтверждение не удалось",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!pending) return null;
  return (
    <div className="contents">
      <AccessibleDialog
        label="Подтверждение чувствительной операции"
        busy={busy}
        onClose={() => finish()}
        className="max-w-md"
      >
        <h2 className="text-xl font-semibold">Подтвердите операцию</h2>
        <p className="mt-2 text-secondary">
          Для изменения данных или настроек безопасности подтвердите текущий
          доступ.
        </p>
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
              )}
            </>
          )}
          {error && <Alert>{error}</Alert>}
          <div className="flex justify-end gap-3">
            <Button type="button" disabled={busy} onClick={() => finish()}>
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
