"""Finite diagnostic codes and request identity, independent of payloads and PII."""

import logging
import uuid
from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
CODES = {
    "http_request": {"success", "client_rejected", "server_failed"},
    "database_readiness": {"database_unavailable", "ready"},
    "privacy_maintenance": {"completed", "database_unavailable"},
    "email_delivery": {
        "credentials_unavailable",
        "temporary_unavailable",
        "sdk_error",
        "invalid_response",
        "smtp_unconfigured",
        "smtp_connection_failed",
        "message_rejected",
        "access_denied",
        "identity_not_verified",
        "quota_exceeded",
        "failed",
    },
}


def correlation(value: str | None) -> str:
    try:
        parsed = uuid.UUID(value or "")
        if str(parsed) == value:
            return str(parsed)
    except (ValueError, TypeError, AttributeError):
        pass
    return str(uuid.uuid4())


def diagnostic(operation: str, reason: str, *, failed: bool = False) -> None:
    if operation not in CODES or reason not in CODES[operation]:
        return
    logging.getLogger("app.operations").log(
        logging.ERROR if failed else logging.INFO,
        "Operation result",
        extra={"operation": operation, "reason": reason},
    )
