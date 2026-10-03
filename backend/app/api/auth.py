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
from app.core.rate_limit import get_client_ip
from app.schemas.auth import (
    CapabilitiesResponse,
    ChangePasswordRequest,
    LoginRequest,
    MFAStepRequiredResponse,
    RegisterRequest,
    RegisterResponse,
    RegistrationCodeConfirmRequest,
    RegistrationCompleteResponse,
    RegistrationLinkConfirmRequest,
    RegistrationResendRequest,
    SessionInfoResponse,
    UserProfileResponse,
    TelemetryConfigResponse,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.registration_service import RegistrationService, verify_gmail_bearer
from app.services.verification_email import request_details
from app.services.system_service import SystemService

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.get("/telemetry-config", response_model=TelemetryConfigResponse)
async def telemetry_config(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> TelemetryConfigResponse:
    from urllib.parse import urlsplit
    from typing import cast, Literal

    # No database, session or request-derived origin; this response is public.
    response.headers["Cache-Control"] = "no-store"
    enabled = settings.SENTRY_FRONTEND_ENABLED and bool(settings.SENTRY_FRONTEND_DSN)
    replay = (
        enabled and settings.SENTRY_REPLAY_ENABLED and settings.telemetry_environment == "staging"
    )
    origin = urlsplit(settings.FRONTEND_URL)
    base = f"{origin.scheme}://{origin.netloc}"
    return TelemetryConfigResponse(
        enabled=enabled,
        dsn=settings.SENTRY_FRONTEND_DSN if enabled else "",
        environment=cast(
            Literal["local", "test", "staging", "production"], settings.telemetry_environment
        ),
        traces_sample_rate=settings.SENTRY_FRONTEND_TRACES_SAMPLE_RATE if enabled else 0,
        replay_enabled=replay,
        replays_session_sample_rate=settings.SENTRY_REPLAYS_SESSION_SAMPLE_RATE if replay else 0,
        replays_on_error_sample_rate=settings.SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE if replay else 0,
        trace_propagation_targets=[f"{base}/api/", f"{base}/oauth/"] if enabled else [],
    )


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CapabilitiesResponse:
    """Безопасная витрина возможностей сервера (SEC-FLAG-01, REG-03)."""
    try:
        reg_mode = await SystemService.get_registration_mode(db)
    except Exception as error:
        from app.telemetry import capture_infrastructure_failure

        capture_infrastructure_failure(error, "capabilities")
        reg_mode = "closed"

    return CapabilitiesResponse(
        totp_enabled=settings.FEATURE_TOTP_ENABLED,
        passkey_enabled=settings.FEATURE_PASSKEY_ENABLED,
        recovery_codes_enabled=settings.FEATURE_RECOVERY_CODES_ENABLED,
        email_verification_enabled=True,
        require_verified_email=settings.REQUIRE_VERIFIED_EMAIL,
        registration_mode=reg_mode,
    )


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_202_ACCEPTED)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegisterResponse:
    """
    Самостоятельная регистрация обычного пользователя (REG-01..REG-09).
    """
    # Защита от межсайтовой подделки / недоверенного Origin (REG-07)
    origin = request.headers.get("Origin")
    if origin:
        from urllib.parse import urlparse

        origin_host = urlparse(origin).netloc.split(":")[0].lower()
        allowed_hosts = {
            "localhost",
            "127.0.0.1",
            "auth.alxprgs.tech",
            "alxprgs.tech",
            urlparse(settings.BASE_URL).netloc.split(":")[0].lower(),
            urlparse(settings.FRONTEND_URL).netloc.split(":")[0].lower(),
        }
        if origin_host not in allowed_hosts:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "invalid_origin",
                    "detail": "Запрос отклонен: недоверенный Origin",
                },
            )

    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent")

    pending = await AuthService.register_user(
        db=db,
        username=payload.username,
        email=payload.email,
        password=payload.password,
        ip_address=ip,
        user_agent=ua,
        settings=settings,
        request_details=request_details(request, settings),
        legal_versions=payload.legal_versions,
    )

    return RegisterResponse(
        challenge_id=pending.id,
        expires_at=pending.expires_at,
        request_details=pending.request_details,
    )


@router.post("/register/confirm-code", response_model=RegistrationCompleteResponse)
async def confirm_registration_code(
    payload: RegistrationCodeConfirmRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegistrationCompleteResponse:
    user = await RegistrationService.confirm(
        db, settings=settings, challenge_id=payload.challenge_id, code=payload.code
    )
    return RegistrationCompleteResponse(user_id=user.id)


@router.post("/register/confirm-link", response_model=RegistrationCompleteResponse)
async def confirm_registration_link(
    payload: RegistrationLinkConfirmRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegistrationCompleteResponse:
    user = await RegistrationService.confirm(db, settings=settings, link=payload.token)
    return RegistrationCompleteResponse(user_id=user.id)


@router.post("/register/preview-link")
async def preview_registration_link(
    payload: RegistrationLinkConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, dict[str, str]]:
    return {"request_details": await RegistrationService.preview_link(db, payload.token)}


@router.post(
    "/register/resend", response_model=RegisterResponse, status_code=status.HTTP_202_ACCEPTED
)
async def resend_registration(
    payload: RegistrationResendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegisterResponse:
    pending = await RegistrationService.resend(
        db, payload.challenge_id, get_client_ip(request), settings
    )
    return RegisterResponse(
        challenge_id=pending.id,
        expires_at=pending.expires_at,
        request_details=pending.request_details,
    )


@router.post("/register/confirm-gmail", response_model=RegistrationCompleteResponse)
async def confirm_registration_gmail(
    request: Request,
    challenge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RegistrationCompleteResponse:
    await verify_gmail_bearer(request.headers.get("Authorization", ""), settings)
    user = await RegistrationService.confirm(db, settings=settings, action_id=challenge_id)
    return RegistrationCompleteResponse(user_id=user.id)


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
        settings=settings,
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


@router.post("/logout", dependencies=[Depends(verify_csrf)])
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
async def get_me(
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> UserProfileResponse:
    csrf = generate_csrf_token(session.id, settings)
    response.headers["X-CSRF-Token"] = csrf
    response.headers["Access-Control-Expose-Headers"] = "X-CSRF-Token"
    from app.services.privacy_service import has_current_acceptance

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
        legal_acceptance_required=not await has_current_acceptance(db, user.id),
        deletion_pending=bool(user.deletion_scheduled_for),
        deletion_scheduled_for=user.deletion_scheduled_for,
        session_purpose=session.purpose,
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
    stmt = (
        select(Session).where(Session.user_id == user.id).order_by(Session.last_activity_at.desc())
    )
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
