"""Load bounded RSA material without including secrets in configuration errors."""

import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def validate_key_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("JWT key identifier must contain 1–128 safe ASCII characters")
    return value


def _read_pem(value: str) -> bytes:
    try:
        if value.lstrip().startswith("-----BEGIN "):
            data = value.encode("ascii")
        else:
            with Path(value).open("rb") as source:
                data = source.read(16385)
        if not data or len(data) > 16384:
            raise ValueError
        return data
    except (OSError, ValueError, UnicodeError):
        raise ValueError("RSA key material is missing, unreadable or invalid") from None


def load_private_key(value: str) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(_read_pem(value), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise ValueError(
            "JWT_PRIVATE_KEY_PEM requires a readable RSA key of at least 2048 bits"
        ) from None


def load_public_key(value: str) -> rsa.RSAPublicKey:
    try:
        key = serialization.load_pem_public_key(_read_pem(value))
        if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise ValueError(
            "JWT_PREVIOUS_PUBLIC_KEY_PEM requires an RSA public key of at least 2048 bits"
        ) from None
