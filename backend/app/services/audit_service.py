from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.privacy import short_user_agent
from app.models.audit import AuditEvent


class AuditService:
    @staticmethod
    async def log_event(
        db: AsyncSession,
        event_type: str,
        user_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
        *,
        commit: bool = True,
    ) -> AuditEvent:
        """
        Записывает событие аудита безопасности.
        Политика безопасности: запрещено логировать пароли, сырые токены, ключи и коды.
        """
        # Фильтрация чувствительных ключей из details
        safe_details = {}
        if details:
            for k, v in details.items():
                if any(
                    secret_term in k.lower()
                    for secret_term in [
                        "password",
                        "secret",
                        "token",
                        "code",
                        "private_key",
                        "cookie",
                    ]
                ):
                    safe_details[k] = "[REDACTED]"
                elif k.lower() in {
                    "identifier",
                    "username",
                    "email",
                    "name",
                    "credential_id",
                    "city",
                    "country",
                }:
                    continue
                else:
                    safe_details[k] = scrub_detail(v)
        from app.core.diagnostics import request_id

        current_request_id = request_id.get()
        if current_request_id:
            safe_details["request_id"] = current_request_id

        event = AuditEvent(
            event_type=event_type,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=short_user_agent(user_agent) if user_agent else None,
            details=safe_details,
        )
        db.add(event)
        await db.flush()
        if commit:
            await db.commit()
        return event


def scrub_detail(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(
                    term in key.lower()
                    for term in (
                        "password",
                        "secret",
                        "token",
                        "code",
                        "key",
                        "cookie",
                        "email",
                        "name",
                        "identifier",
                        "credential",
                        "address",
                        "header",
                        "query",
                        "body",
                    )
                )
                else scrub_detail(item, depth + 1)
            )
            for key, item in list(value.items())[:32]
            if isinstance(key, str) and len(key) <= 64
        }
    if isinstance(value, list):
        return [scrub_detail(item, depth + 1) for item in value[:32]]
    if isinstance(value, str):
        # Only finite server-selected labels or UUID references reach audit details.
        labels = {
            "smtp",
            "ses",
            "open",
            "closed",
            "registration",
            "verified_email",
            "update_registration_mode",
            "user_not_found_or_inactive",
            "invalid_password",
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
            "openid",
            "openid profile",
            "openid email",
            "openid profile email",
        }
        if value in labels:
            return value
        try:
            if str(uuid.UUID(value)) == value:
                return value
        except (ValueError, TypeError):
            pass
        return "[REDACTED]"
    return value if type(value) in {int, bool} or value is None else "[REDACTED]"
