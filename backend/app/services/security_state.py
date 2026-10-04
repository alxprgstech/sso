"""Account lock ordering, access policy and atomic invalidation shared by security events."""

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import AuthenticationException
from app.models.authentication import AuthenticationStep, SecurityAuthorization
from app.models.mfa import EmailVerificationToken, TOTPCredential, WebAuthnChallenge
from app.models.oidc import AuthorizationCode, RefreshToken
from app.models.privacy import DeletionAuthorization
from app.models.session import Session
from app.models.user import User


def revision(user: User) -> int:
    return user.security_revision or 0


def require_account_access(
    user: User, settings: Settings, *, allow_temporary: bool = False
) -> None:
    if not user.is_active:
        raise AuthenticationException("Аккаунт недоступен")
    _require_verified_email(user, settings)
    if allow_temporary:
        return
    _require_regular_password(user)


def _require_verified_email(user: User, settings: Settings) -> None:
    if settings.REQUIRE_VERIFIED_EMAIL and not user.email_verified:
        raise AuthenticationException(
            "Требуется подтверждение адреса электронной почты", error="email_verification_required"
        )


def _require_regular_password(user: User) -> None:
    credential = user.password_credential
    if credential and credential.requires_change:
        raise AuthenticationException(
            "Необходимо сменить временный пароль", error="password_change_required"
        )


async def lock_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise AuthenticationException("Аккаунт недоступен")
    return user


async def invalidate_security_state(
    db: AsyncSession,
    user: User,
    *,
    preserve_session_id: uuid.UUID | None = None,
    preserve_email_token_id: uuid.UUID | None = None,
) -> None:
    """Caller holds User lock and owns commit. Old refresh rows retain replay evidence."""
    user.security_revision = revision(user) + 1
    await db.flush()
    sessions = delete(Session).where(Session.user_id == user.id)
    if preserve_session_id is not None:
        sessions = sessions.where(Session.id != preserve_session_id)
        await db.execute(
            update(Session)
            .where(Session.id == preserve_session_id, Session.user_id == user.id)
            .values(security_revision=user.security_revision)
        )
    await db.execute(sessions)
    await db.execute(
        update(TOTPCredential)
        .where(TOTPCredential.user_id == user.id)
        .values(pending_encrypted_secret=None, pending_expires_at=None, pending_session_id=None)
    )
    await db.execute(delete(AuthorizationCode).where(AuthorizationCode.user_id == user.id))
    await db.execute(
        update(RefreshToken).where(RefreshToken.user_id == user.id).values(is_revoked=True)
    )
    for model in (
        AuthenticationStep,
        SecurityAuthorization,
        DeletionAuthorization,
        WebAuthnChallenge,
        EmailVerificationToken,
    ):
        statement = delete(model).where(model.user_id == user.id)
        if model is EmailVerificationToken and preserve_email_token_id is not None:
            statement = statement.where(model.id != preserve_email_token_id)
        await db.execute(statement)
