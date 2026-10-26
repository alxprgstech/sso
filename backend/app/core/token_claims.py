"""Identity strings, roles and verified-email shape in already signed tokens."""

from typing import Any


def _valid_string(value: Any, maximum: int = 255) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= maximum


def _validate_strings(payload: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in payload and not _valid_string(payload[key]):
            raise ValueError("Invalid string claim")


def _validate_roles(roles: Any) -> None:
    if not isinstance(roles, list) or len(roles) > 100:
        raise ValueError("Invalid roles")
    if not all(_valid_string(role, 64) for role in roles):
        raise ValueError("Invalid roles")


def _validate_optional_claims(payload: dict[str, Any]) -> None:
    _validate_strings(payload, ("preferred_username", "email", "nonce", "jti"))
    if "email_verified" in payload and type(payload["email_verified"]) is not bool:
        raise ValueError("Invalid verification flag")
    if "roles" in payload:
        _validate_roles(payload["roles"])


def _validate_assurance_claims(payload: dict[str, Any]) -> None:
    """Bound the standard assurance claims emitted by this issuer."""
    if "amr" in payload:
        methods = payload["amr"]
        if (
            not isinstance(methods, list)
            or not 1 <= len(methods) <= 4
            or any(method not in {"pwd", "otp", "hwk", "mfa"} for method in methods)
            or len(set(methods)) != len(methods)
        ):
            raise ValueError("Invalid amr")
    if "acr" in payload and payload["acr"] not in {
        "urn:alxprgs:acr:pwd",
        "urn:alxprgs:acr:mfa",
    }:
        raise ValueError("Invalid acr")
