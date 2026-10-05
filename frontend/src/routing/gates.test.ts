import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionGate } from "./gates.ts";
import type { UserProfile } from "../types/api.ts";
const user: UserProfile = {
  id: "fixture",
  username: "fixture",
  email: "fixture@example.test",
  is_active: true,
  is_superuser: false,
  email_verified: true,
  roles: ["user"],
  has_totp: false,
  has_passkey: false,
  created_at: "2026-01-01T00:00:00Z",
  legal_acceptance_required: false,
  session_purpose: "full",
  deletion_pending: false,
};
test("server gates cannot be bypassed by admin deep links or force_login", () => {
  assert.equal(sessionGate(null, true, "/admin/users", ""), "loading");
  assert.equal(sessionGate(null, false, "/admin/system", ""), "login");
  assert.equal(
    sessionGate(
      { ...user, session_purpose: "password_change" },
      false,
      "/login",
      "?force_login=1",
    ),
    "password",
  );
  assert.equal(
    sessionGate(
      { ...user, session_purpose: "password_change", deletion_pending: true },
      false,
      "/admin/users",
      "",
    ),
    "password",
  );
  assert.equal(
    sessionGate(
      { ...user, deletion_pending: true, legal_acceptance_required: true },
      false,
      "/admin/users",
      "",
    ),
    "deletion",
  );
  assert.equal(
    sessionGate(
      { ...user, session_purpose: "deletion_management" },
      false,
      "/account/security",
      "",
    ),
    "deletion",
  );
  assert.equal(
    sessionGate(
      { ...user, legal_acceptance_required: true },
      false,
      "/admin/audit",
      "",
    ),
    "legal",
  );
  assert.equal(
    sessionGate(
      { ...user, legal_acceptance_required: undefined },
      false,
      "/",
      "",
    ),
    "legal",
  );
  assert.equal(sessionGate(user, false, "/login", "?force_login=1"), "login");
  assert.equal(sessionGate(user, false, "/account-deletion", ""), "deletion");
  assert.equal(sessionGate(user, false, "/admin/users", ""), "application");
});
