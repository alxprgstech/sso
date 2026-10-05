import { useEffect, useState } from "react";

export type ThemePreference = "system" | "light" | "dark";
declare global {
  interface Window {
    alxprgsTheme?: {
      getPreference: () => ThemePreference;
      setPreference: (value: ThemePreference) => void;
    };
  }
}

export function ThemeControl() {
  const [preference, setPreference] = useState<ThemePreference>(
    () => window.alxprgsTheme?.getPreference() ?? "system",
  );
  useEffect(() => {
    const changed = () =>
      setPreference(window.alxprgsTheme?.getPreference() ?? "system");
    window.addEventListener("alxprgs-theme-change", changed);
    return () => window.removeEventListener("alxprgs-theme-change", changed);
  }, []);
  return (
    <label className="theme-control">
      Тема оформления
      <select
        aria-label="Тема оформления"
        disabled={!window.alxprgsTheme}
        value={preference}
        onChange={(event) =>
          window.alxprgsTheme?.setPreference(
            event.target.value as ThemePreference,
          )
        }
      >
        <option value="system">Как в системе</option>
        <option value="light">Светлая</option>
        <option value="dark">Тёмная</option>
      </select>
    </label>
  );
}
