import { Capabilities, LoginResponse, UserProfile, SessionInfo, AdminUser, AdminClient, AuditEventItem, RegisterRequest, RegisterResponse, SystemStatus } from "../types/api";

class ApiClient {
  private csrfToken: string | null = null;

  setCsrfToken(token: string | null) {
    this.csrfToken = token;
  }

  getCsrfToken(): string | null {
    return this.csrfToken;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");

    if (options.body && typeof options.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    // Добавление CSRF заголовка для мутирующих запросов
    const method = options.method?.toUpperCase() || "GET";
    if (["POST", "PUT", "DELETE", "PATCH"].includes(method) && this.csrfToken) {
      headers.set("X-CSRF-Token", this.csrfToken);
    }

    const response = await fetch(endpoint, {
      ...options,
      headers,
      credentials: "include", // Использование host-only защищенных cookies
    });

    // Обновляем CSRF токен, если сервер прислал его в заголовке
    const newCsrf = response.headers.get("X-CSRF-Token");
    if (newCsrf) {
      this.csrfToken = newCsrf;
    }

    if (!response.ok) {
      let errorMessage = `Ошибка HTTP ${response.status}`;
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail?.detail || errorData.detail || errorData.error_description || errorData.error || errorMessage;
      } catch {
        // Игнорируем ошибку парсинга JSON
      }
      throw new Error(errorMessage);
    }

    // Если 204 No Content
    if (response.status === 204) {
      return {} as T;
    }

    return response.json();
  }

  // --- Auth & Capabilities ---
  async getCapabilities(): Promise<Capabilities> {
    return this.request<Capabilities>("/api/v1/auth/capabilities");
  }

  async login(username: string, password: string): Promise<LoginResponse> {
    const res = await this.request<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    if ("csrf_token" in res) {
      this.csrfToken = res.csrf_token;
    }
    return res;
  }

  async logout(): Promise<void> {
    await this.request("/api/v1/auth/logout", { method: "POST" });
    this.csrfToken = null;
  }

  async getMe(): Promise<UserProfile> {
    return this.request<UserProfile>("/api/v1/auth/me");
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<{ status: string; message: string }> {
    return this.request("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
  }

  async getSessions(): Promise<SessionInfo[]> {
    return this.request<SessionInfo[]>("/api/v1/auth/sessions");
  }

  async revokeSession(sessionId: string): Promise<void> {
    await this.request(`/api/v1/auth/sessions/${sessionId}`, { method: "DELETE" });
  }

  async revokeOtherSessions(): Promise<{ status: string; revoked_count: number }> {
    return this.request("/api/v1/auth/sessions", { method: "DELETE" });
  }

  // --- Admin API ---
  async getAdminUsers(offset = 0, limit = 50, search?: string): Promise<AdminUser[]> {
    const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (search) query.set("search", search);
    return this.request<AdminUser[]>(`/api/v1/admin/users?${query.toString()}`);
  }

  async createAdminUser(data: { username: string; email: string; password: string; roles: string[]; is_superuser: boolean }): Promise<AdminUser> {
    return this.request<AdminUser>("/api/v1/admin/users", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updateAdminUser(userId: string, data: Partial<AdminUser> & { new_password?: string }): Promise<AdminUser> {
    return this.request<AdminUser>(`/api/v1/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async revokeUserSessions(userId: string): Promise<{ status: string; revoked_count: number }> {
    return this.request(`/api/v1/admin/users/${userId}/sessions/revoke`, { method: "POST" });
  }

  async getAdminClients(): Promise<AdminClient[]> {
    return this.request<AdminClient[]>("/api/v1/admin/clients");
  }

  async createAdminClient(data: { client_name: string; client_type: string; redirect_uris: string[] }): Promise<AdminClient> {
    return this.request<AdminClient>("/api/v1/admin/clients", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async rotateClientSecret(clientId: string): Promise<AdminClient> {
    return this.request<AdminClient>(`/api/v1/admin/clients/${clientId}/rotate-secret`, {
      method: "POST",
    });
  }

  async deleteClient(clientId: string): Promise<void> {
    await this.request(`/api/v1/admin/clients/${clientId}`, {
      method: "DELETE",
    });
  }

  async register(data: RegisterRequest): Promise<RegisterResponse> {
    return this.request<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async getSystemStatus(): Promise<SystemStatus> {
    return this.request<SystemStatus>("/api/v1/admin/system/status");
  }

  async updateRegistrationMode(mode: string, current_admin_password: string): Promise<SystemStatus> {
    return this.request<SystemStatus>("/api/v1/admin/system/registration-mode", {
      method: "POST",
      body: JSON.stringify({ mode, current_admin_password }),
    });
  }

  async getAuditEvents(offset = 0, limit = 50): Promise<AuditEventItem[]> {
    return this.request<AuditEventItem[]>(`/api/v1/admin/audit?offset=${offset}&limit=${limit}`);
  }

  // --- Passkey / WebAuthn API (G4-PASSKEY) ---
  async getPasskeyRegistrationOptions(): Promise<any> {
    return this.request<any>("/api/v1/mfa/passkey/register/options", {
      method: "POST",
    });
  }

  async verifyPasskeyRegistration(credential: any, name = "Passkey"): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>("/api/v1/mfa/passkey/register/verify", {
      method: "POST",
      body: JSON.stringify({ credential, name }),
    });
  }

  async getPasskeyCredentials(): Promise<Array<{ id: string; name: string; sign_count: number }>> {
    return this.request<Array<{ id: string; name: string; sign_count: number }>>("/api/v1/mfa/passkey/credentials");
  }

  async deletePasskeyCredential(id: string): Promise<{ status: string }> {
    return this.request<{ status: string }>(`/api/v1/mfa/passkey/credentials/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  async getPasskeyAuthOptions(): Promise<any> {
    return this.request<any>("/api/v1/mfa/passkey/auth/options", {
      method: "POST",
    });
  }

  async verifyPasskeyAuth(credential: any, mfaToken?: string): Promise<LoginResponse> {
    const res = await this.request<LoginResponse>("/api/v1/mfa/passkey/auth/verify", {
      method: "POST",
      body: JSON.stringify({ credential, mfa_token: mfaToken }),
    });
    if ("csrf_token" in res) {
      this.csrfToken = res.csrf_token;
    }
    return res;
  }
}

export const api = new ApiClient();
