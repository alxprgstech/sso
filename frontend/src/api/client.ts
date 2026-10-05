import {
  Capabilities,
  LoginResponse,
  UserProfile,
  SessionInfo,
  AdminUser,
  AdminClient,
  AuditEventItem,
  RegisterRequest,
  RegisterResponse,
  RegistrationCompleteResponse,
  SystemStatus,
  TOTPSetupResponse,
  RecoveryCodesResponse,
} from "../types/api";
import type { EncodedCreationOptions, EncodedRequestOptions } from "../utils/webauthn";
import { captureContractFailure } from "../telemetry/sentry";
import { canonicalRoute } from "../telemetry/privacy";
import { requestDigest } from "../utils/reauthentication";

export interface SecurityAuthorization {
  authorization: string;
  factor_required: boolean;
  methods?: string[];
  passkey_options?: EncodedRequestOptions | null;
}

export class ApiError extends Error {
  readonly name = "ApiError";
  constructor(message: string, readonly status: number, readonly code: string, readonly route: string) {
    super(message);
  }
}

class ApiClient {
  private csrfToken: string | null = null;
  private reauthenticationHandler: ((action: string, digest: string) => Promise<string>) | null = null;

  setReauthenticationHandler(handler: ((action: string, digest: string) => Promise<string>) | null) {
    this.reauthenticationHandler = handler;
  }

  async startReauthentication(action: string, payload_hash: string, current_password: string): Promise<SecurityAuthorization> {
    return this.request("/api/v1/auth/reauthentication", { method: "POST", body: JSON.stringify({ action, payload_hash, current_password }) }, false);
  }

  async confirmReauthentication(authorization: string, method: string, code?: string, credential?: object): Promise<SecurityAuthorization> {
    return this.request("/api/v1/auth/reauthentication/factor", { method: "POST", body: JSON.stringify({ authorization, method, code, credential }) }, false);
  }

  setCsrfToken(token: string | null) {
    this.csrfToken = token;
  }

  getCsrfToken(): string | null {
    return this.csrfToken;
  }

  async getClientContext(clientId: string, redirectUri: string): Promise<{client_name:string;redirect_origin:string}> {
    const query=new URLSearchParams({client_id:clientId,redirect_uri:redirectUri});
    return this.request(`/oauth/client-context?${query.toString()}`);
  }

  async getLegalDocuments(): Promise<import("../types/api").LegalDocuments> {
    return this.request("/api/v1/legal/documents");
  }
  async acceptLegalDocuments(versions: Record<string, string>): Promise<void> {
    await this.request("/api/v1/auth/legal-acceptance", { method: "POST", body: JSON.stringify({ terms_accepted: true, data_processing_consent: true, legal_versions: versions }) });
  }
  async getDeletionStatus(): Promise<import("../types/api").DeletionStatus> {
    return this.request("/api/v1/auth/account-deletion");
  }
  async reauthenticateDeletion(action: "request" | "cancel", current_password: string): Promise<import("../types/api").DeletionAuthorization> {
    return this.request("/api/v1/auth/account-deletion/reauthenticate", { method: "POST", body: JSON.stringify({ action, current_password }) });
  }
  async confirmDeletionFactor(payload: { action: "request" | "cancel"; authorization: string; method: string; code?: string; credential?: unknown }): Promise<import("../types/api").DeletionAuthorization> {
    return this.request("/api/v1/auth/account-deletion/confirm-factor", { method: "POST", body: JSON.stringify(payload) });
  }
  async submitDeletion(action: "request" | "cancel", authorization: string): Promise<import("../types/api").DeletionStatus> {
    return this.request("/api/v1/auth/account-deletion", { method: action === "request" ? "POST" : "DELETE", body: JSON.stringify({ authorization }) });
  }

  private async request<T>(endpoint: string, options: RequestInit = {}, allowReauthentication = true): Promise<T> {
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
      let errorCode = response.status < 500 ? "request_rejected" : "server_unavailable";
      try {
        const errorData = await response.json();
        errorCode = errorData.error || errorData.detail?.error || errorCode;
        errorMessage = errorData.detail?.detail || errorData.detail || errorData.error_description || errorData.error || errorMessage;
      } catch {
        // Игнорируем ошибку парсинга JSON
      }
      if (errorCode === "reauthentication_required" && allowReauthentication && this.reauthenticationHandler) {
        const digest = await requestDigest(typeof options.body === "string" ? options.body : "");
        const authorization = await this.reauthenticationHandler(`${method} ${endpoint}`, digest);
        headers.set("X-Reauthentication", authorization);
        return this.request<T>(endpoint, { ...options, headers }, false);
      }
      throw new ApiError(typeof errorMessage === "string" ? errorMessage : `Ошибка HTTP ${response.status}`,
        response.status, errorCode, canonicalRoute(endpoint));
    }

    // Если 204 No Content
    if (response.status === 204) {
      return {} as T;
    }

    try {
      const payload: unknown = await response.json();
      if (!payload || typeof payload !== "object") throw new Error("Invalid JSON contract");
      return payload as T;
    } catch {
      captureContractFailure();
      throw new ApiError("Некорректный ответ сервера", response.status, "invalid_response", canonicalRoute(endpoint));
    }
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

  async changePassword(currentPassword: string, newPassword: string): Promise<{ status: string; message: string; requires_login: boolean }> {
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

  async createAdminClient(data: { client_name: string; client_type: string; redirect_uris: string[]; allowed_scopes?: string[] }): Promise<AdminClient> {
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

  async confirmRegistrationCode(challengeId: string, code: string): Promise<RegistrationCompleteResponse> {
    return this.request<RegistrationCompleteResponse>("/api/v1/auth/register/confirm-code", {
      method: "POST",
      body: JSON.stringify({ challenge_id: challengeId, code }),
    });
  }

  async confirmRegistrationLink(token: string): Promise<RegistrationCompleteResponse> {
    return this.request<RegistrationCompleteResponse>("/api/v1/auth/register/confirm-link", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  }

  async previewRegistrationLink(token: string): Promise<{ request_details: Record<string, string> }> {
    return this.request<{ request_details: Record<string, string> }>("/api/v1/auth/register/preview-link", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  }

  async resendRegistration(challengeId: string): Promise<RegisterResponse> {
    return this.request<RegisterResponse>("/api/v1/auth/register/resend", {
      method: "POST",
      body: JSON.stringify({ challenge_id: challengeId }),
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

  async getAuditEvents(offset = 0, limit = 50, filter = ""): Promise<AuditEventItem[]> {
    const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (filter.trim()) query.set("q", filter.trim());
    return this.request<AuditEventItem[]>(`/api/v1/admin/audit?${query}`);
  }

  async downloadAudit(format: "jsonl" | "csv", filter = ""): Promise<void> {
    const query = new URLSearchParams({ format });
    if (filter.trim()) query.set("q", filter.trim());
    const response = await fetch(`/api/v1/admin/audit/export?${query}`, { credentials: "include" });
    if (!response.ok) throw new Error(`Ошибка выгрузки аудита: HTTP ${response.status}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    try {
      const link = document.createElement("a");
      link.href = url;
      link.download = `alxprgs-audit.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  // --- Passkey / WebAuthn API (G4-PASSKEY) ---
  async getPasskeyRegistrationOptions(): Promise<EncodedCreationOptions | { publicKey: EncodedCreationOptions }> {
    return this.request<EncodedCreationOptions | { publicKey: EncodedCreationOptions }>("/api/v1/mfa/passkey/register/options", {
      method: "POST",
    });
  }

  async verifyPasskeyRegistration(credential: object, name = "Passkey"): Promise<{ status: string; message: string }> {
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

  async getPasskeyAuthOptions(): Promise<EncodedRequestOptions | { publicKey: EncodedRequestOptions }> {
    return this.request<EncodedRequestOptions | { publicKey: EncodedRequestOptions }>("/api/v1/mfa/passkey/auth/options", {
      method: "POST",
    });
  }

  async verifyPasskeyAuth(credential: object, mfaToken?: string): Promise<LoginResponse> {
    const res = await this.request<LoginResponse>("/api/v1/mfa/passkey/auth/verify", {
      method: "POST",
      body: JSON.stringify({ credential, mfa_token: mfaToken }),
    });
    if ("csrf_token" in res) {
      this.csrfToken = res.csrf_token;
    }
    return res;
  }

  // --- TOTP API (SEC-FLAG-01) ---
  async setupTotp(): Promise<TOTPSetupResponse> {
    return this.request<TOTPSetupResponse>("/api/v1/mfa/totp/setup", {
      method: "POST",
    });
  }

  async confirmTotp(code: string): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>("/api/v1/mfa/totp/confirm", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
  }

  async verifyTotpLogin(code: string, mfaToken: string): Promise<LoginResponse> {
    const res = await this.request<LoginResponse>("/api/v1/mfa/totp/verify", {
      method: "POST",
      body: JSON.stringify({ code, mfa_token: mfaToken }),
    });
    if ("csrf_token" in res) {
      this.csrfToken = res.csrf_token;
    }
    return res;
  }

  async deleteTotp(): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>("/api/v1/mfa/totp", {
      method: "DELETE",
    });
  }

  // --- Recovery Codes API (SEC-FLAG-02) ---
  async generateRecoveryCodes(): Promise<RecoveryCodesResponse> {
    return this.request<RecoveryCodesResponse>("/api/v1/mfa/recovery-codes/generate", {
      method: "POST",
    });
  }

  async verifyRecoveryCodeLogin(recoveryCode: string, mfaToken: string): Promise<LoginResponse> {
    const res = await this.request<LoginResponse>("/api/v1/mfa/recovery-codes/verify", {
      method: "POST",
      body: JSON.stringify({ recovery_code: recoveryCode, mfa_token: mfaToken }),
    });
    if ("csrf_token" in res) {
      this.csrfToken = res.csrf_token;
    }
    return res;
  }

  // --- Email Verification API (SEC-FLAG-07) ---
  async requestEmailVerification(email?: string): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>("/api/v1/mfa/email/request", {
      method: "POST",
      body: JSON.stringify({ email: email || null }),
    });
  }

  async confirmEmailVerification(token: string): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>("/api/v1/mfa/email/confirm", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  }

  async confirmEmailCode(email: string, code: string): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>("/api/v1/mfa/email/confirm-code", {
      method: "POST",
      body: JSON.stringify({ email, code }),
    });
  }
}

export const api = new ApiClient();
