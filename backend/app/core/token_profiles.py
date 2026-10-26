"""Explicit signed-token claim profiles; callers validate signature first."""

import re
from typing import Any

from app.core.token_audience import _validate_audience
from app.core.token_dates import _nonnegative_integer, _validate_dates
from app.core.token_claims import (
    _validate_strings,
    _validate_optional_claims,
)


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


def _validate_step_up_profile(payload: dict[str, Any]) -> None:
    required = {"transaction_id", "action", "payload_hash", "acr", "amr", "nonce"}
    if not required <= payload.keys():
        raise ValueError("Missing step-up claims")
    if not isinstance(payload["transaction_id"], str) or not payload["transaction_id"]:
        raise ValueError("Invalid transaction")
    if not isinstance(payload["action"], str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_.:-]{0,63}", payload["action"]
    ):
        raise ValueError("Invalid action")
    if not isinstance(payload["payload_hash"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", payload["payload_hash"]
    ):
        raise ValueError("Invalid payload hash")
    if payload["acr"] not in {
        "reauth_basic",
        "reauth_mfa",
        "reauth_strict",
        "reauth_password_mfa",
    }:
        raise ValueError("Invalid assurance")
    methods = payload["amr"]
    if (
        not isinstance(methods, list)
        or not 1 <= len(methods) <= 3
        or any(method not in {"pwd", "otp", "hwk"} for method in methods)
        or len(set(methods)) != len(methods)
    ):
        raise ValueError("Invalid methods")
    if type(payload.get("security_revision")) is not int:
        raise ValueError("Invalid security revision")
    _validate_strings(payload, ("nonce",))


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
    if use in {"access_token", "id_token", "mfa_step", "external_step_up_proof"}:
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
    if payload.get("token_use") == "external_step_up_proof":
        _validate_step_up_profile(payload)
