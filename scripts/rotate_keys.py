#!/usr/bin/env python3
"""ALXPRGS SSO Key Generation & Rotation Script.

Generates:
1. RSA 2048/4096-bit private/public key pair (PEM format) for OIDC RS256 token signing.
2. Fernet symmetric key for TOTP secrets encryption (MFA_ENCRYPTION_KEY).
3. Cryptographically secure 32-byte hex string for session/CSRF SECRET_KEY.

Usage:
    python scripts/rotate_keys.py [--output-dir keys/] [--bits 2048]
"""

import argparse
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_rsa_keypair(bits: int = 2048) -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def main():
    parser = argparse.ArgumentParser(
        description="Rotate or generate ALXPRGS SSO encryption and signing keys"
    )
    parser.add_argument(
        "--output-dir", default=None, help="Directory to save generated RSA PEM files"
    )
    parser.add_argument("--key-id", default=None, help="Key ID (kid) for the RSA keypair")
    parser.add_argument(
        "--bits", type=int, default=2048, choices=[2048, 4096], help="RSA key size in bits"
    )

    args = parser.parse_args()

    kid = args.key_id or f"rsa-key-{secrets.token_hex(4)}"

    print("[*] Generating ALXPRGS SSO Cryptographic Keys...")

    # 1. RSA Keypair
    priv_pem, pub_pem = generate_rsa_keypair(args.bits)
    print(f"[+] RSA {args.bits}-bit key pair generated (kid: {kid}).")

    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        priv_path = out_dir / "oidc_private.pem"
        pub_path = out_dir / "oidc_public.pem"
        priv_path.write_bytes(priv_pem)
        pub_path.write_bytes(pub_pem)
        print(f"    Private key saved to: {priv_path.resolve()}")
        print(f"    Public key saved to:  {pub_path.resolve()}")

    # 2. Fernet Key for MFA
    fernet_key = Fernet.generate_key().decode()
    print(f"[+] MFA_ENCRYPTION_KEY (Fernet): {fernet_key}")

    # 3. SECRET_KEY
    secret_key = secrets.token_hex(32)
    print(f"[+] SECRET_KEY (Hex):           {secret_key}")

    print("\n[*] Key Rotation (SSO-06) Environment Configuration:")
    print(f"    JWT_KEY_ID={kid}")
    print("    JWT_PRIVATE_KEY_PEM=<path_or_pem_content>")
    print("    (For overlapping period: configure previous public key)")
    print("    JWT_PREVIOUS_KEY_ID=<previous_kid>")
    print("    JWT_PREVIOUS_PUBLIC_KEY_PEM=<previous_pub_path_or_pem>")

    print(
        "\n[!] Keep private and encryption keys secret. Store securely in production environments."
    )


if __name__ == "__main__":
    main()
