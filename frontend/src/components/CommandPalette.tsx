import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { Command } from "cmdk";
import { Search } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { Dialog } from "./ui/Dialog";
function isCommandShortcut(event: KeyboardEvent) {
  return (
    event.key.toLowerCase() === "k" &&
    (event.ctrlKey || event.metaKey) &&
    !event.altKey
  );
}

function useCommandShortcut() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const show = () => setOpen((value) => !value);
    const key = (event: KeyboardEvent) => {
      if (!isCommandShortcut(event)) return;
      if (document.querySelector('[role="dialog"]')) return;
      event.preventDefault();
      show();
    };
    document.addEventListener("keydown", key);
    window.addEventListener("alxprgs-command", show);
    return () => {
      document.removeEventListener("keydown", key);
      window.removeEventListener("alxprgs-command", show);
    };
  }, []);
  return { open, setOpen };
}

export function CommandPalette() {
  const { open, setOpen } = useCommandShortcut();
  const navigate = useNavigate();
  const { user } = useAuth();
  const items = [
    { name: "Учётная запись", path: "/" },
    { name: "Безопасность", path: "/account/security" },
    { name: "Сессии", path: "/account/sessions" },
    { name: "Конфиденциальность", path: "/account/privacy" },
  ];
  if (user?.is_superuser || user?.roles.includes("admin"))
    items.push(
      { name: "Обзор системы", path: "/admin" },
      { name: "Пользователи", path: "/admin/users" },
      { name: "Приложения", path: "/admin/applications" },
      { name: "Управление сессиями", path: "/admin/sessions" },
      { name: "Журнал аудита", path: "/admin/audit" },
      { name: "Конфигурация", path: "/admin/system" },
    );
  function run(action: () => void) {
    setOpen(false);
    action();
  }
  return open ? (
    <Dialog label="Команды ALXPRGS" onClose={() => setOpen(false)}>
      <Command label="Поиск команды">
        <div className="flex items-center gap-3 border-b border-line pb-4">
          <Search size={18} aria-hidden="true" />
          <Command.Input
            className="w-full bg-transparent"
            aria-label="Поиск команды"
            placeholder="Найти страницу или сменить тему…"
          />
        </div>
        <Command.List className="command-list" label="Команды">
          <Command.Empty className="empty-state">
            Команды не найдены
          </Command.Empty>
          <Command.Group heading="Навигация">
            {items.map((item) => (
              <Command.Item
                key={item.path}
                onSelect={() => run(() => navigate(item.path))}
              >
                {item.name}
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Оформление">
            {(["dark", "light", "system"] as const).map((theme, i) => (
              <Command.Item
                key={theme}
                onSelect={() =>
                  run(() => window.alxprgsTheme?.setPreference(theme))
                }
              >
                {["Тёмная тема", "Светлая тема", "Тема системы"][i]}
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>
        <p className="mt-4 text-xs text-secondary">
          ↑ ↓ Выбор · Enter Открыть · Esc Закрыть
        </p>
      </Command>
    </Dialog>
  ) : null;
}
