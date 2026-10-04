"""Structural types and temporal order of already signed token claims."""

import time
from typing import Any


def _valid_string(value: Any, maximum: int = 255) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= maximum


def _validate_strings(payload: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in payload and not _valid_string(payload[key]):
            raise ValueError("Invalid string claim")


def _nonnegative_integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _validate_numeric_dates(payload: dict[str, Any]) -> None:
    for key in ("exp", "iat", "nbf", "auth_time"):
        if key in payload and not _nonnegative_integer(payload[key]):
            raise ValueError("Invalid NumericDate")


def _validate_dates(payload: dict[str, Any]) -> None:
    _validate_numeric_dates(payload)
    if payload["exp"] <= payload["iat"] or payload["iat"] > time.time():
        raise ValueError("Invalid temporal order")
    auth_time = payload.get("auth_time", payload["iat"])
    if auth_time > payload["iat"]:
        raise ValueError("Authentication time cannot follow issue time")


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
