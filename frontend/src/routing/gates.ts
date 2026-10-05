import type { UserProfile } from "../types/api";
export type Gate =
  "loading" | "password" | "login" | "deletion" | "legal" | "application";

function isForcedLogin(path: string, search: string): boolean {
  if (path !== "/login") return false;
  return new URLSearchParams(search).get("force_login") === "1";
}

function requiresDeletionManagement(user: UserProfile, path: string): boolean {
  return Boolean(
    user.deletion_pending ||
    user.session_purpose === "deletion_management" ||
    path === "/account-deletion",
  );
}
/** URL never grants privileges; preserve the server session priorities. */
export function sessionGate(
  user: UserProfile | null,
  loading: boolean,
  path: string,
  search: string,
): Gate {
  if (loading) return "loading";
  if (user?.session_purpose === "password_change") return "password";
  if (isForcedLogin(path, search)) return "login";
  if (!user) return "login";
  if (requiresDeletionManagement(user, path)) return "deletion";
  if (user.legal_acceptance_required !== false) return "legal";
  return "application";
}
