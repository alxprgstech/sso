import type { UserProfile } from "../types/api";
export type Gate =
  "loading" | "password" | "login" | "deletion" | "legal" | "application";
/** URL never grants privileges; preserve the server session priorities. */
export function sessionGate(
  user: UserProfile | null,
  loading: boolean,
  path: string,
  search: string,
): Gate {
  if (loading) return "loading";
  if (user?.session_purpose === "password_change") return "password";
  if (
    path === "/login" &&
    new URLSearchParams(search).get("force_login") === "1"
  )
    return "login";
  if (!user) return "login";
  if (
    user.deletion_pending ||
    user.session_purpose === "deletion_management" ||
    path === "/account-deletion"
  )
    return "deletion";
  if (user.legal_acceptance_required !== false) return "legal";
  return "application";
}
