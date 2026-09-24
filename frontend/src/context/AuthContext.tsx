import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "../api/client";
import { Capabilities, LoginResponse, UserProfile } from "../types/api";

interface AuthContextType {
  user: UserProfile | null;
  capabilities: Capabilities | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<LoginResponse>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  refreshCapabilities: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const refreshCapabilities = async () => {
    try {
      const caps = await api.getCapabilities();
      setCapabilities(caps);
    } catch (err) {
      console.error("Не удалось получить возможности сервера:", err);
    }
  };

  const refreshUser = async () => {
    try {
      const me = await api.getMe();
      setUser(me);
    } catch {
      setUser(null);
    }
  };

  useEffect(() => {
    const init = async () => {
      setIsLoading(true);
      await refreshCapabilities();
      await refreshUser();
      setIsLoading(false);
    };

    init();
  }, []);

  const login = async (username: string, password: string): Promise<LoginResponse> => {
    const res = await api.login(username, password);
    if ("user" in res) {
      setUser(res.user);
    }
    return res;
  };

  const logout = async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      await refreshCapabilities();
    }
  };

  return (
    <AuthContext.Provider value={{ user, capabilities, isLoading, login, logout, refreshUser, refreshCapabilities }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth должен использоваться внутри AuthProvider");
  }
  return context;
};
