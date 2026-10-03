from __future__ import annotations

import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditEvent
from app.core.privacy import short_user_agent


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
                    safe_details[k] = v

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
