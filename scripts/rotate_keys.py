#!/usr/bin/env python3
"""Generate one kind of key into a new private directory; never change live keys."""

from __future__ import annotations

import argparse
import csv
import os
import secrets
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_rsa_keypair(bits: int = 2048) -> tuple[bytes, bytes]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    return (
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
    )


def private_directory(path: Path) -> None:
    """Refuse reuse/symlinks; protect an empty directory before writing secrets."""
    if not path.parent.is_dir():
        raise ValueError("Output parent must already exist")
    path.mkdir(mode=0o700, exist_ok=False)
    if os.name == "nt":
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            check=True,
        )
        sid = next(csv.reader(identity.stdout.splitlines()))[1]
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            capture_output=True,
            check=True,
        )
    else:
        path.chmod(0o700)


def write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())


def generate_bundle(output: Path, kind: str, kid: str, bits: int) -> None:
    if kind == "rsa" and (
        not kid
        or len(kid) > 128
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in kid
        )
    ):
        raise ValueError("RSA requires an explicit safe key identifier")
    private_directory(output)
    if kind == "rsa":
        private, public = generate_rsa_keypair(bits)
        write_private(output / "oidc_private.pem", private)
        write_private(output / "oidc_public.pem", public)
        write_private(output / "JWT_KEY_ID", kid.encode("ascii"))
    elif kind == "session":
        write_private(output / "SESSION_SECRET_KEY", secrets.token_hex(64).encode("ascii"))
    elif kind == "totp":
        write_private(output / "TOTP_ENCRYPTION_KEY", Fernet.generate_key())
    else:
        raise ValueError("Unknown key kind")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--kind", choices=["rsa", "session", "totp"], required=True)
    parser.add_argument("--key-id", default="")
    parser.add_argument("--bits", type=int, default=3072, choices=[2048, 3072, 4096])
    args = parser.parse_args()
    try:
        generate_bundle(args.output_dir.absolute(), args.kind, args.key_id, args.bits)
    except (OSError, ValueError, subprocess.SubprocessError):
        print(
            "Key generation refused or failed; inspect the private destination locally.",
            file=sys.stderr,
        )
        return 1
    print(
        "Key files written to the explicit private destination; live configuration was not changed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
