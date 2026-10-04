"""Explicit signed-token claim profiles; callers validate signature first."""

import re
from typing import Any

from .token_audience import _validate_audience
from .token_claims import (
    _validate_optional_claims,
    _validate_strings,
)
from .token_dates import _nonnegative_integer, _validate_dates


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
