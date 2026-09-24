import React, { useState } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Navbar } from "./components/Navbar";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { AdminPage } from "./pages/AdminPage";

const MainContent: React.FC = () => {
  const { user, isLoading } = useAuth();
  const [currentPage, setCurrentPage] = useState<"dashboard" | "admin" | "login">("dashboard");

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-gray-500 text-sm font-medium">Загрузка данных сессии...</div>
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
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
