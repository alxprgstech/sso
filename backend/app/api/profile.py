"""One user-profile projection so assurance flags cannot drift between endpoints."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.session import Session
from app.models.user import User
from app.schemas.auth import UserProfileResponse
from app.services.privacy_service import has_current_acceptance
from app.services.session_assurance import (
    admin_mfa_policy_active,
    session_is_mfa_assured,
)


def admin_mfa_pending(user: User, session: Session, settings: Settings) -> bool:
    return bool(admin_mfa_policy_active(user, settings) and not session_is_mfa_assured(session))


async def build_user_profile(
    db: AsyncSession,
    user: User,
    session: Session,
    settings: Settings,
    *,
    include_legal: bool = True,
) -> UserProfileResponse:
    return UserProfileResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        email_verified=user.email_verified,
        roles=[r.name for r in user.roles],
        has_totp=bool(user.totp_credential and user.totp_credential.is_confirmed),
        has_passkey=bool(user.webauthn_credentials),
        created_at=user.created_at,
        legal_acceptance_required=(
            not await has_current_acceptance(db, user.id) if include_legal else True
        ),
        deletion_pending=bool(user.deletion_scheduled_for),
        deletion_scheduled_for=user.deletion_scheduled_for,
        session_purpose=session.purpose,
        mfa_verified=session_is_mfa_assured(session),
        mfa_method=session.mfa_method,
        admin_mfa_required=admin_mfa_pending(user, session, settings),
    )
