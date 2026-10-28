import { describe, test } from "node:test";
import assert from "node:assert/strict";
import {
  buildRecoveryCodesTxt,
  formatRecoveryCodesDate,
  recoveryCodesFileName,
} from "./recoveryCodes.ts";

const createdAt = new Date(2026, 9, 28, 23, 15, 42);

describe("Frontend Recovery Codes TXT export", () => {
  test("formats local date and file name", () => {
    assert.equal(formatRecoveryCodesDate(createdAt), "28.10.2026 23:15");
    assert.equal(
      recoveryCodesFileName(createdAt),
      "alxprgs-sso-recovery-codes-2026-10-28.txt",
    );
  });

  test("includes BOM, account email, all codes in order and instructions", () => {
    const codes = ["AAAA-BBBB-CCCC-DDDD", "EEEE-FFFF-GGGG-HHHH"];
    const content = buildRecoveryCodesTxt(
      "user@example.test",
      codes,
      createdAt,
    );
    assert.equal(content.charCodeAt(0), 0xfeff);
    assert.match(content, /Учётная запись: user@example\.test/);
    assert.match(content, /Дата создания: 28\.10\.2026 23:15/);
    assert.match(content, /TXT-файл не зашифрован/);
    assert.match(content, /ИНСТРУКЦИЯ/);
    assert.match(content, /Каждый код можно использовать только один раз/);
    assert.ok(content.includes(codes.join("\n")));
    assert.equal(content.split(codes[0]).length, 2);
    assert.equal(content.split(codes[1]).length, 2);
  });

  test("keeps every code of a full 10-code set", () => {
    const codes = Array.from(
      { length: 10 },
      (_, index) => `CODE-${String(index).padStart(4, "0")}`,
    );
    const content = buildRecoveryCodesTxt("user@example.test", codes, createdAt);
    for (const code of codes) assert.ok(content.includes(code));
  });
});
