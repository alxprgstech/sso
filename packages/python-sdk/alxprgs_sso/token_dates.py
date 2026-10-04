"""Exact NumericDate types and authentication/issue/expiration order."""

import time
from typing import Any


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
