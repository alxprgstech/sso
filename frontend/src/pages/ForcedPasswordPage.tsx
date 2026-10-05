import { Alert, Button, Field, PasswordInput } from "../components/ui/controls";
import { AuthSurface } from "../components/AuthSurface";
import { useNavigate } from "react-router";
import { FormEvent, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";

export function ForcedPasswordPage() {
  const navigate = useNavigate();
  const { refreshUser, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (next !== confirmation) {
      setError("Новые пароли не совпадают");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirmation("");
      await refreshUser();
      navigate("/login", { replace: true });
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Не удалось сменить пароль",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthSurface
      step="password-change"
      title="Смените временный пароль"
      description="До смены пароля доступ к приложениям и настройкам ограничен. После смены потребуется новый вход."
    >
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field id="temporary-password" label="Временный пароль">
          <PasswordInput
            id="temporary-password"
            required
            autoComplete="current-password"
            maxLength={128}
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            disabled={busy}
          />
        </Field>
        <Field
          id="replacement-password"
          label="Новый пароль"
          description="От 15 до 128 символов"
        >
          <PasswordInput
            id="replacement-password"
            required
            autoComplete="new-password"
            minLength={15}
            maxLength={128}
            aria-describedby="replacement-password-description"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            disabled={busy}
          />
        </Field>
        <Field id="replacement-confirmation" label="Повторите новый пароль">
          <PasswordInput
            id="replacement-confirmation"
            required
            autoComplete="new-password"
            minLength={15}
            maxLength={128}
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            disabled={busy}
          />
        </Field>
        {error && <Alert>{error}</Alert>}
        <Button
          type="submit"
          loading={busy}
          variant="primary"
          className="w-full"
        >
          Сменить пароль
        </Button>
        <Button
          disabled={busy}
          onClick={() => {
            void logout().catch((caught) =>
              setError(
                caught instanceof Error ? caught.message : "Не удалось выйти",
              ),
            );
          }}
          className="w-full"
        >
          Выйти
        </Button>
      </form>
    </AuthSurface>
  );
}
