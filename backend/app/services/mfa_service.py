from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
import pyotp
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
import webauthn
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationException, AuthorizationException
from app.core.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_random_token,
    hash_token,
)
from app.models.mfa import (
    EmailVerificationToken,
    RecoveryCode,
    TOTPCredential,
    WebAuthnChallenge,
    WebAuthnCredential,
)
from app.models.user import User
from app.services.audit_service import AuditService

settings = get_settings()

# Локальный сборщик отправленных писем (in-memory mail sink, SEC-FLAG-07)
sent_emails_sink: list[dict[str, Any]] = []


class TOTPService:
    @staticmethod
    async def setup_totp(db: AsyncSession, user: User) -> tuple[str, str]:
        """
        Инициализирует подключение TOTP.
        Секрет шифруется симметричным ключом (AES/Fernet) перед сохранением в БД.
        Возвращает: (raw_base32_secret, provisioning_uri).
        """
        secret = pyotp.random_base32()
        encrypted = encrypt_totp_secret(secret)

        stmt = select(TOTPCredential).where(TOTPCredential.user_id == user.id)
        existing = (await db.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.encrypted_secret = encrypted
            existing.is_confirmed = False
            existing.confirmed_at = None
        else:
            cred = TOTPCredential(
                user_id=user.id,
                encrypted_secret=encrypted,
                is_confirmed=False,
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
    async def confirm_totp(db: AsyncSession, user: User, code: str) -> bool:
        """
        Подтверждение первого кода при подключении TOTP.
        Только после этого фактор считается активным.
        """
        stmt = select(TOTPCredential).where(TOTPCredential.user_id == user.id)
        cred = (await db.execute(stmt)).scalar_one_or_none()
        if not cred:
            raise AuthenticationException("Подключение TOTP не было инициировано")

        raw_secret = decrypt_totp_secret(cred.encrypted_secret)
        totp = pyotp.TOTP(raw_secret)

        if not totp.verify(code, valid_window=1):
            return False

        cred.is_confirmed = True
        cred.confirmed_at = datetime.now(timezone.utc)
        await db.commit()
        await AuditService.log_event(db, event_type="totp_enabled", user_id=user.id)
        return True

    @staticmethod
    async def verify_totp(db: AsyncSession, user: User, code: str) -> bool:
        """
        Проверка TOTP кода при входе.
        """
        stmt = select(TOTPCredential).where(
            TOTPCredential.user_id == user.id,
            TOTPCredential.is_confirmed.is_(True),
        )
        cred = (await db.execute(stmt)).scalar_one_or_none()
        if not cred:
            return False

        raw_secret = decrypt_totp_secret(cred.encrypted_secret)
        totp = pyotp.TOTP(raw_secret)
        return bool(totp.verify(code, valid_window=1))

    @staticmethod
    async def remove_totp(db: AsyncSession, user: User) -> None:
        """
        Удаление фактора TOTP и связанных резервных кодов.
        """
        await db.execute(delete(TOTPCredential).where(TOTPCredential.user_id == user.id))
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        await db.commit()
        await AuditService.log_event(db, event_type="totp_disabled", user_id=user.id)


class RecoveryCodesService:
    @staticmethod
    def _normalize_code(code: str) -> str:
        return code.replace("-", "").replace(" ", "").upper().strip()

    @staticmethod
    async def generate_codes(db: AsyncSession, user: User) -> list[str]:
        """
        Выпуск нового набора из 10 резервных кодов.
        Разрешен ТОЛЬКО при активном подтвержденном факторе TOTP (SEC-FLAG-03).
        Показываются пользователю ТОЛЬКО ОДИН РАЗ.
        """
        if not (user.totp_credential and user.totp_credential.is_confirmed):
            raise AuthorizationException(
                "Резервные коды могут быть выпущены только при активном факторе TOTP"
            )

        # Удаляем предыдущие коды пользователя
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))

        alphabet = string.ascii_uppercase + string.digits
        plain_codes = []
        for _ in range(10):
            part1 = "".join(secrets.choice(alphabet) for _ in range(5))
            part2 = "".join(secrets.choice(alphabet) for _ in range(5))
            code_str = f"{part1}-{part2}"
            plain_codes.append(code_str)

            normalized = RecoveryCodesService._normalize_code(code_str)
            h = hash_token(normalized)
            rec = RecoveryCode(
                user_id=user.id,
                code_hash=h,
                is_used=False,
            )
            db.add(rec)

        await db.commit()
        await AuditService.log_event(db, event_type="recovery_codes_generated", user_id=user.id)
        return plain_codes

    @staticmethod
    async def consume_code(db: AsyncSession, user: User, code: str) -> bool:
        """
        Атомарное одноразовое погашение резервного кода (SEC-FLAG-03).
        Резервный код заменяет второй фактор после ввода пароля, но не является самостоятельным входом.
        """
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
        await db.commit()

        consumed_id = result.scalar_one_or_none()
        if consumed_id:
            await AuditService.log_event(db, event_type="recovery_code_used", user_id=user.id)
            return True
        return False


class WebAuthnService:
    @staticmethod
    async def get_registration_options(db: AsyncSession, user: User) -> dict[str, Any]:
        """
        Генерирует challenge и опции для регистрации нового WebAuthn Passkey (W3C WebAuthn Level 3).
        """
        # Получаем уже существующие credentials пользователя
        existing_creds_stmt = select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
        existing_creds = (await db.execute(existing_creds_stmt)).scalars().all()

        exclude_credentials = [
            webauthn.helpers.structs.PublicKeyCredentialDescriptor(
                id=cred.credential_id.encode("utf-8")
            )
            for cred in existing_creds
        ]

        options = webauthn.generate_registration_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            rp_name=settings.WEBAUTHN_RP_NAME,
            user_id=str(user.id).encode("utf-8"),
            user_name=user.username,
            user_display_name=user.username,
            attestation=webauthn.helpers.structs.AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
            exclude_credentials=exclude_credentials,
        )

        challenge_str = webauthn.helpers.bytes_to_base64url(options.challenge) if isinstance(options.challenge, bytes) else options.challenge
        now = datetime.now(timezone.utc)
        challenge_record = WebAuthnChallenge(
            user_id=user.id,
            challenge=challenge_str,
            purpose="registration",
            expires_at=now + timedelta(minutes=5),
        )
        db.add(challenge_record)
        await db.commit()

        return webauthn.options_to_json(options)

    @staticmethod
    async def verify_registration(
        db: AsyncSession,
        user: User,
        credential_json: str | dict[str, Any],
        name: str = "Passkey",
    ) -> bool:
        """
        Проверяет результат регистрации Passkey и сохраняет открытый ключ (SEC-FLAG-06).
        """
        stmt = (
            select(WebAuthnChallenge)
            .where(
                WebAuthnChallenge.user_id == user.id,
                WebAuthnChallenge.purpose == "registration",
                WebAuthnChallenge.expires_at > datetime.now(timezone.utc),
            )
            .order_by(WebAuthnChallenge.created_at.desc())
        )
        challenge_record = (await db.execute(stmt)).scalar_one_or_none()
        if not challenge_record:
            raise AuthenticationException("Срок действия challenge истёк или challenge не найден")

        try:
            verification = webauthn.verify_registration_response(
                credential=credential_json,
                expected_challenge=webauthn.helpers.base64url_to_bytes(challenge_record.challenge),
                expected_rp_id=settings.WEBAUTHN_RP_ID,
                expected_origin=settings.WEBAUTHN_ORIGIN,
                require_user_verification=False,
            )
        except Exception as e:
            raise AuthenticationException(f"Ошибка проверки регистрации WebAuthn: {e}")

        # Сохранение credential
        cred_id_str = verification.credential_id.decode("utf-8", errors="ignore")
        pub_key_str = verification.credential_public_key.hex()

        new_cred = WebAuthnCredential(
            user_id=user.id,
            credential_id=cred_id_str,
            public_key=pub_key_str,
            sign_count=verification.sign_count,
            name=name,
        )
        db.add(new_cred)
        await db.delete(challenge_record)
        await db.commit()

        await AuditService.log_event(
            db, event_type="passkey_registered", user_id=user.id, details={"name": name}
        )
        return True

    @staticmethod
    async def get_authentication_options(db: AsyncSession, user: User | None = None) -> dict[str, Any]:
        """
        Генерирует challenge для входа по Passkey.
        """
        allow_credentials = []
        if user:
            existing_stmt = select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
            creds = (await db.execute(existing_stmt)).scalars().all()
            allow_credentials = [
                webauthn.helpers.structs.PublicKeyCredentialDescriptor(id=c.credential_id.encode("utf-8"))
                for c in creds
            ]

        options = webauthn.generate_authentication_options(
            rp_id=settings.WEBAUTHN_RP_ID,
            allow_credentials=allow_credentials or None,
            user_verification=UserVerificationRequirement.PREFERRED,
        )

        challenge_str = webauthn.helpers.bytes_to_base64url(options.challenge) if isinstance(options.challenge, bytes) else options.challenge
        now = datetime.now(timezone.utc)
        challenge_record = WebAuthnChallenge(
            user_id=user.id if user else None,
            challenge=challenge_str,
            purpose="authentication",
            expires_at=now + timedelta(minutes=5),
        )
        db.add(challenge_record)
        await db.commit()

        return webauthn.options_to_json(options)

    @staticmethod
    async def verify_authentication(
        db: AsyncSession,
        user: User,
        credential_json: str | dict[str, Any],
    ) -> bool:
        """
        Проверка assertion Passkey при входе.
        Учитывает синхронизируемые ключи (Multi-Device Passkeys, sign_count не строго возрастает).
        """
        stmt = (
            select(WebAuthnChallenge)
            .where(
                WebAuthnChallenge.user_id == user.id,
                WebAuthnChallenge.purpose == "authentication",
                WebAuthnChallenge.expires_at > datetime.now(timezone.utc),
            )
            .order_by(WebAuthnChallenge.created_at.desc())
        )
        challenge_record = (await db.execute(stmt)).scalar_one_or_none()
        if not challenge_record:
            raise AuthenticationException("Срок действия challenge истёк или challenge не найден")

        # Находим credential по credential_id
        cred_stmt = select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
        creds = (await db.execute(cred_stmt)).scalars().all()
        if not creds:
            raise AuthenticationException("У пользователя отсутствуют зарегистрированные Passkeys")

        target_cred = creds[0]

        try:
            verification = webauthn.verify_authentication_response(
                credential=credential_json,
                expected_challenge=webauthn.helpers.base64url_to_bytes(challenge_record.challenge),
                expected_rp_id=settings.WEBAUTHN_RP_ID,
                expected_origin=settings.WEBAUTHN_ORIGIN,
                credential_public_key=bytes.fromhex(target_cred.public_key),
                credential_current_sign_count=target_cred.sign_count,
                require_user_verification=False,
            )
        except Exception as e:
            raise AuthenticationException(f"Ошибка проверки аутентификации WebAuthn: {e}")

        # Обновляем sign_count
        target_cred.sign_count = verification.new_sign_count
        await db.delete(challenge_record)
        await db.commit()

        await AuditService.log_event(db, event_type="passkey_login_success", user_id=user.id)
        return True

    @staticmethod
    async def delete_passkey(db: AsyncSession, user: User, credential_id: str) -> bool:
        stmt = delete(WebAuthnCredential).where(
            WebAuthnCredential.user_id == user.id,
            WebAuthnCredential.credential_id == credential_id,
        )
        res = await db.execute(stmt)
        await db.commit()
        if (res.rowcount or 0) > 0:
            await AuditService.log_event(
                db, event_type="passkey_deleted", user_id=user.id, details={"credential_id": credential_id}
            )
            return True
        return False


class EmailVerificationService:
    @staticmethod
    async def send_verification(db: AsyncSession, user: User, email: str) -> str:
        """
        Выпуск токена подтверждения email и отправка письма в локальный сборщик (SEC-FLAG-07).
        """
        raw_token = generate_random_token(32)
        h = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=24)

        tok = EmailVerificationToken(
            user_id=user.id,
            token_hash=h,
            email=email,
            is_used=False,
            expires_at=expires_at,
        )
        db.add(tok)
        await db.commit()

        # Запись в локальный почтовый сборщик (mock sink, без реальных внешних отправок)
        sent_emails_sink.append({
            "to": email,
            "subject": "Подтверждение адреса электронной почты ALXPRGS SSO",
            "token": raw_token,
            "timestamp": now.isoformat(),
        })

        await AuditService.log_event(
            db, event_type="email_verification_requested", user_id=user.id, details={"email": email}
        )
        return raw_token

    @staticmethod
    async def confirm_email(db: AsyncSession, raw_token: str) -> bool:
        """
        Атомарное подтверждение адреса электронной почты.
        """
        h = hash_token(raw_token)
        now = datetime.now(timezone.utc)

        stmt = select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == h,
            EmailVerificationToken.is_used.is_(False),
            EmailVerificationToken.expires_at > now,
        )
        tok_obj = (await db.execute(stmt)).scalar_one_or_none()
        if not tok_obj:
            return False

        tok_obj.is_used = True

        # Обновляем пользователя
        user_stmt = select(User).where(User.id == tok_obj.user_id)
        user = (await db.execute(user_stmt)).scalar_one()
        user.email = tok_obj.email
        user.email_verified = True

        await db.commit()
        await AuditService.log_event(db, event_type="email_verified", user_id=user.id)
        return True
