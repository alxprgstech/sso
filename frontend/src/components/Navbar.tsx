import { useState } from "react";
import { Link, NavLink } from "react-router";
import { LogOut, Command } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { Alert, Badge, Button } from "./ui/controls";
import { Brand } from "./Brand";
export function Navbar() {
  const { user, logout } = useAuth();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function leave() {
    setBusy(true);
    setError("");
    try {
      await logout();
    } catch {
      setError("Не удалось завершить сессию. Попробуйте снова.");
    } finally {
      setBusy(false);
    }
  }
  const admin = user && (user.is_superuser || user.roles.includes("admin"));
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-3">
        <Link
          to="/"
          className="inline-flex min-h-11 font-semibold tracking-tight text-base"
          aria-label="ALXPRGS SSO — личный кабинет"
        >
          <Brand />
        </Link>
        <nav className="flex flex-wrap gap-2" aria-label="Основная навигация">
          <NavLink className="ui-button ui-ghost" to="/">
            Личный кабинет
          </NavLink>
          {admin && (
            <NavLink className="ui-button ui-ghost" to="/admin">
              Администрирование
            </NavLink>
          )}
        </nav>
        <div className="flex flex-wrap items-center gap-3">
          <span className="max-w-40 truncate text-secondary">
            {user?.username}
          </span>
          {admin && <Badge>Admin</Badge>}
          <Button
            onClick={() => window.dispatchEvent(new Event("alxprgs-command"))}
            aria-label="Открыть команды"
          >
            <Command size={16} aria-hidden="true" />
            <span className="hidden sm:inline">Команды</span>
          </Button>
          <Button loading={busy} onClick={() => void leave()}>
            <LogOut size={16} aria-hidden="true" />
            Выйти
          </Button>
        </div>
      </div>
      {error && <Alert>{error}</Alert>}
    </header>
  );
}
