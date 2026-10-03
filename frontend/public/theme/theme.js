/* Shared by the SSO frontend and both demo clients; runs before first paint. */
(function () {
  if (window.alxprgsTheme) return;
  const key = "alxprgs.ui.theme.v1";
  const valid = value => ["system", "light", "dark"].includes(value);
  const read = () => {
    try { const value = localStorage.getItem(key); return valid(value) ? value : "system"; }
    catch { return "system"; }
  };
  let preference = read();
  const media = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const apply = () => {
    const resolved = preference === "system" ? (media?.matches ? "dark" : "light") : preference;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themePreference = preference;
    document.querySelectorAll("[data-theme-control]").forEach(control => { control.value = preference; });
    window.dispatchEvent(new Event("alxprgs-theme-change"));
  };
  window.alxprgsTheme = {
    getPreference: () => preference,
    setPreference: value => {
      if (!valid(value)) return;
      preference = value;
      try { localStorage.setItem(key, value); } catch { /* Keep the choice in memory. */ }
      apply();
    },
  };
  media?.addEventListener("change", () => { if (preference === "system") apply(); });
  window.addEventListener("storage", event => {
    if (event.key === key || event.key === null) { preference = read(); apply(); }
  });
  document.addEventListener("change", event => {
    if (event.target instanceof HTMLSelectElement && event.target.hasAttribute("data-theme-control")) {
      window.alxprgsTheme.setPreference(event.target.value);
    }
  });
  document.addEventListener("DOMContentLoaded", apply, { once: true });
  apply();
})();
