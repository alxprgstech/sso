"""Consent and erasure scenarios. Callers own the final transaction boundary."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.security import async_verify_password, generate_random_token, hash_token
from app.legal import REQUIRED_DOCUMENTS, validate_versions
from app.models.audit import AuditEvent
from app.models.mfa import EmailVerificationToken, RecoveryCode, WebAuthnChallenge
from app.models.oidc import AuthorizationCode, RefreshToken
from app.models.privacy import (
    DeletedSubject,
    DeletionAuthorization,
    LegalAcceptance,
    PrivacyRateWindow,
)
from app.models.registration import PendingRegistration
from app.models.session import Session
from app.models.user import User

GRACE = timedelta(days=14)
COOLDOWN = timedelta(days=7)
AUTHORIZATION_TTL = timedelta(minutes=5)
logger = logging.getLogger(__name__)


def rejection(error: str, detail: str, status: int = 409) -> HTTPException:
    return HTTPException(status, detail={"error": error, "detail": detail})


async def database_now(db: AsyncSession) -> datetime:
    return (await db.execute(select(func.clock_timestamp()))).scalar_one()


@dataclass(frozen=True)
class RateLimit:
    bucket: str
    identity: str
    limit: int
    seconds: int = 60


@dataclass(frozen=True)
class DeletionContext:
    db: AsyncSession
    user: User
    session: Session
    settings: Settings


@dataclass(frozen=True)
class AuthorizationScope:
    user_id: uuid.UUID
    session_id: uuid.UUID


@dataclass(frozen=True)
class ActionProof:
    token: str
    action: str


@dataclass(frozen=True)
class FactorEvidence:
    method: str
    code: str | None = None
    credential: dict[str, Any] | None = None


async def consume_rate_limit(db: AsyncSession, settings: Settings, policy: RateLimit) -> None:
    """Atomic sliding expiration shared across instances; never retains a raw IP."""
    digest = hmac.new(
        settings.SESSION_SECRET_KEY.encode(),
        f"privacy:{policy.bucket}:{policy.identity}".encode(),
        hashlib.sha256,
    ).hexdigest()
    try:
        now = await database_now(db)
        stmt = insert(PrivacyRateWindow).values(
            id=uuid.uuid4(),
            created_at=now,
            key_hash=digest,
            attempts=1,
            expires_at=now + timedelta(seconds=policy.seconds),
        )
        counted = stmt.on_conflict_do_update(
            index_elements=[PrivacyRateWindow.key_hash],
            set_={
                "attempts": text(
                    "CASE WHEN privacy_rate_windows.expires_at <= clock_timestamp() THEN 1 ELSE privacy_rate_windows.attempts + 1 END"
                ),
                "expires_at": text(
                    f"CASE WHEN privacy_rate_windows.expires_at <= clock_timestamp() THEN clock_timestamp() + interval '{policy.seconds} seconds' ELSE privacy_rate_windows.expires_at END"
                ),
            },
        ).returning(PrivacyRateWindow.attempts)
        attempts = (await db.execute(counted)).scalar_one()
        # Persist attempts even when a later password/consent validation fails.
        await db.commit()
    except Exception as error:
        try:
            await db.rollback()
        except Exception:
            logger.error("privacy_rate_limit_rollback_failed")
        raise rejection(
            "service_unavailable", "Не удалось проверить лимиты безопасности.", 503
        ) from error
    if attempts > policy.limit:
        raise rejection(
            "rate_limit_exceeded", "Слишком много запросов. Повторите через минуту.", 429
        )


async def has_current_acceptance(db: AsyncSession, user_id: uuid.UUID) -> bool:
    rows = (
        await db.execute(
            select(LegalAcceptance.document_id, LegalAcceptance.version).where(
                LegalAcceptance.user_id == user_id
            )
        )
    ).all()
    return all((document, version) in rows for document, version in REQUIRED_DOCUMENTS.items())


async def record_acceptance(
    db: AsyncSession, user_id: uuid.UUID, versions: dict[str, str], accepted_at: datetime
) -> None:
    validate_versions(versions)
    for document, version in versions.items():
        await db.execute(
            insert(LegalAcceptance)
            .values(
                id=uuid.uuid4(),
                created_at=accepted_at,
                user_id=user_id,
                document_id=document,
                version=version,
                accepted_at=accepted_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    LegalAcceptance.user_id,
                    LegalAcceptance.document_id,
                    LegalAcceptance.version,
                ]
            )
        )


async def require_access(db: AsyncSession, user: User) -> None:
    if user.deletion_scheduled_for:
        raise rejection("account_deletion_pending", "Аккаунт ожидает удаления.", 403)
    if not await has_current_acceptance(db, user.id):
        raise rejection("legal_acceptance_required", "Подтвердите актуальные документы.", 403)


def deletion_status(user: User) -> dict[str, Any]:
    return {
        "pending": bool(user.deletion_scheduled_for),
        "requested_at": user.deletion_requested_at,
        "scheduled_for": user.deletion_scheduled_for,
        "request_allowed_at": user.deletion_request_allowed_at,
    }


def require_enabled_factor(required: bool, enabled: bool) -> None:
    if not required:
        return
    if not enabled:
        raise rejection(
            "required_factor_disabled",
            "Обязательный фактор отключён. Обратитесь к администратору.",
            403,
        )


def factor_methods(user: User, settings: Settings) -> list[str]:
    totp = bool(user.totp_credential and user.totp_credential.is_confirmed)
    passkey = bool(user.webauthn_credentials)
    require_enabled_factor(totp, settings.FEATURE_TOTP_ENABLED)
    require_enabled_factor(passkey, settings.FEATURE_PASSKEY_ENABLED)
    methods = []
    if totp:
        methods.append("totp")
        if settings.FEATURE_RECOVERY_CODES_ENABLED:
            methods.append("recovery_code")
    if passkey:
        methods.append("passkey")
    return methods


async def lock_active_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    current = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None:
        raise rejection("invalid_credentials", "Аккаунт недоступен.", 401)
    if not current.is_active:
        raise rejection("invalid_credentials", "Аккаунт недоступен.", 401)
    return current


async def verify_reauthentication(context: DeletionContext, password: str) -> User:
    # Account lock precedes proof issuance and competes with erasure/request.
    user = await lock_active_user(context.db, context.user.id)
    valid_session = await context.db.scalar(
        select(Session.id).where(
            Session.id == context.session.id,
            Session.user_id == user.id,
            Session.expires_at > func.clock_timestamp(),
        )
    )
    if not valid_session:
        raise rejection("invalid_credentials", "Сессия недоступна.", 401)
    await verify_deletion_password(user, password, context.settings)
    return user


async def verify_deletion_password(user: User, password: str, settings: Settings) -> None:
    if settings.REQUIRE_VERIFIED_EMAIL and not user.email_verified:
        raise rejection("email_verification_required", "Необходимо подтвердить email.", 403)
    credential = user.password_credential
    if credential is None:
        raise rejection("invalid_credentials", "Неверный пароль.", 401)
    if not await async_verify_password(password, credential.password_hash):
        raise rejection("invalid_credentials", "Неверный пароль.", 401)


def require_cancellable(user: User, now: datetime) -> None:
    deadline = user.deletion_scheduled_for
    if deadline is None:
        raise rejection("deletion_not_cancellable", "Заявка отсутствует.")
    if now >= deadline:
        raise rejection("deletion_not_cancellable", "Срок отмены истёк.")


def require_no_cooldown(user: User, now: datetime) -> None:
    allowed_at = user.deletion_request_allowed_at
    if allowed_at is None:
        return
    if now < allowed_at:
        raise rejection("deletion_cooldown", "Повторная заявка доступна после указанной даты.", 429)


def require_available_action(user: User, action: str, now: datetime) -> None:
    if action == "cancel":
        require_cancellable(user, now)
    elif action == "request":
        require_no_cooldown(user, now)
    else:
        raise rejection("invalid_deletion_action", "Неизвестное действие.", 400)


async def deletion_passkey_options(
    context: DeletionContext, proof: DeletionAuthorization
) -> dict[str, Any]:
    from app.services.mfa_service import WebAuthnService

    options = await WebAuthnService.get_authentication_options(
        context.db,
        context.user,
        settings=context.settings,
        purpose=f"deletion_{proof.action}",
        commit=False,
    )
    proof.webauthn_challenge = options["challenge"]
    return options


async def start_reauthentication(
    context: DeletionContext, action: str, password: str
) -> dict[str, Any]:
    db = context.db
    await consume_rate_limit(
        db, context.settings, RateLimit("deletion-reauth", str(context.user.id), 5)
    )
    user = await verify_reauthentication(context, password)
    methods = factor_methods(user, context.settings)
    now = await database_now(db)
    require_available_action(user, action, now)
    raw = generate_random_token(32)
    authorization = DeletionAuthorization(
        user_id=user.id,
        session_id=context.session.id,
        action=action,
        token_hash=hash_token(raw),
        expires_at=now + AUTHORIZATION_TTL,
        stage="factor" if methods else "authorized",
        failed_attempts=0,
    )
    db.add(authorization)
    options = None
    if "passkey" in methods:
        options = await deletion_passkey_options(context, authorization)
    await db.commit()
    return {
        "authorization": raw,
        "factor_required": bool(methods),
        "methods": methods,
        "passkey_options": options,
        "expires_at": authorization.expires_at,
    }


def valid_authorization(row: DeletionAuthorization, stage: str, now: datetime) -> bool:
    if row.stage != stage:
        return False
    if row.expires_at <= now:
        return False
    return row.failed_attempts < 5


async def authorization_row(
    db: AsyncSession, scope: AuthorizationScope, proof: ActionProof, stage: str
) -> DeletionAuthorization:
    row = await db.scalar(
        select(DeletionAuthorization)
        .where(
            DeletionAuthorization.token_hash == hash_token(proof.token),
            DeletionAuthorization.user_id == scope.user_id,
            DeletionAuthorization.session_id == scope.session_id,
            DeletionAuthorization.action == proof.action,
        )
        .with_for_update()
    )
    if row is not None:
        if valid_authorization(row, stage, await database_now(db)):
            return row
    raise rejection(
        "invalid_deletion_authorization",
        "Подтверждение истекло, уже использовано или недействительно.",
        401,
    )


async def consume_deletion_recovery_code(context: DeletionContext, code: str) -> bool:
    from app.services.mfa_service import RecoveryCodesService

    digest = hash_token(RecoveryCodesService._normalize_code(code))
    consumed = await context.db.scalar(
        update(RecoveryCode)
        .where(
            RecoveryCode.user_id == context.user.id,
            RecoveryCode.code_hash == digest,
            RecoveryCode.is_used.is_(False),
        )
        .values(is_used=True, used_at=await database_now(context.db))
        .returning(RecoveryCode.id)
    )
    return consumed is not None


async def verify_deletion_factor(
    context: DeletionContext, row: DeletionAuthorization, evidence: FactorEvidence
) -> bool:
    from app.services.mfa_service import TOTPService, WebAuthnService

    if evidence.method not in factor_methods(context.user, context.settings):
        return False
    if evidence.method == "passkey":
        if not evidence.credential:
            return False
        return await WebAuthnService.verify_authentication(
            context.db,
            context.user,
            evidence.credential,
            settings=context.settings,
            purpose=f"deletion_{row.action}",
            expected_challenge=row.webauthn_challenge,
            commit=False,
        )
    if not evidence.code:
        return False
    if evidence.method == "totp":
        return await TOTPService.verify_totp(context.db, context.user, evidence.code, commit=False)
    return await consume_deletion_recovery_code(context, evidence.code)


async def confirm_factor(
    context: DeletionContext, proof: ActionProof, evidence: FactorEvidence
) -> dict[str, Any]:
    db = context.db
    await consume_rate_limit(
        db, context.settings, RateLimit("deletion-factor", str(context.user.id), 5)
    )
    scope = AuthorizationScope(context.user.id, context.session.id)
    row = await authorization_row(db, scope, proof, "factor")
    # Disabled required factors must raise 403 rather than become an invalid code.
    factor_methods(context.user, context.settings)
    try:
        valid = await verify_deletion_factor(context, row, evidence)
    except HTTPException:
        valid = False
    if not valid:
        row.failed_attempts += 1
        await db.commit()
        raise rejection("invalid_factor", "Второй фактор не прошёл проверку.", 401)
    row.stage = "authorized"
    # Rotate the secret: factor-step tokens cannot authorize erasure/cancellation.
    authorized = generate_random_token(32)
    row.token_hash = hash_token(authorized)
    await db.commit()
    return {"authorization": authorized, "factor_required": False, "expires_at": row.expires_at}


async def request_deletion(
    db: AsyncSession, user: User, session: Session, raw: str
) -> tuple[dict[str, Any], str]:
    from app.core.rbac import ensure_not_last_admin, lock_admin_invariant

    await lock_admin_invariant(db)
    locked = await lock_active_user(db, user.id)
    await authorization_row(
        db, AuthorizationScope(user.id, session.id), ActionProof(raw, "request"), "authorized"
    )
    now = await database_now(db)
    if locked.deletion_scheduled_for:
        raise rejection("deletion_already_pending", "Удаление уже запланировано; срок не изменён.")
    require_no_cooldown(locked, now)
    await ensure_not_last_admin(db, user.id)
    locked.deletion_requested_at = now
    locked.deletion_scheduled_for = now + GRACE
    from app.services.security_state import invalidate_security_state, revision

    await invalidate_security_state(db, locked)
    restricted_raw = generate_random_token(32)
    restricted = Session(
        user_id=user.id,
        session_token_hash=hash_token(restricted_raw),
        purpose="deletion_management",
        security_revision=revision(locked),
        expires_at=now + timedelta(hours=1),
        last_activity_at=now,
    )
    db.add(restricted)
    db.add(AuditEvent(event_type="account_deletion_requested", user_id=user.id, details={}))
    result = deletion_status(locked)
    await db.commit()
    return result, restricted_raw


async def cancel_deletion(
    db: AsyncSession, user: User, session: Session, raw: str
) -> dict[str, Any]:
    from app.core.rbac import lock_admin_invariant

    await lock_admin_invariant(db)
    locked = await lock_active_user(db, user.id)
    await authorization_row(
        db, AuthorizationScope(user.id, session.id), ActionProof(raw, "cancel"), "authorized"
    )
    now = await database_now(db)
    require_cancellable(locked, now)
    locked.deletion_requested_at = None
    locked.deletion_scheduled_for = None
    locked.deletion_request_allowed_at = now + COOLDOWN
    # Force a new login; never promote a restricted session or revive old tokens.
    from app.services.security_state import invalidate_security_state

    await invalidate_security_state(db, locked)
    db.add(AuditEvent(event_type="account_deletion_cancelled", user_id=user.id, details={}))
    result = deletion_status(locked)
    await db.commit()
    return result


async def erase_subject(db: AsyncSession, user: User, now: datetime) -> None:
    audit_rows = (
        (
            await db.execute(
                select(AuditEvent)
                .where(
                    or_(
                        AuditEvent.user_id == user.id,
                        AuditEvent.details["target_user_id"].as_string() == str(user.id),
                        AuditEvent.details["created_user_id"].as_string() == str(user.id),
                        AuditEvent.details["identifier"]
                        .as_string()
                        .in_([user.username, user.email]),
                        AuditEvent.details["username"].as_string() == user.username,
                    )
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for event in audit_rows:
        event.user_id = None
        event.ip_address = None
        event.user_agent = None
        event.details = {}
    await db.execute(
        delete(PendingRegistration).where(
            or_(
                func.lower(PendingRegistration.email) == user.email.lower(),
                func.lower(PendingRegistration.username) == user.username.lower(),
            )
        )
    )
    await db.execute(
        insert(DeletedSubject)
        .values(id=uuid.uuid4(), created_at=now, subject_id=user.id, deleted_at=now)
        .on_conflict_do_nothing(index_elements=[DeletedSubject.subject_id])
    )
    # SQL delete delegates every credential/session/consent cascade to PostgreSQL.
    await db.execute(delete(User).where(User.id == user.id))
    db.add(
        AuditEvent(
            event_type="account_deleted", user_id=None, ip_address=None, user_agent=None, details={}
        )
    )


async def maintenance(db: AsyncSession, settings: Settings) -> int:
    from app.core.rbac import lock_admin_invariant

    # One owner, nonblocking, and the same admin lock as all destructive role changes.
    if not await db.scalar(text("SELECT pg_try_advisory_xact_lock(1129466198)")):
        return 0
    await lock_admin_invariant(db)
    now = await database_now(db)
    due = (
        (
            await db.execute(
                select(User)
                .where(User.deletion_scheduled_for <= now)
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    for user in due:
        await erase_subject(db, user, now)
    await db.execute(delete(AuditEvent).where(AuditEvent.created_at <= now - timedelta(days=90)))
    # Registration resend quotas last one hour; cleanup cannot erase that window.
    await db.execute(
        delete(PendingRegistration).where(
            PendingRegistration.expires_at <= now - timedelta(hours=1)
        )
    )
    from app.models.authentication import AuthenticationStep, SecurityAuthorization

    for model in (
        AuthenticationStep,
        SecurityAuthorization,
        DeletionAuthorization,
        PrivacyRateWindow,
        WebAuthnChallenge,
        EmailVerificationToken,
    ):
        await db.execute(delete(model).where(model.expires_at <= now))
    await db.execute(
        delete(Session).where(
            or_(
                Session.expires_at <= now,
                Session.last_activity_at
                <= now - timedelta(seconds=settings.SESSION_IDLE_TIMEOUT_SECONDS),
            )
        )
    )
    await db.execute(delete(AuthorizationCode).where(AuthorizationCode.expires_at <= now))
    await db.execute(
        delete(RefreshToken).where(
            RefreshToken.created_at
            <= now
            - timedelta(
                seconds=settings.REFRESH_FAMILY_MAX_LIFETIME_SECONDS
                + settings.REFRESH_TOKEN_TTL_SECONDS
            )
        )
    )
    await db.execute(
        delete(DeletedSubject).where(DeletedSubject.deleted_at <= now - timedelta(days=30))
    )
    await db.commit()
    return len(due)


async def maintenance_loop(settings: Settings) -> None:
    from app.database import async_session_maker

    while True:
        try:
            async with async_session_maker() as db:
                await maintenance(db, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            # No payloads, exception text or identifiers. Retry the next scheduled tick.
            from app.core.diagnostics import diagnostic

            diagnostic("privacy_maintenance", "database_unavailable", failed=True)
        await asyncio.sleep(60)
