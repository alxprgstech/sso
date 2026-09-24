from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import (
    generate_csrf_token,
    get_cookie_name,
    get_current_session,
    get_current_user,
    verify_csrf,
)
from app.config import Settings, get_settings
from app.database import get_db
from app.models.session import Session
from app.models.user import User
from app.schemas.auth import (
    CapabilitiesResponse,
    ChangePasswordRequest,
    LoginRequest,
    MFAStepRequiredResponse,
    SessionInfoResponse,
    UserProfileResponse,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(settings: Settings = Depends(get_settings)) -> CapabilitiesResponse:
    """Безопасная витрина возможностей сервера (SEC-FLAG-01)."""
    return CapabilitiesResponse(
        totp_enabled=settings.FEATURE_TOTP_ENABLED,
        passkey_enabled=settings.FEATURE_PASSKEY_ENABLED,
        recovery_codes_enabled=settings.FEATURE_RECOVERY_CODES_ENABLED,
        email_verification_enabled=settings.FEATURE_EMAIL_VERIFICATION_ENABLED,
        require_verified_email=settings.REQUIRE_VERIFIED_EMAIL,
    )


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")

    user, mfa_required, mfa_token, methods = await AuthService.authenticate_user(
        db,
        username=payload.username,
        password=payload.password,
        ip_address=ip,
        user_agent=ua,
    )

    if mfa_required and mfa_token:
        return MFAStepRequiredResponse(
            mfa_required=True,
            mfa_token=mfa_token,
            available_methods=methods,
        )

    # Успешный парольный вход (сессия выпускается сразу)
    raw_token, session, csrf_token = await AuthService.create_user_session(
        db=db,
        user_id=user.id,
        ip_address=ip,
        user_agent=ua,
        settings=settings,
    )

    cookie_name = get_cookie_name(settings, request)
    is_secure = (request.url.scheme == "https") or (settings.ENVIRONMENT == "production")

    response.set_cookie(
        key=cookie_name,
        value=raw_token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        path="/",
        max_age=settings.SESSION_ABSOLUTE_TIMEOUT_SECONDS,
    )

    return {
        "status": "ok",
        "csrf_token": csrf_token,
        "user": UserProfileResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            email_verified=user.email_verified,
            roles=[r.name for r in user.roles],
            has_totp=bool(user.totp_credential and user.totp_credential.is_confirmed),
            has_passkey=bool(user.webauthn_credentials and len(user.webauthn_credentials) > 0),
            created_at=user.created_at,
        ),
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_current_session),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    await db.delete(session)
    await db.commit()

    cookie_name = get_cookie_name(settings, request)
    response.delete_cookie(key=cookie_name, path="/")

    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")
    await AuditService.log_event(
        db,
        event_type="logout",
        user_id=user.id,
        ip_address=ip,
        user_agent=ua,
    )

    return {"status": "ok"}


@router.get("/me", response_model=UserProfileResponse)
async def get_me(user: User = Depends(get_current_user)) -> UserProfileResponse:
    return UserProfileResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        email_verified=user.email_verified,
        roles=[r.name for r in user.roles],
        has_totp=bool(user.totp_credential and user.totp_credential.is_confirmed),
        has_passkey=bool(user.webauthn_credentials and len(user.webauthn_credentials) > 0),
        created_at=user.created_at,
    )


@router.post("/change-password", dependencies=[Depends(verify_csrf)])
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")

    await AuthService.change_password(
        db=db,
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        current_session_id=session.id,
        ip_address=ip,
        user_agent=ua,
    )
    return {"status": "ok", "message": "Пароль успешно изменён, остальные сессии отозваны"}


@router.get("/sessions", response_model=list[SessionInfoResponse])
async def list_sessions(
    user: User = Depends(get_current_user),
    current_session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> list[SessionInfoResponse]:
    stmt = select(Session).where(Session.user_id == user.id).order_by(Session.last_activity_at.desc())
    sessions = (await db.execute(stmt)).scalars().all()

    return [
        SessionInfoResponse(
            id=s.id,
            ip_address=s.ip_address,
            user_agent=s.user_agent,
            is_current=(s.id == current_session.id),
            last_activity_at=s.last_activity_at,
            expires_at=s.expires_at,
            created_at=s.created_at,
        )
        for s in sessions
    ]


@router.delete("/sessions/{session_id}", dependencies=[Depends(verify_csrf)])
async def revoke_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    revoked = await AuthService.revoke_session(db, session_id=session_id, user_id=user.id)
    if not revoked:
        return {"status": "not_found", "message": "Сессия не найдена"}
    return {"status": "ok"}


@router.delete("/sessions", dependencies=[Depends(verify_csrf)])
async def revoke_other_sessions(
    user: User = Depends(get_current_user),
    current_session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    count = await AuthService.revoke_all_sessions(
        db,
        user_id=user.id,
        except_session_id=current_session.id,
    )
    return {"status": "ok", "revoked_count": count}
