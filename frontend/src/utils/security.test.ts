import { test, describe, before, after } from "node:test";
import assert from "node:assert/strict";
import { sanitizeReturnTo } from "./security.ts";

describe("Frontend Security Utils: sanitizeReturnTo (G8-SEC, FINAL-04)", () => {
  before(() => {
    // Mock window for Node.js test environment
    Object.defineProperty(globalThis, "window", { configurable: true, value: {
      location: {
        origin: "http://localhost:5173",
        host: "localhost:5173",
        hostname: "localhost",
      },
    } });
  });

  after(() => {
    Reflect.deleteProperty(globalThis, "window");
  });

  test("allows valid relative URLs", () => {
    assert.equal(sanitizeReturnTo("/dashboard"), "/dashboard");
    assert.equal(sanitizeReturnTo("/admin/users?page=1"), "/admin/users?page=1");
    assert.equal(sanitizeReturnTo("/oauth/authorize?client_id=123"), "/oauth/authorize?client_id=123");
  });

  test("rejects protocol-relative open redirect attacks", () => {
    assert.equal(sanitizeReturnTo("//evil.com"), null);
    assert.equal(sanitizeReturnTo("//evil.com/path"), null);
    assert.equal(sanitizeReturnTo("///evil.com"), null);
  });

  test("rejects backslash bypasses", () => {
    assert.equal(sanitizeReturnTo("/\\evil.com"), null);
    assert.equal(sanitizeReturnTo("\\evil.com"), null);
    assert.equal(sanitizeReturnTo("/path\\something"), null);
  });

  test("rejects dangerous pseudo-protocols", () => {
    assert.equal(sanitizeReturnTo("javascript:alert(1)"), null);
    assert.equal(sanitizeReturnTo("data:text/html,<script>alert(1)</script>"), null);
    assert.equal(sanitizeReturnTo("vbscript:msgbox(1)"), null);
  });

  test("rejects control characters and newlines", () => {
    assert.equal(sanitizeReturnTo("/dashboard\r\nSet-Cookie: evil"), null);
    assert.equal(sanitizeReturnTo("/dashboard\t"), null);
  });

  test("allows trusted target SSO absolute origins", () => {
    assert.equal(
      sanitizeReturnTo("http://localhost:8000/oauth/authorize?client_id=test"),
      "http://localhost:8000/oauth/authorize?client_id=test"
    );
    assert.equal(
      sanitizeReturnTo("https://auth.alxprgs.tech/oauth/authorize"),
      "https://auth.alxprgs.tech/oauth/authorize"
    );
  });

  test("rejects untrusted external absolute origins", () => {
    assert.equal(sanitizeReturnTo("https://evil.com/callback"), null);
    assert.equal(sanitizeReturnTo("https://attacker.alxprgs.tech.evil.com"), null);
    assert.equal(sanitizeReturnTo("http://localhost:3000/phish"), null);
  });
});
