from __future__ import annotations

from dataclasses import dataclass

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_cookie_name,
    get_current_session,
    get_current_user,
    get_optional_current_user,
    limit_security_endpoint,
    require_feature,
    require_recent_reauthentication,
    verify_csrf,
)
from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationException
from app.core.rate_limit import get_client_ip
from app.database import get_db
from app.models.mfa import WebAuthnCredential
from app.models.session import Session
from app.models.user import User
from app.schemas.auth import UserProfileResponse
from app.schemas.mfa import (
    EmailVerificationCodeConfirmRequest,
    EmailVerificationConfirmRequest,
    EmailVerificationRequest,
    PasskeyAuthenticationVerifyRequest,
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
    _cred_id_to_bytes,
    WebAuthnContext,
    PasskeyRegistration,
    PasskeyAuthentication,
)
from app.services.verification_email import request_details

router = APIRouter(
    prefix="/api/v1/mfa",
    tags=["Multi-Factor Authentication"],
    dependencies=[Depends(limit_security_endpoint), Depends(require_recent_reauthentication)],
)


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
    session: Session = Depends(get_current_session),
) -> TOTPSetupResponse:
    secret, otpauth_url = await TOTPService.setup_totp(db, user, session.id)
    return TOTPSetupResponse(secret=secret, otpauth_url=otpauth_url)


@totp_router.post("/confirm", dependencies=[Depends(verify_csrf)])
async def confirm_totp(
    payload: TOTPVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    session: Session = Depends(get_current_session),
) -> dict[str, str]:
    success = await TOTPService.confirm_totp(db, user, payload.code, session.id)
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

    user = await AuthService.verify_mfa_step_token(
        payload.mfa_token, db, method="totp", settings=settings
    )
    valid = await TOTPService.verify_totp(db, user, payload.code, commit=False)
    if not valid:
        raise AuthenticationException("Неверный одноразовый код TOTP")

    # Выпуск сессии после успешного прохождения второго фактора
    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent")
    raw_token, session, csrf_token = await AuthService.create_user_session(
        db=db,
        user_id=user.id,
        ip_address=ip,
        user_agent=ua,
        settings=settings,
        expected_revision=user.security_revision or 0,
        mfa_token=payload.mfa_token,
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
            session_purpose=session.purpose,
        ),
    }


@totp_router.delete("", dependencies=[Depends(verify_csrf)])
async def delete_totp(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    session: Session = Depends(get_current_session),
) -> dict[str, str]:
    await TOTPService.remove_totp(db, user, session.id)
    return {"status": "ok", "message": "Фактор TOTP и связанные резервные коды удалены"}


# ==============================================================================
# 2. RECOVERY CODES РОУТЕР (FEATURE_RECOVERY_CODES_ENABLED)
# ==============================================================================
recovery_router = APIRouter(
    prefix="/recovery-codes",
    dependencies=[Depends(require_feature("FEATURE_RECOVERY_CODES_ENABLED"))],
)


@recovery_router.post(
    "/generate", response_model=RecoveryCodesResponse, dependencies=[Depends(verify_csrf)]
)
async def generate_recovery_codes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    session: Session = Depends(get_current_session),
) -> RecoveryCodesResponse:
    codes = await RecoveryCodesService.generate_codes(db, user, session.id)
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

    user = await AuthService.verify_mfa_step_token(
        payload.mfa_token, db, method="recovery_code", settings=settings
    )
    consumed = await RecoveryCodesService.consume_code(
        db, user, payload.recovery_code, commit=False
    )
    if not consumed:
        raise AuthenticationException("Недействительный или ранее использованный резервный код")

    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent")
    raw_token, session, csrf_token = await AuthService.create_user_session(
        db=db,
        user_id=user.id,
        ip_address=ip,
        user_agent=ua,
        settings=settings,
        expected_revision=user.security_revision or 0,
        mfa_token=payload.mfa_token,
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
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_current_session),
) -> dict[str, Any]:
    return await WebAuthnService.get_registration_options(
        db,
        user,
        context=WebAuthnContext(
            rp_id=settings.WEBAUTHN_RP_ID, settings=settings, session_id=session.id
        ),
    )


@passkey_router.post("/register/verify", dependencies=[Depends(verify_csrf)])
async def passkey_register_verify(
    payload: PasskeyRegistrationVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_current_session),
) -> dict[str, str]:
    await WebAuthnService.verify_registration(
        db,
        user,
        PasskeyRegistration(payload.credential, name=payload.name),
        context=WebAuthnContext(
            rp_id=settings.WEBAUTHN_RP_ID,
            origin=settings.WEBAUTHN_ORIGIN,
            settings=settings,
            session_id=session.id,
        ),
    )
    return {"status": "ok", "message": "Passkey успешно зарегистрирован"}


@passkey_router.post("/auth/options")
async def passkey_auth_options(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return await WebAuthnService.get_authentication_options(
        db,
        user=None,
        operation=PasskeyAuthentication(
            trust=WebAuthnContext(rp_id=settings.WEBAUTHN_RP_ID, settings=settings)
        ),
    )


async def _find_discoverable_credential(db: AsyncSession, raw_id: str):
    from sqlalchemy import select

    cred_stmt = select(WebAuthnCredential).where(WebAuthnCredential.credential_id == raw_id)
    cred_obj = (await db.execute(cred_stmt)).scalar_one_or_none()
    if not cred_obj:
        all_creds = (await db.execute(select(WebAuthnCredential))).scalars().all()
        for c in all_creds:
            if _cred_id_to_bytes(c.credential_id) == _cred_id_to_bytes(raw_id):
                cred_obj = c
                break

    return cred_obj


async def _discoverable_passkey_user(db: AsyncSession, credential: dict[str, Any]) -> User:
    from sqlalchemy import select

    # Discoverable passkey login (без пароля)
    cred_dict = credential
    raw_id = cred_dict.get("id") or cred_dict.get("rawId")
    if not raw_id:
        raise AuthenticationException("Отсутствует идентификатор ключа Passkey (id)")

    cred_obj = await _find_discoverable_credential(db, raw_id)

    if not cred_obj:
        raise AuthenticationException("Passkey не найден или был удалён")

    user_stmt = select(User).where(User.id == cred_obj.user_id)
    found_user = (await db.execute(user_stmt)).scalar_one_or_none()
    if not found_user or not found_user.is_active:
        raise AuthenticationException("Пользователь не найден или заблокирован")
    return found_user


@passkey_router.post("/auth/verify")
async def passkey_auth_verify(
    payload: PasskeyAuthenticationVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:

    if payload.mfa_token:
        user = await AuthService.verify_mfa_step_token(
            payload.mfa_token, db, method="passkey", settings=settings
        )
    else:
        user = await _discoverable_passkey_user(db, payload.credential)

    await WebAuthnService.verify_authentication(
        db,
        user,
        payload.credential,
        operation=PasskeyAuthentication(
            trust=WebAuthnContext(
                rp_id=settings.WEBAUTHN_RP_ID, origin=settings.WEBAUTHN_ORIGIN, settings=settings
            ),
            commit=False,
        ),
    )

    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent")
    raw_token, session, csrf_token = await AuthService.create_user_session(
        db=db,
        user_id=user.id,
        ip_address=ip,
        user_agent=ua,
        settings=settings,
        expected_revision=user.security_revision or 0,
        mfa_token=payload.mfa_token,
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
        "user": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
        },
    }


@passkey_router.get("/credentials")
async def list_user_passkeys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    return await WebAuthnService.list_credentials(db, user)


@passkey_router.delete("/credentials/{credential_id:path}", dependencies=[Depends(verify_csrf)])
async def delete_passkey(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    session: Session = Depends(get_current_session),
) -> dict[str, str]:
    from fastapi import HTTPException

    deleted = await WebAuthnService.delete_passkey(db, user, credential_id, session.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Passkey не найден")
    return {"status": "ok"}


# ==============================================================================
# 4. EMAIL VERIFICATION РОУТЕР
# ==============================================================================
email_router = APIRouter(
    prefix="/email",
)


@dataclass(frozen=True, repr=False)
class EmailRequestContext:
    request: Request
    db: AsyncSession
    settings: Settings


async def _request_user_email(
    context: EmailRequestContext, user: User, email: str | None
) -> dict[str, str]:
    cookie_name = get_cookie_name(context.settings, context.request)
    if context.request.cookies.get(cookie_name):
        session = await get_current_session(context.request, context.db, context.settings)
        await verify_csrf(context.request, session, context.settings)

    target_email = (email or user.email).strip().lower()
    if target_email != user.email:
        from app.services.reauthentication_service import consume

        session = await get_current_session(context.request, context.db, context.settings)
        await consume(context.db, user, session, context.request)
    await EmailVerificationService.send_verification(
        context.db,
        user,
        target_email,
        context.settings,
        request_details(context.request, context.settings),
    )
    return {"status": "ok", "message": f"Письмо с подтверждением отправлено на {target_email}"}


async def _request_unverified_email(context: EmailRequestContext, email: str) -> None:
    from sqlalchemy import func, select

    clean_email = email.strip().lower()
    stmt = select(User).where(func.lower(User.email) == clean_email)
    target_user = (await context.db.execute(stmt)).scalar_one_or_none()

    if target_user and not target_user.email_verified:
        await EmailVerificationService.send_verification(
            context.db,
            target_user,
            clean_email,
            context.settings,
            request_details(context.request, context.settings),
        )


@email_router.post("/request")
async def request_email_verification(
    payload: EmailVerificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """
    Запрос письма с подтверждением адреса электронной почты (G4-EMAIL, SEC-FLAG-07).
    Поддерживает как аутентифицированных пользователей, так и неподтверждённых пользователей
    без активной сессии (с защитой от перечисления аккаунтов и rate limiting).
    """
    from fastapi import HTTPException, status

    from app.core.rate_limit import check_email_request_rate_limit, get_client_ip

    ip = get_client_ip(request)

    # Ограничение частоты запросов подтверждения
    await check_email_request_rate_limit(db, ip)

    context = EmailRequestContext(request, db, settings)
    if user:
        return await _request_user_email(context, user, payload.email)

    # 2. Неаутентифицированный запрос (неподтвержденный пользователь)
    if not payload.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Необходимо указать email для отправки подтверждения",
        )

    await _request_unverified_email(context, payload.email)

    # Защита от перечисления аккаунтов (Account Enumeration):
    # Возвращаем нейтральный ответ
    return {
        "status": "ok",
        "message": "Если указанный адрес зарегистрирован в системе, на него отправлено письмо с подтверждением",
    }


@email_router.post("/confirm")
async def confirm_email_verification(
    payload: EmailVerificationConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    success = await EmailVerificationService.confirm_email(db, payload.token)
    if not success:
        raise AuthenticationException(
            "Токен подтверждения недействителен или срок его действия истёк"
        )
    return {"status": "ok", "message": "Адрес электронной почты успешно подтверждён"}


@email_router.post("/confirm-code")
async def confirm_email_code(
    payload: EmailVerificationCodeConfirmRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    success = await EmailVerificationService.confirm_code(db, payload.email, payload.code, settings)
    if not success:
        raise AuthenticationException("Код подтверждения недействителен или истёк")
    return {"status": "ok", "message": "Адрес электронной почты успешно подтверждён"}


# Монтируем 4 подроутера в основной mfa router
router.include_router(totp_router)
router.include_router(recovery_router)
router.include_router(passkey_router)
router.include_router(email_router)
