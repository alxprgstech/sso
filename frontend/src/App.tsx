import React, { useState } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Navbar } from "./components/Navbar";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { DashboardPage } from "./pages/DashboardPage";
import { AdminPage } from "./pages/AdminPage";
import { VerifyEmailPage } from "./pages/VerifyEmailPage";
import { navigationBreadcrumb } from "./telemetry/sentry";
import { AppShell } from "./components/AppShell";
import { AcceptancePage, LegalPage } from "./pages/LegalPage";
import { AccountDeletionPage } from "./pages/AccountDeletionPage";

const MainContent: React.FC = () => {
  const { user, isLoading } = useAuth();
  const [currentPage, setCurrentPage] = useState<"dashboard" | "admin" | "login">("dashboard");
  const [authView, setAuthView] = useState<"login" | "register">(
    window.location.pathname === "/register" ? "register" : "login"
  );

  if (window.location.pathname === "/verify-email") {
    return <VerifyEmailPage />;
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-50 py-12">
        <div className="text-gray-500 text-sm font-medium">Загрузка данных сессии...</div>
      </div>
    );
  }

  if (!user) {
    if (authView === "register") {
      return (
        <RegisterPage
          onNavigateToLogin={() => {
            window.history.pushState({}, "", "/login");
            setAuthView("login");
            navigationBreadcrumb("login");
          }}
        />
      );
    }
    return (
      <LoginPage
        onNavigateToRegister={() => {
          window.history.pushState({}, "", "/register");
          setAuthView("register");
          navigationBreadcrumb("register");
        }}
      />
    );
  }

  const isAdmin = user.is_superuser || user.roles.includes("admin");

  if (user.deletion_pending || user.session_purpose === "deletion_management" || window.location.pathname === "/account-deletion") return <AccountDeletionPage />;
  if (user.legal_acceptance_required !== false) return <AcceptancePage />;

  return (
    <div className="flex-1 bg-gray-50 flex flex-col">
      <Navbar currentPage={currentPage} setCurrentPage={page => { navigationBreadcrumb(page); setCurrentPage(page); }} />
      <div className="flex-1">
        {currentPage === "admin" && isAdmin ? (
          <AdminPage />
        ) : (
          <DashboardPage />
        )}
      </div>
      <a href="/account-deletion" className="deletion-link">Удаление аккаунта</a>
    </div>
  );
};

export const App: React.FC = () => {
  const publicDocument = ["/privacy", "/terms", "/cookies", "/data-consent"].includes(window.location.pathname);
  if (publicDocument) return <AppShell><LegalPage path={window.location.pathname} /></AppShell>;
  return (
    <AuthProvider>
      <AppShell><MainContent /></AppShell>
    </AuthProvider>
  );
};

export default App;
