from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import (
    AuthenticationException,
    AuthorizationException,
    FeatureDisabledException,
)
from app.core.rbac import ROLE_ADMIN
from app.core.security import hash_token
from app.database import get_db
from app.models.session import Session
from app.models.user import User


def get_cookie_name(settings: Settings, request: Request) -> str:
    """Определяет имя cookie (с префиксом __Host- при HTTPS)."""
    if request.url.scheme == "https" or settings.ENVIRONMENT == "production":
        return settings.SESSION_COOKIE_NAME
    return "alx_session"


async def require_recent_reauthentication(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    from app.services.reauthentication_service import consume, sensitive_action

    if not sensitive_action(request.method, request.url.path):
        return
    if request.url.path == "/api/v1/mfa/email/request":
        # Own-address verification works without a session; address changes
        # are guarded in the handler after its independently persisted quota.
        return
    # Feature gates retain their direct API contract even for anonymous requests.
    for prefix, flag in (
        ("/api/v1/mfa/totp", "FEATURE_TOTP_ENABLED"),
        ("/api/v1/mfa/passkey", "FEATURE_PASSKEY_ENABLED"),
        ("/api/v1/mfa/recovery-codes", "FEATURE_RECOVERY_CODES_ENABLED"),
    ):
        if request.url.path.startswith(prefix) and not getattr(settings, flag):
            raise FeatureDisabledException(feature=flag)
    session = await get_current_session(request, db, settings)
    await verify_csrf(request, session, settings)
    user = await get_current_user(request, session, db, settings)
    if request.url.path.startswith("/api/v1/admin/"):
        from app.core.rbac import lock_admin_invariant

        await lock_admin_invariant(db)
    await consume(db, user, session, request)


async def limit_security_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    from app.core.rate_limit import get_client_ip
    from app.services.privacy_service import RateLimit, consume_rate_limit

    path = request.url.path
    for prefix, flag in (
        ("/api/v1/mfa/totp", "FEATURE_TOTP_ENABLED"),
        ("/api/v1/mfa/passkey", "FEATURE_PASSKEY_ENABLED"),
        ("/api/v1/mfa/recovery-codes", "FEATURE_RECOVERY_CODES_ENABLED"),
    ):
        if path.startswith(prefix) and not getattr(settings, flag):
            return
    if path in {
        "/oauth/token",
        "/oauth/revoke",
        "/api/v1/mfa/totp/verify",
        "/api/v1/mfa/totp/setup",
        "/api/v1/mfa/totp/confirm",
        "/api/v1/mfa/recovery-codes/verify",
        "/api/v1/mfa/passkey/auth/options",
        "/api/v1/mfa/passkey/auth/verify",
        "/api/v1/mfa/passkey/register/options",
        "/api/v1/mfa/passkey/register/verify",
    }:
        await consume_rate_limit(db, settings, RateLimit("security-ip", get_client_ip(request), 40))


async def get_current_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Session:
    cached = getattr(request.state, "validated_session", None)
    if cached is not None and getattr(request.state, "session_db_id", None) == id(db):
        return cached
    cookie_name = get_cookie_name(settings, request)
    raw_token = request.cookies.get(cookie_name)
    if not raw_token:
        raise AuthenticationException("Сессионный cookie отсутствует")

    token_hash = hash_token(raw_token)
    from app.services.security_state import lock_user, revision

    owner = await db.scalar(select(Session.user_id).where(Session.session_token_hash == token_hash))
    if owner is None:
        raise AuthenticationException("Недействительная сессия")
    current = await lock_user(db, owner)
    stmt = (
        select(Session)
        .where(Session.session_token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise AuthenticationException("Недействительная сессия")
    if not current.is_active or session.security_revision != revision(current):
        raise AuthenticationException("Сессия отозвана изменением безопасности аккаунта")

    now = datetime.now(timezone.utc)

    # Проверка абсолютного срока жизни (7 дней)
    if session.expires_at <= now:
        await db.delete(session)
        await db.commit()
        raise AuthenticationException("Срок действия сессии истёк")

    # Проверка срока неактивности (idle timeout: 12 часов)
    idle_limit_seconds = settings.SESSION_IDLE_TIMEOUT_SECONDS
    if (now - session.last_activity_at).total_seconds() > idle_limit_seconds:
        await db.delete(session)
        await db.commit()
        raise AuthenticationException("Сессия завершена по неактивности")

    # Обновление времени последней активности
    session.last_activity_at = now
    await db.commit()

    request.state.session_id = session.id
    request.state.validated_session = session
    request.state.session_db_id = id(db)
    return session


async def get_current_user(
    request: Request,
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    stmt = select(User).where(User.id == session.user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise AuthenticationException("Пользователь не найден")

    # SSO-08: Заблокированный пользователь не может использовать сессию
    if not user.is_active:
        raise AuthenticationException("Учётная запись заблокирована")
    from app.services.security_state import require_account_access

    email_recovery_paths = {
        "/api/v1/mfa/email/request",
        "/api/v1/mfa/email/confirm",
        "/api/v1/mfa/email/confirm-code",
        "/api/v1/auth/logout",
    }
    if request.url.path not in email_recovery_paths:
        require_account_access(user, settings, allow_temporary=session.purpose == "password_change")

    from app.services.privacy_service import require_access

    path = request.url.path
    if session.purpose == "password_change":
        allowed = path in {
            "/api/v1/auth/me",
            "/api/v1/auth/logout",
            "/api/v1/auth/change-password",
            "/api/v1/auth/reauthentication",
            "/api/v1/auth/reauthentication/factor",
            "/api/v1/mfa/email/request",
            "/api/v1/mfa/email/confirm",
            "/api/v1/mfa/email/confirm-code",
        }
        if not allowed:
            raise AuthenticationException(
                "Необходимо сменить временный пароль", error="password_change_required"
            )
        return user
    privacy_management = path in {
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/auth/account-deletion",
    } or path.startswith("/api/v1/auth/account-deletion/")
    if session.purpose == "deletion_management" and not privacy_management:
        raise AuthorizationException("Доступ ограничен управлением удалением аккаунта")
    if not privacy_management and path != "/api/v1/auth/legal-acceptance":
        await require_access(db, user)

    return user


async def get_optional_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Возвращает текущего аутентифицированного пользователя, либо None при отсутствии валидной сессии."""
    cookie_name = get_cookie_name(settings, request)
    raw_token = request.cookies.get(cookie_name)
    if not raw_token:
        return None
    try:
        session = await get_current_session(request, db, settings)
        return await get_current_user(request, session, db, settings)
    except Exception:
        return None


async def require_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Серверный RBAC: доступ разрешён только администраторам."""
    is_admin = current_user.is_superuser or any(r.name == ROLE_ADMIN for r in current_user.roles)
    if not is_admin:
        raise AuthorizationException("Требуются права администратора")
    return current_user


def generate_csrf_token(session_id: uuid.UUID, settings: Settings) -> str:
    """Генерирует криптографически стойкий CSRF-токен, привязанный к сессии."""
    key = settings.SESSION_SECRET_KEY.encode("utf-8")
    msg = str(session_id).encode("utf-8")
    return hmac.new(key, msg, digestmod="sha256").hexdigest()


async def verify_csrf(
    request: Request,
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Проверка CSRF-токена для мутирующих запросов (POST, PUT, DELETE, PATCH).
    """
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        header_val = request.headers.get(settings.CSRF_HEADER_NAME)
        if not header_val:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "csrf_missing", "detail": "Заголовок X-CSRF-Token отсутствует"},
            )
        expected_token = generate_csrf_token(session.id, settings)
        if not hmac.compare_digest(header_val, expected_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "csrf_invalid", "detail": "Недействительный CSRF-токен"},
            )


def require_feature(flag_name: str):
    """
    Зависимость FastAPI для проверки состояния флагов возможностей (SEC-FLAG-02).
    При выключенном флаге запрос немедленно прерывается со статусом 404 feature_disabled.
    """

    def _dependency(settings: Settings = Depends(get_settings)):
        enabled = getattr(settings, flag_name, False)
        if not enabled:
            raise FeatureDisabledException(
                f"Функционал '{flag_name}' отключен конфигурацией сервера",
                feature=flag_name,
            )

    return _dependency
