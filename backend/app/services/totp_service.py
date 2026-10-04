from __future__ import annotations


import uuid


from datetime import datetime, timedelta, timezone


import pyotp


from sqlalchemy import delete, select


from sqlalchemy.ext.asyncio import AsyncSession


from app.config import get_settings

from app.core.exceptions import (
    AuthenticationException,
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

        await db.commit()

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
        if (
            not cred.pending_encrypted_secret
            or not cred.pending_expires_at
            or cred.pending_expires_at <= now
            or cred.pending_session_id != session_id
        ):
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
        current_step = int(now.timestamp()) // totp.interval
        cred.last_verified_step = max(
            step
            for step in (current_step - 1, current_step, current_step + 1)
            if totp.verify(
                code, for_time=datetime.fromtimestamp(step * totp.interval, timezone.utc)
            )
        )
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        await invalidate_security_state(db, user, preserve_session_id=session_id)
        await db.commit()
        await AuditService.log_event(db, event_type="totp_enabled", user_id=user.id)
        return True

    @staticmethod
    async def verify_totp(db: AsyncSession, user: User, code: str, *, commit: bool = True) -> bool:
        """
        Проверка TOTP кода при входе.
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
        current_step = int(datetime.now(timezone.utc).timestamp()) // totp.interval
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
        if not totp_step_usable(matched, cred.last_verified_step):
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
        await db.commit()
        await AuditService.log_event(db, event_type="totp_disabled", user_id=user.id)
