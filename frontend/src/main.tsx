import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { ErrorBoundary } from "@sentry/react";
import { bootstrapTelemetry } from "./telemetry/sentry";

void bootstrapTelemetry().finally(() => ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary fallback={<div role="alert"><p>Не удалось отобразить страницу.</p><button onClick={() => window.location.reload()}>Перезагрузить</button></div>} showDialog={false}>
    <App />
    </ErrorBoundary>
  </React.StrictMode>
));
