import { describe, test } from "node:test";
import assert from "node:assert/strict";
import {
  formatPasskeyFallbackName,
  suggestPasskeyName,
  type PasskeyNameSource,
} from "./webauthn.ts";

function credential(
  attachment: AuthenticatorAttachment | null,
  transports: AuthenticatorTransport[] | null,
) {
  return {
    authenticatorAttachment: attachment,
    response: {
      getTransports: transports === null ? undefined : () => transports,
    },
  } as unknown as PasskeyNameSource;
}

describe("Frontend WebAuthn passkey naming", () => {
  test("uses only reliable WebAuthn metadata for the suggestion", () => {
    assert.equal(
      suggestPasskeyName(credential("platform", ["internal"])),
      "Passkey на этом устройстве",
    );
    assert.equal(
      suggestPasskeyName(credential("cross-platform", ["usb"])),
      "Аппаратный ключ безопасности",
    );
    assert.equal(
      suggestPasskeyName(credential("cross-platform", ["hybrid"])),
      "Passkey на телефоне",
    );
  });

  test("leaves the field empty when metadata is not conclusive", () => {
    assert.equal(suggestPasskeyName(credential(null, null)), "");
    assert.equal(suggestPasskeyName(credential("cross-platform", [])), "");
    assert.equal(suggestPasskeyName(credential(null, ["internal"])), "");
  });

  test("builds a local-time fallback name within the UI length limit", () => {
    const name = formatPasskeyFallbackName(new Date(2026, 9, 28, 23, 15, 7));
    assert.equal(name, "Passkey_2026-10-28_23-15-07");
    assert.ok(name.length <= 128);
  });
});
