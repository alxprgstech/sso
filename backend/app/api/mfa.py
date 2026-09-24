from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import (
    get_cookie_name,
    get_current_session,
    get_current_user,
    require_feature,
    verify_csrf,
)
from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationException
from app.database import get_db
from app.models.session import Session
from app.models.user import User
from app.schemas.auth import UserProfileResponse
from app.schemas.mfa import (
    EmailVerificationConfirmRequest,
    EmailVerificationRequest,
    PasskeyAuthenticationOptionsResponse,
    PasskeyAuthenticationVerifyRequest,
    PasskeyRegistrationOptionsResponse,
    PasskeyRegistrationVerifyRequest,
    RecoveryCodesResponse,
    RecoveryCodeVerifyRequest,
    TOTPSetupResponse,
    TOTPVerifyRequest,
)
from app.services.auth_service import AuthService
from app.services.mfa_service import (
    EmailVerificationService,
    RecoveryCodesService,
    TOTPService,
    WebAuthnService,
)

router = APIRouter(prefix="/api/v1/mfa", tags=["Multi-Factor Authentication"])


# ==============================================================================
# 1. TOTP РОУТЕР (FEATURE_TOTP_ENABLED)
# ==============================================================================
totp_router = APIRouter(
    prefix="/totp",
    dependencies=[Depends(require_feature("FEATURE_TOTP_ENABLED"))],
)


@totp_router.post("/setup", response_model=TOTPSetupResponse, dependencies=[Depends(verify_csrf)])
async def setup_totp(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TOTPSetupResponse:
    secret, otpauth_url = await TOTPService.setup_totp(db, user)
    return TOTPSetupResponse(secret=secret, otpauth_url=otpauth_url)


@totp_router.post("/confirm", dependencies=[Depends(verify_csrf)])
async def confirm_totp(
    payload: TOTPVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    success = await TOTPService.confirm_totp(db, user, payload.code)
    if not success:
        raise AuthenticationException("Неверный одноразовый код TOTP")
    return {"status": "ok", "message": "Фактор TOTP успешно подтверждён и активирован"}


@totp_router.post("/verify")
async def verify_totp_login(
    payload: TOTPVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    """Подтверждение TOTP кода на втором шаге входа (MFA Step 2)."""
    if not payload.mfa_token:
        raise AuthenticationException("Параметр mfa_token обязателен для завершения входа")

    user = await AuthService.verify_mfa_step_token(payload.mfa_token, db)
    valid = await TOTPService.verify_totp(db, user, payload.code)
    if not valid:
        raise AuthenticationException("Неверный одноразовый код TOTP")

    # Выпуск сессии после успешного прохождения второго фактора
    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")
    raw_token, session, csrf_token = await AuthService.create_user_session(
        db=db, user_id=user.id, ip_address=ip, user_agent=ua, settings=settings
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
            has_totp=True,
            has_passkey=bool(user.webauthn_credentials and len(user.webauthn_credentials) > 0),
            created_at=user.created_at,
        ),
    }


@totp_router.delete("", dependencies=[Depends(verify_csrf)])
async def delete_totp(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await TOTPService.remove_totp(db, user)
    return {"status": "ok", "message": "Фактор TOTP и связанные резервные коды удалены"}


# ==============================================================================
# 2. RECOVERY CODES РОУТЕР (FEATURE_RECOVERY_CODES_ENABLED)
# ==============================================================================
recovery_router = APIRouter(
    prefix="/recovery-codes",
    dependencies=[Depends(require_feature("FEATURE_RECOVERY_CODES_ENABLED"))],
)


@recovery_router.post("/generate", response_model=RecoveryCodesResponse, dependencies=[Depends(verify_csrf)])
async def generate_recovery_codes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecoveryCodesResponse:
    codes = await RecoveryCodesService.generate_codes(db, user)
    return RecoveryCodesResponse(recovery_codes=codes)


@recovery_router.post("/verify")
async def verify_recovery_code_login(
    payload: RecoveryCodeVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    """Погашение резервного кода на втором шаге входа после ввода пароля."""
    if not payload.mfa_token:
        raise AuthenticationException("Параметр mfa_token обязателен для завершения входа")

    user = await AuthService.verify_mfa_step_token(payload.mfa_token, db)
    consumed = await RecoveryCodesService.consume_code(db, user, payload.recovery_code)
    if not consumed:
        raise AuthenticationException("Недействительный или ранее использованный резервный код")

    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")
    raw_token, session, csrf_token = await AuthService.create_user_session(
        db=db, user_id=user.id, ip_address=ip, user_agent=ua, settings=settings
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
        "message": "Вход выполнен с использованием резервного кода",
    }


# ==============================================================================
# 3. WEBAUTHN / PASSKEY РОУТЕР (FEATURE_PASSKEY_ENABLED)
# ==============================================================================
passkey_router = APIRouter(
    prefix="/passkey",
    dependencies=[Depends(require_feature("FEATURE_PASSKEY_ENABLED"))],
)


@passkey_router.post("/register/options", dependencies=[Depends(verify_csrf)])
async def passkey_register_options(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await WebAuthnService.get_registration_options(db, user)


@passkey_router.post("/register/verify", dependencies=[Depends(verify_csrf)])
async def passkey_register_verify(
    payload: PasskeyRegistrationVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await WebAuthnService.verify_registration(db, user, payload.credential, name=payload.name)
    return {"status": "ok", "message": "Passkey успешно зарегистрирован"}


@passkey_router.post("/auth/options")
async def passkey_auth_options(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await WebAuthnService.get_authentication_options(db, user=None)


@passkey_router.post("/auth/verify")
async def passkey_auth_verify(
    payload: PasskeyAuthenticationVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    if not payload.mfa_token:
        raise AuthenticationException("Параметр mfa_token обязателен для завершения входа")

    user = await AuthService.verify_mfa_step_token(payload.mfa_token, db)
    await WebAuthnService.verify_authentication(db, user, payload.credential)

    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")
    raw_token, session, csrf_token = await AuthService.create_user_session(
        db=db, user_id=user.id, ip_address=ip, user_agent=ua, settings=settings
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

    return {"status": "ok", "csrf_token": csrf_token}


@passkey_router.delete("/{credential_id}", dependencies=[Depends(verify_csrf)])
async def delete_passkey(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    deleted = await WebAuthnService.delete_passkey(db, user, credential_id)
    if not deleted:
        return {"status": "not_found", "message": "Passkey не найден"}
    return {"status": "ok"}


# ==============================================================================
# 4. EMAIL VERIFICATION РОУТЕР (FEATURE_EMAIL_VERIFICATION_ENABLED)
# ==============================================================================
email_router = APIRouter(
    prefix="/email",
    dependencies=[Depends(require_feature("FEATURE_EMAIL_VERIFICATION_ENABLED"))],
)


@email_router.post("/request", dependencies=[Depends(verify_csrf)])
async def request_email_verification(
    payload: EmailVerificationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    target_email = payload.email or user.email
    await EmailVerificationService.send_verification(db, user, target_email)
    return {"status": "ok", "message": f"Письмо с подтверждением отправлено на {target_email}"}


@email_router.post("/confirm")
async def confirm_email_verification(
    payload: EmailVerificationConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    success = await EmailVerificationService.confirm_email(db, payload.token)
    if not success:
        raise AuthenticationException("Токен подтверждения недействителен или срок его действия истёк")
    return {"status": "ok", "message": "Адрес электронной почты успешно подтверждён"}


# Монтируем 4 подроутера в основной mfa router
router.include_router(totp_router)
router.include_router(recovery_router)
router.include_router(passkey_router)
router.include_router(email_router)
