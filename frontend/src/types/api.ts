export interface Capabilities {
  totp_enabled: boolean;
  passkey_enabled: boolean;
  recovery_codes_enabled: boolean;
  email_verification_enabled: boolean;
  require_verified_email: boolean;
  registration_mode: "closed" | "open" | string;
}

export interface SystemStatus {
  bootstrap_completed: boolean;
  bootstrap_completed_at: string | null;
  registration_mode: "closed" | "open" | string;
  total_users: number;
  total_active_admins: number;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  confirm_password: string;
}

export interface RegisterResponse {
  status: string;
  message: string;
  user_id: string;
  username: string;
  email: string;
  email_verification_required: boolean;
}

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  email_verified: boolean;
  roles: string[];
  has_totp: boolean;
  has_passkey: boolean;
  created_at: string;
}

export interface SessionInfo {
  id: string;
  ip_address: string | null;
  user_agent: string | null;
  is_current: boolean;
  last_activity_at: string;
  expires_at: string;
  created_at: string;
}

export interface LoginResponseSuccess {
  status: "ok";
  csrf_token: string;
  user: UserProfile;
}

export interface LoginResponseMFA {
  mfa_required: true;
  mfa_token: string;
  available_methods: string[];
}

export type LoginResponse = LoginResponseSuccess | LoginResponseMFA;

export interface AdminUser {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  email_verified: boolean;
  roles: string[];
  created_at: string;
  updated_at: string;
}

export interface AdminClient {
  id: string;
  client_id: string;
  client_name: string;
  client_type: string;
  is_active: boolean;
  redirect_uris: string[];
  client_secret: string | null;
  created_at: string;
}

export interface AuditEventItem {
  id: string;
  event_type: string;
  user_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  details: Record<string, any>;
  created_at: string;
}

export interface TOTPSetupResponse {
  secret: string;
  otpauth_url: string;
}

export interface RecoveryCodesResponse {
  recovery_codes: string[];
}

