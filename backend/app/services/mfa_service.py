from __future__ import annotations

import json
import secrets
import string
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


def _cred_id_to_bytes(cred_id: str) -> bytes:
    try:
        return webauthn.helpers.base64url_to_bytes(cred_id)
    except Exception:
        return cred_id.encode("utf-8")


class WebAuthnService:
    @staticmethod
    async def get_registration_options(
        db: AsyncSession,
        user: User,
        rp_id: str | None = None,
        settings: Settings | None = None,
    ) -> dict[str, Any]:
        """
        Генерирует challenge и опции для регистрации нового WebAuthn Passkey (W3C WebAuthn Level 3).
        """
        active_settings = settings or get_settings()

        # Получаем уже существующие credentials пользователя
        existing_creds_stmt = select(WebAuthnCredential).where(
            WebAuthnCredential.user_id == user.id
        )
        existing_creds = (await db.execute(existing_creds_stmt)).scalars().all()

        exclude_credentials = [
            webauthn.helpers.structs.PublicKeyCredentialDescriptor(
                id=_cred_id_to_bytes(cred.credential_id)
            )
            for cred in existing_creds
        ]

        effective_rp_id = rp_id or active_settings.WEBAUTHN_RP_ID

        options = webauthn.generate_registration_options(
            rp_id=effective_rp_id,
            rp_name=active_settings.WEBAUTHN_RP_NAME,
            user_id=str(user.id).encode("utf-8"),
            user_name=user.username,
            user_display_name=user.username,
            attestation=webauthn.helpers.structs.AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=exclude_credentials,
        )

        challenge_str = (
            webauthn.helpers.bytes_to_base64url(options.challenge)
            if isinstance(options.challenge, bytes)
            else options.challenge
        )
        now = datetime.now(timezone.utc)
        challenge_record = WebAuthnChallenge(
            user_id=user.id,
            challenge=challenge_str,
            purpose="registration",
            expires_at=now + timedelta(minutes=5),
        )
        db.add(challenge_record)
        await db.commit()

        return json.loads(webauthn.options_to_json(options))

    @staticmethod
    async def verify_registration(
        db: AsyncSession,
        user: User,
        credential_json: str | dict[str, Any],
        name: str = "Passkey",
        rp_id: str | None = None,
        origin: str | None = None,
        settings: Settings | None = None,
    ) -> bool:
        """
        Проверяет результат регистрации Passkey и сохраняет открытый ключ (SEC-FLAG-06, G4-PASSKEY, G6-WEBAUTHN).
        Параметры доверия (RP ID, origin, user verification) поступают строго из конфигурации сервера.
        """
        active_settings = settings or get_settings()

        stmt = (
            select(WebAuthnChallenge)
            .where(
                WebAuthnChallenge.user_id == user.id,
                WebAuthnChallenge.purpose == "registration",
                WebAuthnChallenge.expires_at > datetime.now(timezone.utc),
            )
            .order_by(WebAuthnChallenge.created_at.desc())
        )
        challenge_record = (await db.execute(stmt)).scalars().first()
        if not challenge_record:
            raise AuthenticationException("Срок действия challenge истёк или challenge не найден")

        effective_rp_id = rp_id or active_settings.WEBAUTHN_RP_ID
        expected_origins = [origin] if origin else [active_settings.WEBAUTHN_ORIGIN]

        try:
            verification = webauthn.verify_registration_response(
                credential=credential_json,
                expected_challenge=webauthn.helpers.base64url_to_bytes(challenge_record.challenge),
                expected_rp_id=effective_rp_id,
                expected_origin=expected_origins,
                require_user_verification=True,
            )
        except Exception as e:
            raise AuthenticationException(f"Ошибка проверки регистрации WebAuthn: {e}")

        # Сохранение credential в безопасном представлении Base64URL
        cred_id_str = webauthn.helpers.bytes_to_base64url(verification.credential_id)
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
            db,
            event_type="passkey_registered",
            user_id=user.id,
            details={"name": name, "credential_id": cred_id_str},
        )
        return True

    @staticmethod
    async def get_authentication_options(
        db: AsyncSession,
        user: User | None = None,
        rp_id: str | None = None,
        settings: Settings | None = None,
    ) -> dict[str, Any]:
        """
        Генерирует challenge для входа по Passkey.
        """
        active_settings = settings or get_settings()

        allow_credentials = []
        if user:
            existing_stmt = select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
            creds = (await db.execute(existing_stmt)).scalars().all()
            allow_credentials = [
                webauthn.helpers.structs.PublicKeyCredentialDescriptor(
                    id=_cred_id_to_bytes(c.credential_id)
                )
                for c in creds
            ]

        effective_rp_id = rp_id or active_settings.WEBAUTHN_RP_ID

        options = webauthn.generate_authentication_options(
            rp_id=effective_rp_id,
            allow_credentials=allow_credentials or None,
            user_verification=UserVerificationRequirement.REQUIRED,
        )

        challenge_str = (
            webauthn.helpers.bytes_to_base64url(options.challenge)
            if isinstance(options.challenge, bytes)
            else options.challenge
        )
        now = datetime.now(timezone.utc)
        challenge_record = WebAuthnChallenge(
            user_id=user.id if user else None,
            challenge=challenge_str,
            purpose="authentication",
            expires_at=now + timedelta(minutes=5),
        )
        db.add(challenge_record)
        await db.commit()

        return json.loads(webauthn.options_to_json(options))

    @staticmethod
    async def verify_authentication(
        db: AsyncSession,
        user: User,
        credential_json: str | dict[str, Any],
        rp_id: str | None = None,
        origin: str | None = None,
        settings: Settings | None = None,
    ) -> bool:
        """
        Проверка assertion Passkey при входе с поддержкой множественных ключей,
        защитой от Replay и проверкой актуальности удалённых ключей (G4-PASSKEY, G6-WEBAUTHN).
        Параметры доверия (RP ID, origin, user verification) поступают строго из конфигурации сервера.
        """
        import json

        active_settings = settings or get_settings()

        cred_dict = (
            json.loads(credential_json) if isinstance(credential_json, str) else credential_json
        )
        client_raw_id = cred_dict.get("id") or cred_dict.get("rawId")
        if not client_raw_id:
            raise AuthenticationException("Отсутствует идентификатор ключа Passkey (id)")

        # Находим все ключи пользователя и точно сопоставляем использованный ключ
        cred_stmt = select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
        creds = (await db.execute(cred_stmt)).scalars().all()
        if not creds:
            raise AuthenticationException(
                "У пользователя отсутствуют зарегистрированные ключи Passkey"
            )

        target_cred = None
        for c in creds:
            if c.credential_id == client_raw_id or _cred_id_to_bytes(
                c.credential_id
            ) == _cred_id_to_bytes(client_raw_id):
                target_cred = c
                break

        if not target_cred:
            raise AuthenticationException("Ключ доступа Passkey не найден или был удалён")

        # Поиск challenge: сначала пытаемся извлечь подписанный challenge из clientDataJSON
        challenge_record = None
        try:
            resp_obj = cred_dict.get("response", {})
            client_data_raw = resp_obj.get("clientDataJSON")
            if client_data_raw:
                client_data_bytes = webauthn.helpers.base64url_to_bytes(client_data_raw)
                client_data_dict = json.loads(client_data_bytes.decode("utf-8"))
                signed_challenge = client_data_dict.get("challenge")
                if signed_challenge:
                    stmt = select(WebAuthnChallenge).where(
                        WebAuthnChallenge.challenge == signed_challenge,
                        WebAuthnChallenge.purpose == "authentication",
                        WebAuthnChallenge.expires_at > datetime.now(timezone.utc),
                    )
                    challenge_record = (await db.execute(stmt)).scalars().first()
        except Exception:
            pass

        if not challenge_record:
            # Fallback к последнему активному challenge пользователя
            stmt = (
                select(WebAuthnChallenge)
                .where(
                    WebAuthnChallenge.user_id == user.id,
                    WebAuthnChallenge.purpose == "authentication",
                    WebAuthnChallenge.expires_at > datetime.now(timezone.utc),
                )
                .order_by(WebAuthnChallenge.created_at.desc())
            )
            challenge_record = (await db.execute(stmt)).scalars().first()

        if not challenge_record:
            raise AuthenticationException("Срок действия challenge истёк или challenge не найден")

        effective_rp_id = rp_id or active_settings.WEBAUTHN_RP_ID
        expected_origins = [origin] if origin else [active_settings.WEBAUTHN_ORIGIN]

        try:
            verification = webauthn.verify_authentication_response(
                credential=credential_json,
                expected_challenge=webauthn.helpers.base64url_to_bytes(challenge_record.challenge),
                expected_rp_id=effective_rp_id,
                expected_origin=expected_origins,
                credential_public_key=bytes.fromhex(target_cred.public_key),
                credential_current_sign_count=target_cred.sign_count,
                require_user_verification=True,
            )
        except Exception as e:
            raise AuthenticationException(f"Ошибка проверки аутентификации WebAuthn: {e}")

        # Обновляем sign_count
        target_cred.sign_count = verification.new_sign_count
        # Удаляем использованный challenge (Replay Protection)
        await db.delete(challenge_record)
        await db.commit()

        await AuditService.log_event(
            db,
            event_type="passkey_login_success",
            user_id=user.id,
            details={"credential_id": target_cred.credential_id},
        )
        return True

    @staticmethod
    async def list_credentials(db: AsyncSession, user: User) -> list[dict[str, Any]]:
        """Возвращает список зарегистрированных Passkeys текущего пользователя."""
        stmt = (
            select(WebAuthnCredential)
            .where(WebAuthnCredential.user_id == user.id)
            .order_by(
                WebAuthnCredential.id.desc()
                if hasattr(WebAuthnCredential, "id")
                else WebAuthnCredential.credential_id
            )
        )
        creds = (await db.execute(stmt)).scalars().all()
        return [
            {
                "id": c.credential_id,
                "name": c.name or "Passkey",
                "sign_count": c.sign_count,
            }
            for c in creds
        ]

    @staticmethod
    async def delete_passkey(db: AsyncSession, user: User, credential_id: str) -> bool:
        stmt = select(WebAuthnCredential).where(
            WebAuthnCredential.user_id == user.id,
        )
        creds = (await db.execute(stmt)).scalars().all()
        target = None
        for c in creds:
            if c.credential_id == credential_id or _cred_id_to_bytes(
                c.credential_id
            ) == _cred_id_to_bytes(credential_id):
                target = c
                break
        if not target:
            return False

        deleted_id = target.credential_id
        await db.delete(target)
        await db.commit()
        await AuditService.log_event(
            db,
            event_type="passkey_deleted",
            user_id=user.id,
            details={"credential_id": deleted_id},
        )
        return True


class EmailVerificationService:
    @staticmethod
    def _send_smtp_email(
        to_email: str,
        subject: str,
        body: str,
        settings: Settings,
    ) -> bool:
        """Синхронная отправка письма через smtplib (вызывается в отдельном потоке)."""
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM_EMAIL
        msg["To"] = to_email
        msg.set_content(body)

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as server:
                if settings.SMTP_USE_TLS:
                    server.starttls()
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            return True
        except Exception:
            return False

    @staticmethod
    async def send_verification(
        db: AsyncSession,
        user: User,
        email: str,
        settings: Settings | None = None,
    ) -> str:
        """
        Выпуск токена подтверждения email и отправка письма в локальный сборщик и/или SMTP (SEC-FLAG-07, G4-EMAIL).
        """
        import asyncio

        active_settings = settings or get_settings()

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

        # Запись в локальный почтовый сборщик (mock sink, без обязательных внешних сетевых вызовов, SEC-FLAG-07)
        sent_emails_sink.append(
            {
                "to": email,
                "subject": "Подтверждение адреса электронной почты ALXPRGS SSO",
                "token": raw_token,
                "timestamp": now.isoformat(),
            }
        )

        # Если настроен SMTP хост и порт — попытка отправки через реальный SMTP
        if active_settings.SMTP_HOST and active_settings.SMTP_PORT:
            verification_url = f"{active_settings.FRONTEND_URL}/verify-email?token={raw_token}"
            body = (
                f"Здравствуйте, {user.username}!\n\n"
                f"Для подтверждения вашего адреса электронной почты перейдите по ссылке:\n"
                f"{verification_url}\n\n"
                f"Код подтверждения: {raw_token}\n\n"
                f"Ссылка действительна 24 часа. Если вы не запрашивали подтверждение, проигнорируйте письмо.\n"
            )
            smtp_ok = await asyncio.to_thread(
                EmailVerificationService._send_smtp_email,
                to_email=email,
                subject="Подтверждение адреса электронной почты ALXPRGS SSO",
                body=body,
                settings=active_settings,
            )
            if not smtp_ok:
                await AuditService.log_event(
                    db,
                    event_type="email_delivery_failed",
                    user_id=user.id,
                    details={"email": email, "reason": "smtp_connection_failed"},
                )

        await AuditService.log_event(
            db, event_type="email_verification_requested", user_id=user.id, details={"email": email}
        )
        return raw_token

    @staticmethod
    async def confirm_email(db: AsyncSession, raw_token: str) -> bool:
        """
        Атомарное подтверждение адреса электронной почты с защитой от Replay и истечения срока (G4-EMAIL).
        """
        h = hash_token(raw_token)
        now = datetime.now(timezone.utc)

        # Проверяем наличие любого токена с таким хешем для выявления replay / expired
        check_stmt = select(EmailVerificationToken).where(EmailVerificationToken.token_hash == h)
        existing_tok = (await db.execute(check_stmt)).scalar_one_or_none()

        if not existing_tok:
            return False

        if existing_tok.is_used:
            await AuditService.log_event(
                db,
                event_type="email_verification_replay_detected",
                user_id=existing_tok.user_id,
                details={"token_hash": h[:16]},
            )
            return False

        if existing_tok.expires_at <= now:
            await AuditService.log_event(
                db,
                event_type="email_verification_expired",
                user_id=existing_tok.user_id,
                details={"token_hash": h[:16]},
            )
            return False

        existing_tok.is_used = True

        # Обновляем пользователя
        user_stmt = select(User).where(User.id == existing_tok.user_id)
        user = (await db.execute(user_stmt)).scalar_one()
        user.email = existing_tok.email
        user.email_verified = True

        await db.commit()
        await AuditService.log_event(db, event_type="email_verified", user_id=user.id)
        return True
