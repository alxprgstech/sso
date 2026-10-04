"""Audience shape and authorized-party binding for signed token profiles."""

from typing import Any

from .token_claims import _valid_string


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
