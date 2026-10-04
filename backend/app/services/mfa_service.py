from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import webauthn
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import Settings, get_settings
from app.core.exceptions import (
    AuthenticationException,
)
from app.core.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_random_token,
    hash_token,
)
from app.models.mfa import (
    EmailVerificationToken,
    WebAuthnChallenge,
    WebAuthnCredential,
)
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.security_state import invalidate_security_state, lock_user, revision
from app.services.ses_email import SESEmailDeliveryError
from app.services.verification_email import (
    CODE_TTL_SECONDS,
    MAX_CODE_ATTEMPTS,
    build_message,
    code_hash,
    code_matches,
    deliver_message,
    link_url,
    new_code,
)

from app.services.totp_service import TOTPService, totp_step_usable
from app.services.recovery_codes_service import RecoveryCodesService
from app.services.webauthn_assertion import (
    AssertionPolicy,
    _cred_id_to_bytes,
    assertion_dictionary,
    locked_assertion_credential,
    signed_assertion_challenge,
    locked_assertion_challenge,
    verify_assertion_signature,
)

__all__ = [
    "TOTPService",
    "RecoveryCodesService",
    "WebAuthnService",
    "EmailVerificationService",
    "sent_emails_sink",
    "encrypt_totp_secret",
    "decrypt_totp_secret",
    "_cred_id_to_bytes",
    "totp_step_usable",
]

settings = get_settings()

# Локальный сборщик доступен только при ENVIRONMENT=testing.
sent_emails_sink: list[dict[str, Any]] = []


async def locked_registration_challenge(
    db: AsyncSession, user: User, credential_json, session_id: uuid.UUID | None
) -> WebAuthnChallenge:
    try:
        assertion = assertion_dictionary(credential_json)
        signed = signed_assertion_challenge(
            assertion, AssertionPolicy("", [], "registration", None)
        )
    except (ValueError, TypeError):
        signed = None
    if not signed:
        raise AuthenticationException("Некорректный challenge регистрации WebAuthn")
    stmt = (
        select(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.user_id == user.id,
            WebAuthnChallenge.purpose == "registration",
            WebAuthnChallenge.session_id == session_id,
            WebAuthnChallenge.challenge == signed,
            WebAuthnChallenge.expires_at > datetime.now(timezone.utc),
        )
        .order_by(WebAuthnChallenge.created_at.desc())
        .with_for_update()
    )
    challenge_record = (await db.execute(stmt)).scalars().first()
    if not challenge_record:
        raise AuthenticationException("Срок действия challenge истёк или challenge не найден")

    return challenge_record


def verify_registration_signature(
    credential_json, challenge_record: WebAuthnChallenge, policy: AssertionPolicy
):
    try:
        verification = webauthn.verify_registration_response(
            credential=credential_json,
            expected_challenge=webauthn.helpers.base64url_to_bytes(challenge_record.challenge),
            expected_rp_id=policy.rp_id,
            expected_origin=policy.origins,
            require_user_verification=True,
        )
    except Exception:
        raise AuthenticationException("Ошибка проверки регистрации WebAuthn") from None

    return verification


class WebAuthnService:
    @staticmethod
    async def get_registration_options(
        db: AsyncSession,
        user: User,
        rp_id: str | None = None,
        settings: Settings | None = None,
        session_id: uuid.UUID | None = None,
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
            session_id=session_id,
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
        session_id: uuid.UUID | None = None,
    ) -> bool:
        """
        Проверяет результат регистрации Passkey и сохраняет открытый ключ (SEC-FLAG-06, G4-PASSKEY, G6-WEBAUTHN).
        Параметры доверия (RP ID, origin, user verification) поступают строго из конфигурации сервера.
        """
        active_settings = settings or get_settings()
        user = await lock_user(db, user.id)

        challenge_record = await locked_registration_challenge(
            db, user, credential_json, session_id
        )

        effective_rp_id = rp_id or active_settings.WEBAUTHN_RP_ID
        expected_origins = [origin] if origin else [active_settings.WEBAUTHN_ORIGIN]

        policy = AssertionPolicy(effective_rp_id, expected_origins, "registration", None)
        verification = verify_registration_signature(credential_json, challenge_record, policy)

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
        await invalidate_security_state(db, user, preserve_session_id=session_id)
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
        *,
        purpose: str = "authentication",
        commit: bool = True,
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
            purpose=purpose,
            expires_at=now + timedelta(minutes=5),
        )
        db.add(challenge_record)
        await db.flush()
        if commit:
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
        *,
        purpose: str = "authentication",
        expected_challenge: str | None = None,
        commit: bool = True,
    ) -> bool:
        """Verify the exact server trust policy, lock and consume the assertion once."""
        active_settings = settings or get_settings()
        user = await lock_user(db, user.id)
        if not user.is_active:
            raise AuthenticationException("Аккаунт недоступен")
        policy = AssertionPolicy(
            rp_id or active_settings.WEBAUTHN_RP_ID,
            [origin] if origin else [active_settings.WEBAUTHN_ORIGIN],
            purpose,
            expected_challenge,
        )
        assertion = assertion_dictionary(credential_json)
        target = await locked_assertion_credential(db, user.id, assertion)
        challenge = await locked_assertion_challenge(db, user.id, assertion, policy)
        target.sign_count = verify_assertion_signature(credential_json, target, challenge, policy)
        await db.delete(challenge)
        from app.models.audit import AuditEvent

        db.add(
            AuditEvent(
                event_type="passkey_login_success"
                if purpose == "authentication"
                else "deletion_factor_verified",
                user_id=user.id,
                details={},
            )
        )
        await db.flush()
        if commit:
            await db.commit()
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
    async def delete_passkey(
        db: AsyncSession, user: User, credential_id: str, session_id: uuid.UUID | None = None
    ) -> bool:
        user = await lock_user(db, user.id)
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
        await invalidate_security_state(db, user, preserve_session_id=session_id)
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
    async def send_verification(
        db: AsyncSession,
        user: User,
        email: str,
        settings: Settings | None = None,
        details: dict[str, str] | None = None,
    ) -> str:
        """Send a six-digit code and an independent one-use link for an existing user."""
        active_settings = settings or get_settings()
        user = await lock_user(db, user.id)
        if not user.is_active:
            raise AuthenticationException("Аккаунт недоступен")
        await db.execute(
            delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        )
        raw_token = generate_random_token(32)
        code = new_code()
        now = datetime.now(timezone.utc)
        tok = EmailVerificationToken(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=hash_token(raw_token),
            email=email,
            is_used=False,
            expires_at=now + timedelta(seconds=CODE_TTL_SECONDS),
            security_revision=revision(user),
        )
        tok.code_hash = code_hash(active_settings, tok.id, code)
        db.add(tok)
        await db.commit()
        message = build_message(
            to_email=email,
            username=user.username,
            code=code,
            link=link_url(active_settings, raw_token, "existing"),
            action_url=None,
            details=details or {},
            settings=active_settings,
        )
        if active_settings.ENVIRONMENT == "testing":
            sent_emails_sink.append(
                {
                    "to": email,
                    "subject": str(message["Subject"]),
                    "token": raw_token,
                    "code": code,
                    "challenge_id": str(tok.id),
                    "timestamp": now.isoformat(),
                }
            )
        try:
            await deliver_message(message, active_settings)
        except SESEmailDeliveryError as error:
            from app.telemetry import capture_infrastructure_failure

            capture_infrastructure_failure(error, "email_delivery")
            await AuditService.log_event(
                db,
                event_type="email_delivery_failed",
                user_id=user.id,
                details={"reason": error.reason, "provider": active_settings.EMAIL_PROVIDER},
            )
        await AuditService.log_event(db, event_type="email_verification_requested", user_id=user.id)
        return raw_token

    @staticmethod
    async def confirm_email(db: AsyncSession, raw_token: str) -> bool:
        owner = await db.scalar(
            select(EmailVerificationToken.user_id).where(
                EmailVerificationToken.token_hash == hash_token(raw_token)
            )
        )
        if owner is None:
            return False
        await lock_user(db, owner)
        tok = await db.scalar(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.token_hash == hash_token(raw_token))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if tok and tok.is_used:
            await AuditService.log_event(
                db, event_type="email_verification_replay_detected", user_id=tok.user_id
            )
            return False
        if tok and tok.expires_at <= datetime.now(timezone.utc):
            await AuditService.log_event(
                db, event_type="email_verification_expired", user_id=tok.user_id
            )
            return False
        return await EmailVerificationService._consume(db, tok)

    @staticmethod
    async def confirm_code(db: AsyncSession, email: str, code: str, settings: Settings) -> bool:
        candidate = await db.scalar(
            select(EmailVerificationToken)
            .where(
                EmailVerificationToken.email == email.strip().lower(),
                EmailVerificationToken.is_used.is_(False),
            )
            .order_by(EmailVerificationToken.created_at.desc())
            .limit(1)
        )
        if candidate is None:
            return False
        await lock_user(db, candidate.user_id)
        tok = await db.scalar(
            select(EmailVerificationToken)
            .where(
                EmailVerificationToken.email == email.strip().lower(),
                EmailVerificationToken.is_used.is_(False),
            )
            .order_by(EmailVerificationToken.created_at.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not tok or tok.is_used or tok.expires_at <= datetime.now(timezone.utc):
            return False
        if not tok.code_hash or tok.failed_attempts >= MAX_CODE_ATTEMPTS:
            return False
        if not code_matches(settings, tok.id, code, tok.code_hash):
            tok.failed_attempts += 1
            await db.commit()
            return False
        return await EmailVerificationService._consume(db, tok)

    @staticmethod
    async def _consume(db: AsyncSession, tok: EmailVerificationToken | None) -> bool:
        if not tok or tok.is_used or tok.expires_at <= datetime.now(timezone.utc):
            return False
        user = await lock_user(db, tok.user_id)
        if not user.is_active or tok.security_revision != revision(user):
            return False
        tok.is_used = True
        user.email = tok.email
        user.email_verified = True
        try:
            await db.flush()
            await invalidate_security_state(db, user, preserve_email_token_id=tok.id)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return False
        await AuditService.log_event(db, event_type="email_verified", user_id=user.id)
        return True
