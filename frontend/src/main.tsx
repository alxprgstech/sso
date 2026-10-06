import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { watchTelemetryConsent } from "./telemetry/sentry";
import { AppShell } from "./components/AppShell";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary fallback={<AppShell><div className="legal-page" role="alert"><p>Не удалось отобразить страницу.</p><button onClick={() => window.location.reload()}>Перезагрузить</button></div></AppShell>}>
    <App />
    </ErrorBoundary>
  </React.StrictMode>
);
watchTelemetryConsent();
