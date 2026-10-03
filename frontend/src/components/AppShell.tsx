import type { ReactNode } from "react";
import { CookieBanner, LegalFooter } from "./PrivacyControls";
import { ThemeControl } from "./ThemeControl";

export function AppShell({ children }: { children: ReactNode }) {
  return <div data-sentry-block className="sso-sensitive app-shell">
    <a className="skip-link" href="#main-content">К основному содержимому</a>
    <div className="app-scroll">
      <div className="appearance-bar"><ThemeControl /></div>
      <main id="main-content" tabIndex={-1}>{children}</main>
      <LegalFooter />
    </div>
    <CookieBanner />
  </div>;
}
