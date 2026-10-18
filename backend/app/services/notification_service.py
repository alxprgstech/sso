"""Security notices share the mutation transaction; delivery is at least once."""

import asyncio
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.diagnostics import diagnostic
from app.models.notification import SecurityNotification
from app.models.user import User
from app.services.verification_email import deliver_message

NOTICES = {
    "password_change": "Пароль изменён",
    "totp_enabled": "Фактор TOTP включён",
    "totp_disabled": "Фактор TOTP отключён",
    "passkey_registered": "Добавлен ключ Passkey",
    "passkey_deleted": "Удалён ключ Passkey",
    "recovery_codes_generated": "Резервные коды обновлены",
    "email_changed": "Адрес электронной почты изменён",
}


def enqueue(db: AsyncSession, user: User, kind: str) -> None:
    if kind not in NOTICES or not user.email_verified:
        return
    now = datetime.now(timezone.utc)
    db.add(
        SecurityNotification(
            user_id=user.id,
            recipient=user.email,
            kind=kind,
            attempts=0,
            next_attempt_at=now,
            expires_at=now + timedelta(hours=24),
        )
    )


async def dispatch(db: AsyncSession, settings: Settings, *, limit: int = 20) -> int:
    now = datetime.now(timezone.utc)
    rows = (
        await db.scalars(
            select(SecurityNotification)
            .where(
                or_(
                    SecurityNotification.next_attempt_at <= now,
                    SecurityNotification.expires_at <= now,
                    SecurityNotification.attempts >= 5,
                )
            )
            .order_by(SecurityNotification.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    sent = 0
    for row in rows:
        now = datetime.now(timezone.utc)
        if row.expires_at <= now or row.attempts >= 5:
            diagnostic("security_notification", "delivery_exhausted", failed=True)
            await db.delete(row)
            continue
        message = EmailMessage()
        message["To"] = row.recipient
        message["From"] = (
            settings.SES_FROM_EMAIL
            if settings.EMAIL_PROVIDER == "ses"
            else settings.SMTP_FROM_EMAIL
        )
        message["Subject"] = "ALXPRGS SSO: изменение безопасности аккаунта"
        message.set_content(
            NOTICES[row.kind] + ". Если изменение выполнили не вы, обратитесь к администратору."
        )
        row.attempts += 1
        try:
            async with asyncio.timeout(min(30, (row.expires_at - now).total_seconds())):
                await deliver_message(message, settings)
        except Exception:
            diagnostic("security_notification", "delivery_failed", failed=True)
            if row.attempts >= 5:
                await db.delete(row)
            else:
                row.next_attempt_at = now + timedelta(seconds=60 * 2**row.attempts)
        else:
            await db.delete(row)
            sent += 1
    await db.commit()
    return sent
