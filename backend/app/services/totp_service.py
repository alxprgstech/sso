from __future__ import annotations


import math
import uuid


from datetime import datetime, timedelta, timezone


import pyotp


from sqlalchemy import delete, select


from sqlalchemy.ext.asyncio import AsyncSession


from app.config import get_settings

from app.core.exceptions import (
    AuthenticationException,
    TOTPReplayException,
)

from app.core.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
)

from app.models.mfa import (
    RecoveryCode,
    TOTPCredential,
)

from app.models.user import User

from app.services.audit_service import AuditService

from app.services.security_state import invalidate_security_state, lock_user


settings = get_settings()


def totp_step_usable(matched: int | None, previous: int | None) -> bool:
    if matched is None:
        return False
    if previous is None:
        return True
    return matched > previous


def replay_retry_after(previous: int, interval: int, now: datetime) -> int:
    """Seconds until a code that is strictly newer than ``previous`` can exist.

    When the redeemed code came from an older window the authenticator already
    shows a newer one, so the wait is zero. When the current window itself was
    spent, the user has to wait for the next 30-second step.
    """
    now_ts = now.timestamp()
    now_step = int(now_ts) // interval
    next_usable_step = max(now_step, previous + 1)
    return max(0, math.ceil(next_usable_step * interval - now_ts))


def pending_enrollment_bound(
    credential: TOTPCredential, session_id: uuid.UUID | None, now: datetime
) -> bool:
    return (
        credential.pending_expires_at is not None
        and credential.pending_expires_at > now
        and credential.pending_session_id == session_id
    )


def last_matching_step(totp: pyotp.TOTP, code: str, now: datetime) -> int:
    current_step = int(now.timestamp()) // totp.interval
    return max(
        step
        for step in (current_step - 1, current_step, current_step + 1)
        if totp.verify(code, for_time=datetime.fromtimestamp(step * totp.interval, timezone.utc))
    )


class TOTPService:
    @staticmethod
    async def setup_totp(
        db: AsyncSession, user: User, session_id: uuid.UUID | None = None
    ) -> tuple[str, str]:
        """
        Инициализирует подключение TOTP.
        Секрет шифруется симметричным ключом (AES/Fernet) перед сохранением в БД.
        Возвращает: (raw_base32_secret, provisioning_uri).
        """
        user = await lock_user(db, user.id)
        secret = pyotp.random_base32()
        encrypted = encrypt_totp_secret(secret)

        stmt = select(TOTPCredential).where(TOTPCredential.user_id == user.id)
        existing = (await db.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.pending_encrypted_secret = encrypted
            existing.pending_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
            existing.pending_session_id = session_id
        else:
            cred = TOTPCredential(
                user_id=user.id,
                encrypted_secret=encrypted,
                is_confirmed=False,
                pending_encrypted_secret=encrypted,
                pending_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                pending_session_id=session_id,
            )
            db.add(cred)

        await AuditService.log_event(db, event_type="totp_setup_started", user_id=user.id)

        totp_obj = pyotp.TOTP(secret)
        otpauth_url = totp_obj.provisioning_uri(
            name=user.email,
            issuer_name=settings.WEBAUTHN_RP_NAME,
        )
        return secret, otpauth_url

    @staticmethod
    async def confirm_totp(
        db: AsyncSession, user: User, code: str, session_id: uuid.UUID | None = None
    ) -> bool:
        """
        Подтверждение первого кода при подключении TOTP.
        Только после этого фактор считается активным.
        """
        user = await lock_user(db, user.id)
        stmt = select(TOTPCredential).where(TOTPCredential.user_id == user.id).with_for_update()
        cred = (await db.execute(stmt)).scalar_one_or_none()
        if not cred:
            raise AuthenticationException("Подключение TOTP не было инициировано")

        now = datetime.now(timezone.utc)
        if not cred.pending_encrypted_secret:
            return False
        if not pending_enrollment_bound(cred, session_id, now):
            return False
        raw_secret = decrypt_totp_secret(cred.pending_encrypted_secret)
        totp = pyotp.TOTP(raw_secret)

        if not totp.verify(code, valid_window=1):
            return False

        cred.is_confirmed = True
        cred.confirmed_at = now
        cred.encrypted_secret = cred.pending_encrypted_secret
        cred.pending_encrypted_secret = None
        cred.pending_expires_at = None
        cred.pending_session_id = None
        cred.last_verified_step = last_matching_step(totp, code, now)
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        await invalidate_security_state(db, user, preserve_session_id=session_id)
        await AuditService.log_event(db, event_type="totp_enabled", user_id=user.id)
        return True

    @staticmethod
    async def verify_totp(
        db: AsyncSession,
        user: User,
        code: str,
        *,
        commit: bool = True,
        replay_error: bool = False,
    ) -> bool:
        """
        Проверка TOTP кода при входе.

        ``replay_error`` is used by authenticated elevation/reauthentication
        flows: a code from an already redeemed step raises ``TOTPReplayException``
        (a distinct, retryable client error) instead of looking like a typo.
        The step is never accepted twice either way.
        """
        await lock_user(db, user.id)
        stmt = select(TOTPCredential).where(
            TOTPCredential.user_id == user.id,
            TOTPCredential.is_confirmed.is_(True),
        )
        cred = (await db.execute(stmt.with_for_update())).scalar_one_or_none()
        if not cred:
            return False

        raw_secret = decrypt_totp_secret(cred.encrypted_secret)
        totp = pyotp.TOTP(raw_secret)
        now = datetime.now(timezone.utc)
        current_step = int(now.timestamp()) // totp.interval
        matched = next(
            (
                step
                for step in (current_step - 1, current_step, current_step + 1)
                if totp.verify(
                    code, for_time=datetime.fromtimestamp(step * totp.interval, timezone.utc)
                )
            ),
            None,
        )
        if matched is None:
            return False
        previous = cred.last_verified_step
        if not totp_step_usable(matched, previous):
            if replay_error and previous is not None:
                raise TOTPReplayException(replay_retry_after(previous, totp.interval, now))
            return False
        cred.last_verified_step = matched
        await db.flush()
        if commit:
            await db.commit()
        return True

    @staticmethod
    async def remove_totp(
        db: AsyncSession, user: User, session_id: uuid.UUID | None = None
    ) -> None:
        """
        Удаление фактора TOTP и связанных резервных кодов.
        """
        user = await lock_user(db, user.id)
        await db.execute(delete(TOTPCredential).where(TOTPCredential.user_id == user.id))
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        await invalidate_security_state(db, user, preserve_session_id=session_id)
        await AuditService.log_event(db, event_type="totp_disabled", user_id=user.id)
