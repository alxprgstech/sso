from __future__ import annotations


import secrets

import string

import uuid


from datetime import datetime, timezone


from sqlalchemy import delete, update


from sqlalchemy.ext.asyncio import AsyncSession


from app.core.exceptions import (
    AuthorizationException,
)

from app.core.security import (
    hash_token,
)

from app.models.mfa import (
    RecoveryCode,
)

from app.models.user import User

from app.services.audit_service import AuditService

from app.services.security_state import invalidate_security_state, lock_user

from app.config import Settings, get_settings


class RecoveryCodesService:
    @staticmethod
    def _normalize_code(code: str) -> str:
        return code.replace("-", "").replace(" ", "").upper().strip()

    @staticmethod
    def _has_active_factor(user: User, settings: Settings) -> bool:
        totp = bool(
            settings.FEATURE_TOTP_ENABLED
            and user.totp_credential
            and user.totp_credential.is_confirmed
        )
        passkey = bool(settings.FEATURE_PASSKEY_ENABLED and user.webauthn_credentials)
        return totp or passkey

    @staticmethod
    async def generate_codes(
        db: AsyncSession,
        user: User,
        session_id: uuid.UUID | None = None,
        settings: Settings | None = None,
    ) -> list[str]:
        """
        Выпуск нового набора из 10 резервных кодов.
        Разрешен при любом активном подтвержденном MFA-факторе: TOTP или Passkey.
        Показываются пользователю ТОЛЬКО ОДИН РАЗ.
        """
        active_settings = settings or get_settings()
        user = await lock_user(db, user.id)
        if not RecoveryCodesService._has_active_factor(user, active_settings):
            raise AuthorizationException(
                "Резервные коды могут быть выпущены только при активном подтверждённом "
                "факторе MFA (TOTP или Passkey)"
            )

        # Удаляем предыдущие коды пользователя
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))

        alphabet = string.ascii_uppercase + string.digits
        plain_codes = []
        for _ in range(10):
            code_str = "-".join(
                "".join(secrets.choice(alphabet) for _ in range(8)) for _ in range(4)
            )
            plain_codes.append(code_str)

            normalized = RecoveryCodesService._normalize_code(code_str)
            h = hash_token(normalized)
            rec = RecoveryCode(
                user_id=user.id,
                code_hash=h,
                is_used=False,
            )
            db.add(rec)

        # The caller already proved a fresh factor for this exact operation, so
        # this session keeps its assurance while other grants are revoked.
        await invalidate_security_state(
            db, user, preserve_session_id=session_id, preserve_assurance=True
        )
        await AuditService.log_event(db, event_type="recovery_codes_generated", user_id=user.id)
        return plain_codes

    @staticmethod
    async def consume_code(db: AsyncSession, user: User, code: str, *, commit: bool = True) -> bool:
        """
        Атомарное одноразовое погашение резервного кода (SEC-FLAG-03).
        Резервный код заменяет второй фактор после ввода пароля, но не является самостоятельным входом.
        """
        await lock_user(db, user.id)
        normalized = RecoveryCodesService._normalize_code(code)
        h = hash_token(normalized)
        now = datetime.now(timezone.utc)

        stmt = (
            update(RecoveryCode)
            .where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_hash == h,
                RecoveryCode.is_used.is_(False),
            )
            .values(is_used=True, used_at=now)
            .returning(RecoveryCode.id)
        )
        result = await db.execute(stmt)
        consumed_id = result.scalar_one_or_none()
        if consumed_id:
            await AuditService.log_event(
                db, event_type="recovery_code_used", user_id=user.id, commit=commit
            )
            return True
        return False
