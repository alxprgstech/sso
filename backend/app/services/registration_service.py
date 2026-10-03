from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from authlib.jose import JsonWebToken
import httpx
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal import validate_versions
from app.config import Settings
from app.core.rbac import ROLE_USER
from app.core.rate_limit import check_email_request_rate_limit, check_registration_rate_limit
from app.core.security import hash_password
from app.models.audit import AuditEvent
from app.models.registration import PendingRegistration
from app.models.user import PasswordCredential, Role, User, UserRole
from app.services.audit_service import AuditService
from app.services.mfa_service import sent_emails_sink
from app.services.ses_email import SESEmailDeliveryError
from app.services.system_service import SystemService
from app.services.verification_email import (
    CODE_TTL_SECONDS,
    MAX_CODE_ATTEMPTS,
    MAX_SENDS,
    action_url,
    build_message,
    code_hash,
    code_matches,
    deliver_message,
    link_digest,
    link_url,
    new_code,
    new_link,
)


def _invalid_challenge() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "invalid_verification", "detail": "Код или ссылка недействительны"},
    )


async def verify_gmail_bearer(header: str, settings: Settings) -> None:
    if not header.startswith("Bearer ") or len(header) > 8192:
        raise HTTPException(status_code=401, detail={"error": "gmail_auth_required"})
    token = header[7:]

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get("https://www.googleapis.com/oauth2/v3/certs")
            response.raise_for_status()
            jwks = response.json()
        verifier = JsonWebToken(["RS256"])
        claims = verifier.decode(
            token,
            jwks,
            claims_option={
                "iss": {
                    "essential": True,
                    "values": ["accounts.google.com", "https://accounts.google.com"],
                },
                "aud": {"essential": True, "value": "https://alxprgs.tech"},
                "azp": {"essential": True, "value": "gmail@system.gserviceaccount.com"},
                "exp": {"essential": True},
                "iat": {"essential": True},
            },
        )
        claims.validate()
    except Exception as error:
        raise HTTPException(status_code=401, detail={"error": "gmail_auth_invalid"}) from error


class RegistrationService:
    @staticmethod
    async def start(
        db: AsyncSession,
        *,
        username: str,
        email: str,
        password: str,
        ip_address: str,
        user_agent: str | None,
        details: dict[str, str],
        settings: Settings,
        legal_versions: dict[str, str],
    ) -> PendingRegistration:

        validate_versions(legal_versions)
        if await SystemService.get_registration_mode(db) != "open":
            await AuditService.log_event(
                db,
                event_type="registration_rejected_closed",
                ip_address=ip_address,
                user_agent=user_agent,
                details={"username": username},
            )
            raise HTTPException(status_code=403, detail="Регистрация новых пользователей закрыта")
        await check_registration_rate_limit(db, ip_address)
        await check_email_request_rate_limit(db, ip_address)
        clean_username = username.strip()
        clean_email = email.strip().lower()
        await AuditService.log_event(
            db,
            event_type="registration_attempt",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        existing_user = await db.scalar(
            select(User.id).where(
                (func.lower(User.username) == clean_username.lower())
                | (func.lower(User.email) == clean_email)
            )
        )
        if existing_user:
            raise HTTPException(
                status_code=409,
                detail={"error": "user_already_exists", "detail": "Учётная запись уже существует"},
            )

        now = datetime.now(timezone.utc)
        code = new_code()
        link = new_link()
        password_digest = await asyncio.to_thread(hash_password, password)
        # The transaction-scoped lock serializes first requests for one email across workers.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:email))"), {"email": clean_email}
        )
        pending = await db.scalar(
            select(PendingRegistration)
            .where(PendingRegistration.email == clean_email)
            .with_for_update()
        )
        if pending:
            if pending.send_count >= MAX_SENDS and pending.created_at > now - timedelta(hours=1):
                await db.rollback()
                raise HTTPException(status_code=429, detail={"error": "rate_limit_exceeded"})
            pending.send_count = (
                pending.send_count + 1 if pending.created_at > now - timedelta(hours=1) else 1
            )
            pending.created_at = now
            pending.username = clean_username
            pending.password_hash = password_digest
            pending.failed_attempts = 0
        else:
            pending = PendingRegistration(
                id=uuid.uuid4(),
                username=clean_username,
                email=clean_email,
                password_hash=password_digest,
                code_hash="",
                link_hash="",
                request_details=details,
                expires_at=now,
            )
            db.add(pending)
        pending.code_hash = code_hash(settings, pending.id, code)
        pending.link_hash = link_digest(link)
        pending.request_details = details
        pending.legal_versions = legal_versions
        pending.legal_accepted_at = now
        pending.expires_at = now + timedelta(seconds=CODE_TTL_SECONDS)
        try:
            await db.commit()
        except IntegrityError as error:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"error": "user_already_exists", "detail": "Учётная запись уже существует"},
            ) from error
        await RegistrationService._send(db, pending, code, link, settings)
        return pending

    @staticmethod
    async def resend(
        db: AsyncSession,
        challenge_id: uuid.UUID,
        ip_address: str,
        settings: Settings,
    ) -> PendingRegistration:
        await check_email_request_rate_limit(db, ip_address)
        pending = await db.scalar(
            select(PendingRegistration)
            .where(PendingRegistration.id == challenge_id)
            .with_for_update()
        )
        now = datetime.now(timezone.utc)
        if not pending or pending.created_at <= now - timedelta(hours=1):
            raise _invalid_challenge()
        validate_versions(pending.legal_versions)
        if pending.send_count >= MAX_SENDS:
            raise HTTPException(status_code=429, detail={"error": "rate_limit_exceeded"})
        code, link = new_code(), new_link()
        pending.code_hash = code_hash(settings, pending.id, code)
        pending.link_hash = link_digest(link)
        pending.failed_attempts = 0
        pending.send_count += 1
        pending.expires_at = now + timedelta(seconds=CODE_TTL_SECONDS)
        await db.commit()
        await RegistrationService._send(db, pending, code, link, settings)
        return pending

    @staticmethod
    async def _send(
        db: AsyncSession,
        pending: PendingRegistration,
        code: str,
        link: str,
        settings: Settings,
    ) -> None:
        message = build_message(
            to_email=pending.email,
            username=pending.username,
            code=code,
            link=link_url(settings, link, "registration"),
            action_url=(
                action_url(settings, pending.id)
                if settings.BASE_URL.startswith("https://")
                else None
            ),
            details=pending.request_details,
            settings=settings,
        )
        if settings.ENVIRONMENT == "testing":
            sent_emails_sink.append(
                {
                    "to": pending.email,
                    "token": link,
                    "code": code,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        try:
            await deliver_message(message, settings)
        except SESEmailDeliveryError as error:
            await AuditService.log_event(
                db,
                event_type="email_delivery_failed",
                details={"provider": settings.EMAIL_PROVIDER, "reason": error.reason},
            )
            raise HTTPException(
                status_code=503, detail={"error": "email_delivery_failed"}
            ) from error
        await AuditService.log_event(
            db,
            event_type="email_verification_requested",
            ip_address=pending.request_details.get("ip"),
            details={"purpose": "registration"},
        )

    @staticmethod
    async def preview_link(db: AsyncSession, token: str) -> dict[str, str]:
        pending = await db.scalar(
            select(PendingRegistration).where(PendingRegistration.link_hash == link_digest(token))
        )
        if not pending or pending.expires_at <= datetime.now(timezone.utc):
            raise _invalid_challenge()

        validate_versions(pending.legal_versions)
        return pending.request_details

    @staticmethod
    async def confirm(
        db: AsyncSession,
        *,
        settings: Settings,
        challenge_id: uuid.UUID | None = None,
        code: str | None = None,
        link: str | None = None,
        action_id: uuid.UUID | None = None,
    ) -> User:
        if code is not None and challenge_id is not None:
            stmt = select(PendingRegistration).where(PendingRegistration.id == challenge_id)
        elif link is not None:
            stmt = select(PendingRegistration).where(
                PendingRegistration.link_hash == link_digest(link)
            )
        elif action_id is not None:
            stmt = select(PendingRegistration).where(PendingRegistration.id == action_id)
        else:
            raise _invalid_challenge()
        pending = await db.scalar(stmt.with_for_update())
        if not pending or pending.expires_at <= datetime.now(timezone.utc):
            raise _invalid_challenge()
        if code is not None:
            if pending.failed_attempts >= MAX_CODE_ATTEMPTS:
                raise _invalid_challenge()
            if not code_matches(settings, pending.id, code, pending.code_hash):
                pending.failed_attempts += 1
                await db.commit()
                raise _invalid_challenge()
        # Serializes case-insensitive username claims across self-registrations.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:username))"),
            {"username": pending.username.lower()},
        )
        existing_user = await db.scalar(
            select(User.id).where(
                (func.lower(User.username) == pending.username.lower())
                | (func.lower(User.email) == pending.email)
            )
        )
        if existing_user:
            raise HTTPException(status_code=409, detail={"error": "user_already_exists"})
        role = await db.scalar(select(Role).where(Role.name == ROLE_USER))
        if not role:
            role = Role(name=ROLE_USER, description="Стандартный пользователь экосистемы")
            db.add(role)
            await db.flush()
        user = User(
            id=uuid.uuid4(),
            username=pending.username,
            email=pending.email,
            is_active=True,
            is_superuser=False,
            email_verified=True,
        )
        db.add(user)
        await db.flush()
        from app.services.privacy_service import record_acceptance

        await record_acceptance(db, user.id, pending.legal_versions, pending.legal_accepted_at)
        db.add(PasswordCredential(user_id=user.id, password_hash=pending.password_hash))
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.add(
            AuditEvent(
                event_type="user_registered",
                user_id=user.id,
                details={"source": "verified_email"},
            )
        )
        await db.delete(pending)
        try:
            await db.commit()
        except IntegrityError as error:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"error": "user_already_exists", "detail": "Учётная запись уже существует"},
            ) from error
        return user
