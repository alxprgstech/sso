"""Exact-origin and redirect validation without rewriting registered URIs."""

import ipaddress
from urllib.parse import urlsplit


def origin(value: str) -> str:
    if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        raise ValueError("Invalid origin")
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Invalid origin")
    _ = parsed.port
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Invalid origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_redirect(value: str, *, local: bool = False) -> None:
    if (
        any(character.isspace() or ord(character) < 32 for character in value)
        or "*" in value
        or "\\" in value
    ):
        raise ValueError("Unsafe redirect URI")
    parsed = urlsplit(value)
    origin(value)
    if parsed.fragment:
        raise ValueError("Unsafe redirect URI")
    if parsed.scheme == "https":
        return
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        pass
    if not local or not loopback:
        raise ValueError("HTTPS redirect URI required")
