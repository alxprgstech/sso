import React, { useState } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Navbar } from "./components/Navbar";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { DashboardPage } from "./pages/DashboardPage";
import { AdminPage } from "./pages/AdminPage";
import { VerifyEmailPage } from "./pages/VerifyEmailPage";

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
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
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
          }}
        />
      );
    }
    return (
      <LoginPage
        onNavigateToRegister={() => {
          window.history.pushState({}, "", "/register");
          setAuthView("register");
        }}
      />
    );
  }

  const isAdmin = user.is_superuser || user.roles.includes("admin");

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar currentPage={currentPage} setCurrentPage={setCurrentPage} />
      <main className="flex-1">
        {currentPage === "admin" && isAdmin ? (
          <AdminPage />
        ) : (
          <DashboardPage />
        )}
      </main>
      <footer className="border-t border-gray-200 bg-white py-4 text-center text-xs text-gray-500">
        ALXPRGS SSO &copy; 2026. Закрытая система единого входа для инфраструктуры alxprgs.tech.
      </footer>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <MainContent />
    </AuthProvider>
  );
};

export default App;
