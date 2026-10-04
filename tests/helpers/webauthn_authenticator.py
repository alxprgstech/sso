"""Software test authenticator: real P-256 signatures, COSE keys and UV flags."""

import hashlib
import json
import secrets
import struct
from dataclasses import dataclass

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url


@dataclass(frozen=True)
class AssertionProfile:
    rp_id: str | None = None
    uv: bool = True
    signature_valid: bool = True


class Authenticator:
    def __init__(self):
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.identifier = secrets.token_bytes(32)
        self.counter = 0

    @property
    def id(self):
        return bytes_to_base64url(self.identifier)

    def client_data(self, options, origin, kind):
        return json.dumps(
            {
                "type": kind,
                "challenge": options["challenge"],
                "origin": origin,
                "crossOrigin": False,
            },
            separators=(",", ":"),
        ).encode()

    def registration(self, options, origin, *, rp_id=None, uv=True):
        public = self.private.public_key().public_numbers()
        cose = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: public.x.to_bytes(32, "big"), -3: public.y.to_bytes(32, "big")}
        )
        data = self.client_data(options, origin, "webauthn.create")
        auth = hashlib.sha256((rp_id or options["rp"]["id"]).encode()).digest()
        auth += bytes([0x41 | (0x04 if uv else 0)]) + struct.pack(">I", 0)
        auth += bytes(16) + struct.pack(">H", len(self.identifier)) + self.identifier + cose
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal"],
            },
        }

    def assertion(self, options, origin, profile: AssertionProfile = AssertionProfile()):
        rp_id, uv, signature_valid = profile.rp_id, profile.uv, profile.signature_valid
        self.counter += 1
        data = self.client_data(options, origin, "webauthn.get")
        auth = hashlib.sha256((rp_id or options["rpId"]).encode()).digest()
        auth += bytes([0x01 | (0x04 if uv else 0)]) + struct.pack(">I", self.counter)
        signature = self.private.sign(
            auth + hashlib.sha256(data).digest(), ec.ECDSA(hashes.SHA256())
        )
        if not signature_valid:
            signature = bytes([signature[0] ^ 1]) + signature[1:]
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(data),
                "authenticatorData": bytes_to_base64url(auth),
                "signature": bytes_to_base64url(signature),
                "userHandle": None,
            },
        }
