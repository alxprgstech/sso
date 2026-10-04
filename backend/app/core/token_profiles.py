"""Explicit signed-token claim profiles; callers validate signature first."""

import re
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


def _checked_audience_items(values: Any) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= 10:
        raise ValueError("Invalid audience")
    if not all(_valid_string(value) for value in values):
        raise ValueError("Invalid audience")
    return values


def _audience_values(raw: Any) -> list[str]:
    values = [raw] if isinstance(raw, str) else raw
    values = _checked_audience_items(values)
    if len(set(values)) != len(values):
        raise ValueError("Invalid audience")
    return values


def _validate_authorized_party(
    payload: dict[str, Any], audience: str | None, values: list[str]
) -> None:
    if len(values) <= 1 and "azp" not in payload:
        return
    if not audience or payload.get("azp") != audience:
        raise ValueError("Invalid authorized party")


def _validate_audience(payload: dict[str, Any], audience: str | None) -> None:
    raw = payload.get("aud")
    if raw is None:
        return
    values = _audience_values(raw)
    use = payload.get("token_use")
    if use in {"access_token", "mfa_step"} and not isinstance(raw, str):
        raise ValueError("This profile requires one audience")
    if use == "id_token":
        _validate_authorized_party(payload, audience, values)


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


def _validate_access_profile(payload: dict[str, Any]) -> None:
    scope = payload.get("scope")
    if not isinstance(scope, str) or len(scope) > 255:
        raise ValueError("Invalid scope")
    if not re.fullmatch(r"[\x21\x23-\x5b\x5d-\x7e]+(?: [\x21\x23-\x5b\x5d-\x7e]+)*", scope):
        raise ValueError("Invalid scope")
    _validate_security_revision(payload)


def _validate_security_revision(payload: dict[str, Any]) -> None:
    if "security_revision" in payload and not _nonnegative_integer(payload["security_revision"]):
        raise ValueError("Invalid security revision")


def _validate_mfa_profile(payload: dict[str, Any]) -> None:
    if payload.get("purpose") != "mfa_step" or type(payload.get("security_revision")) is not int:
        raise ValueError("Invalid MFA step")
    _validate_mfa_methods(payload.get("methods"))


def _validate_mfa_methods(methods: Any) -> None:
    if not isinstance(methods, list) or not methods:
        raise ValueError("Invalid MFA methods")
    if any(method not in {"totp", "passkey", "recovery_code"} for method in methods):
        raise ValueError("Invalid MFA methods")


def _require_claims(payload: dict[str, Any], expected_use: str | None) -> None:
    use = payload.get("token_use")
    if expected_use is not None and use != expected_use:
        raise ValueError("Unexpected token profile")
    required = {"iss", "sub", "exp", "iat"}
    if use in {"access_token", "id_token", "mfa_step"}:
        required |= {"aud", "token_use"}
    if not required <= payload.keys():
        raise ValueError("Missing required claims")


def validate_claims(
    payload: dict[str, Any], audience: str | None = None, expected_use: str | None = None
) -> None:
    _require_claims(payload, expected_use)
    _validate_strings(payload, ("iss", "sub"))
    _validate_dates(payload)
    _validate_audience(payload, audience)
    _validate_optional_claims(payload)
    if payload.get("token_use") == "access_token":
        _validate_access_profile(payload)
    if payload.get("token_use") == "mfa_step":
        _validate_mfa_profile(payload)
