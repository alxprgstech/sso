import React from "react";
import { useAuth } from "../context/AuthContext";

interface NavbarProps {
  currentPage: "dashboard" | "admin" | "login";
  setCurrentPage: (page: "dashboard" | "admin" | "login") => void;
}

export const Navbar: React.FC<NavbarProps> = ({ currentPage, setCurrentPage }) => {
  const { user, logout } = useAuth();

  const isAdmin = user && (user.is_superuser || user.roles.includes("admin"));

  return (
    <header className="bg-white border-b border-gray-200 shadow-sm sticky top-0 z-10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3 cursor-pointer" onClick={() => setCurrentPage(user ? "dashboard" : "login")}>
          <div className="w-9 h-9 bg-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-lg shadow-sm">
            A
          </div>
          <div>
            <span className="text-xl font-bold tracking-tight text-gray-900">ALXPRGS</span>
            <span className="text-xl font-medium text-blue-600 ml-1">SSO</span>
          </div>
        </div>

        {user ? (
          <div className="flex items-center space-x-4">
            <nav className="flex space-x-2">
              <button
                onClick={() => setCurrentPage("dashboard")}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  currentPage === "dashboard"
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                }`}
              >
                Личный кабинет
              </button>
              {isAdmin && (
                <button
                  onClick={() => setCurrentPage("admin")}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    currentPage === "admin"
                      ? "bg-blue-50 text-blue-700"
                      : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                  }`}
                >
                  Администрирование
                </button>
              )}
            </nav>

            <div className="h-5 w-px bg-gray-200" />

            <div className="flex items-center space-x-3">
              <div className="text-right">
                <div className="text-sm font-semibold text-gray-900 leading-none">{user.username}</div>
                <div className="text-xs text-gray-500 mt-0.5">{user.email}</div>
              </div>
              {isAdmin && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">
                  Admin
                </span>
              )}
              <button
                onClick={logout}
                className="text-sm text-red-600 hover:text-red-700 hover:bg-red-50 px-2.5 py-1.5 rounded-md font-medium transition-colors"
              >
                Выйти
              </button>
            </div>
          </div>
        ) : (
          <div className="text-sm text-gray-500 font-medium">
            auth.alxprgs.tech
          </div>
        )}
      </div>
    </header>
  );
};
