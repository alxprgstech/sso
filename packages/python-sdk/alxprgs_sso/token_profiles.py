"""Explicit signed-token claim profiles; callers validate signature first."""

import re
import time
from typing import Any


def validate_claims(
    payload: dict[str, Any], audience: str | None = None, expected_use: str | None = None
) -> None:
    required = {"iss", "sub", "exp", "iat"}
    use = payload.get("token_use")
    if expected_use is not None and use != expected_use:
        raise ValueError("Unexpected token profile")
    if use in {"access_token", "id_token", "mfa_step"}:
        required |= {"aud", "token_use"}
    if not required <= payload.keys():
        raise ValueError("Missing required claims")
    for key in ("iss", "sub"):
        if not isinstance(payload[key], str) or not 1 <= len(payload[key]) <= 255:
            raise ValueError("Invalid string claim")
    for key in ("exp", "iat", "nbf", "auth_time"):
        if key in payload and (type(payload[key]) is not int or payload[key] < 0):
            raise ValueError("Invalid NumericDate")
    if payload["exp"] <= payload["iat"] or payload["iat"] > time.time():
        raise ValueError("Invalid temporal order")
    if "auth_time" in payload and payload["auth_time"] > payload["iat"]:
        raise ValueError("Authentication time cannot follow issue time")
    aud = payload.get("aud")
    if aud is not None:
        audiences = [aud] if isinstance(aud, str) else aud
        if (
            not isinstance(audiences, list)
            or not 1 <= len(audiences) <= 10
            or any(not isinstance(item, str) or not 1 <= len(item) <= 255 for item in audiences)
            or len(set(audiences)) != len(audiences)
        ):
            raise ValueError("Invalid audience")
        if use in {"access_token", "mfa_step"} and not isinstance(aud, str):
            raise ValueError("This profile requires one audience")
        if use == "id_token" and (len(audiences) > 1 or "azp" in payload):
            if not audience or payload.get("azp") != audience:
                raise ValueError("Invalid authorized party")
    for key in ("preferred_username", "email", "nonce", "jti"):
        if key in payload and (
            not isinstance(payload[key], str) or not 1 <= len(payload[key]) <= 255
        ):
            raise ValueError("Invalid optional string claim")
    if "email_verified" in payload and type(payload["email_verified"]) is not bool:
        raise ValueError("Invalid verification flag")
    if "roles" in payload:
        roles = payload["roles"]
        if (
            not isinstance(roles, list)
            or len(roles) > 100
            or any(not isinstance(role, str) or not 1 <= len(role) <= 64 for role in roles)
        ):
            raise ValueError("Invalid roles")
    if use == "access_token":
        scope = payload.get("scope")
        if (
            not isinstance(scope, str)
            or len(scope) > 255
            or not re.fullmatch(r"[\x21\x23-\x5b\x5d-\x7e]+(?: [\x21\x23-\x5b\x5d-\x7e]+)*", scope)
        ):
            raise ValueError("Invalid scope")
        if "security_revision" in payload and (
            type(payload["security_revision"]) is not int or payload["security_revision"] < 0
        ):
            raise ValueError("Invalid security revision")
    if use == "mfa_step":
        if (
            payload.get("purpose") != "mfa_step"
            or type(payload.get("security_revision")) is not int
        ):
            raise ValueError("Invalid MFA step")
        methods = payload.get("methods")
        if (
            not isinstance(methods, list)
            or not methods
            or any(method not in {"totp", "passkey", "recovery_code"} for method in methods)
        ):
            raise ValueError("Invalid MFA methods")
