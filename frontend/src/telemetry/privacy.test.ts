import assert from "node:assert/strict";
import { test } from "node:test";
import { canonicalRoute, sanitizeEvent, sanitizeBreadcrumb, sanitizeReplayMetadata } from "./privacy.ts";

const secret = "canary-verification-password-email-never-export"; // pragma: allowlist secret -- synthetic canary
test("initial verification URL, nested events and whole exception chain are minimized", () => {
  const event = sanitizeEvent({
    request: { url: `https://sso.invalid/verify-email?token=${secret}#${secret}`, headers: { Cookie: secret }, data: secret },
    exception: { values: [{ type: "TypeError", value: secret }, { type: secret, value: secret }] },
    user: { email: secret }, extra: { nested: { value: secret } }, tags: { arbitrary: secret },
    breadcrumbs: [{ message: secret }], contexts: { geo: { country: secret } },
  });
  assert.ok(event);
  assert.equal(event.transaction, "/verify-email");
  assert.equal(JSON.stringify(event).includes(secret), false);
});
test("only explicit navigation breadcrumbs survive", () => {
  assert.equal(sanitizeBreadcrumb({ category: "console", message: secret }), null);
  assert.deepEqual(sanitizeBreadcrumb({ category: "sso.navigation", message: "admin", data: { secret } }), { category: "sso.navigation", message: "admin", level: "info" });
  const event = sanitizeEvent({ exception: { values: [{ type: "Error" }] }, breadcrumbs: [{ category: "sso.navigation", message: "admin", data: { secret } }] });
  assert.equal(event?.breadcrumbs?.[0].message, "admin");
  assert.equal(JSON.stringify(event).includes(secret), false);
});
test("Replay metadata is independently projected", () => {
  const event = sanitizeReplayMetadata({ type: "replay_event", request: { url: secret }, user: { email: secret }, urls: [`/verify-email?token=${secret}`], replay_id: "a".repeat(32), segment_id: 0 } as Parameters<typeof sanitizeReplayMetadata>[0]);
  assert.ok(event);
  assert.equal(JSON.stringify(event).includes(secret), false);
  assert.equal(sanitizeReplayMetadata({ type: "replay_event", urls: secret } as unknown as Parameters<typeof sanitizeReplayMetadata>[0]), null);
});
test("unrecognized path content cannot become a transaction", () => {
  assert.equal(canonicalRoute(`/private/${secret}`), "unmatched");
  assert.equal(canonicalRoute(`/api/v1/admin/users/${secret}?search=${secret}`), "/api/v1/admin/users/{id}");
});

test("redesign routes stay finite and discard query/hash and unknown identifiers", () => {
  for (const path of ["/account/security", "/account/sessions", "/account/privacy", "/admin/users", "/admin/applications", "/admin/sessions", "/admin/audit", "/admin/system", "/oauth/client-context"]) {
    assert.equal(canonicalRoute(`${path}?search=${secret}#${secret}`), path);
  }
  assert.equal(canonicalRoute(`/admin/users/${secret}`), "unmatched");
  assert.equal(canonicalRoute(`/account/${secret}`), "unmatched");
});
