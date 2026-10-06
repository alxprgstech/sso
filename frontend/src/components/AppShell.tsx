import type { ReactNode } from "react";
import { CookieBanner, LegalFooter } from "./PrivacyControls";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div data-sentry-block className="sso-sensitive app-shell">
      <a className="skip-link" href="#main-content">
        К основному содержимому
      </a>
      <div className="app-scroll">
        <main id="main-content" tabIndex={-1}>
          {children}
        </main>
        <LegalFooter />
      </div>
      <CookieBanner />
    </div>
  );
}
