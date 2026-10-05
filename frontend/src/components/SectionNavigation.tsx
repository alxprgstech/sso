import { useState, type ReactNode } from "react";
import { NavLink } from "react-router";
import {
  Menu,
  X,
  LayoutDashboard,
  Users,
  AppWindow,
  Monitor,
  ScrollText,
  Settings,
  User,
  ShieldCheck,
  LockKeyhole,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { Dialog } from "./ui/Dialog";
import { Button } from "./ui/controls";
const adminItems = [
  { path: "/admin", name: "Обзор", icon: LayoutDashboard },
  { path: "/admin/users", name: "Пользователи", icon: Users },
  { path: "/admin/applications", name: "Приложения", icon: AppWindow },
  { path: "/admin/sessions", name: "Сессии", icon: Monitor },
  { path: "/admin/audit", name: "Журнал аудита", icon: ScrollText },
  { path: "/admin/system", name: "Конфигурация", icon: Settings },
];
const accountItems = [
  { path: "/", name: "Профиль", icon: User },
  { path: "/account/security", name: "Безопасность", icon: ShieldCheck },
  { path: "/account/sessions", name: "Сессии", icon: Monitor },
  { path: "/account/privacy", name: "Конфиденциальность", icon: LockKeyhole },
];
export function SectionNavigation({
  mode,
  children,
}: {
  mode: "admin" | "account";
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  const items = mode === "admin" ? adminItems : accountItems;
  const nav = (
    <nav
      aria-label={
        mode === "admin"
          ? "Разделы администрирования"
          : "Разделы учётной записи"
      }
      className="section-links"
    >
      {items.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          end
          onClick={() => setOpen(false)}
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <motion.span
                  layoutId={`selected-${mode}`}
                  className="nav-selected"
                  transition={{ duration: reduced ? 0 : 0.18 }}
                />
              )}
              <item.icon size={18} aria-hidden="true" />
              <span>{item.name}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
  return (
    <div className={`application-layout ${mode}-layout`}>
      <aside className="desktop-sidebar">
        <p className="px-3 pb-4 text-xs text-secondary">
          {mode === "admin" ? "УПРАВЛЕНИЕ SSO" : "УЧЁТНАЯ ЗАПИСЬ"}
        </p>
        {nav}
      </aside>
      <div className="application-content min-w-0">
        <div className="mobile-section-nav">
          <Button onClick={() => setOpen(true)}>
            <Menu size={18} aria-hidden="true" />
            Разделы
          </Button>
        </div>
        {children}
      </div>
      {open && (
        <Dialog label="Разделы" onClose={() => setOpen(false)}>
          <div className="flex justify-between items-center mb-4">
            <h2>Разделы</h2>
            <Button onClick={() => setOpen(false)} aria-label="Закрыть разделы">
              <X size={18} />
            </Button>
          </div>
          {nav}
        </Dialog>
      )}
    </div>
  );
}
