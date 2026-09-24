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


async def get_current_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Session:
    cookie_name = get_cookie_name(settings, request)
    raw_token = request.cookies.get(cookie_name)
    if not raw_token:
        raise AuthenticationException("Сессионный cookie отсутствует")

    token_hash = hash_token(raw_token)
    stmt = select(Session).where(Session.session_token_hash == token_hash)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if not session:
        raise AuthenticationException("Недействительная сессия")

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
    return session


async def get_current_user(
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> User:
    stmt = select(User).where(User.id == session.user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise AuthenticationException("Пользователь не найден")

    # SSO-08: Заблокированный пользователь не может использовать сессию
    if not user.is_active:
        raise AuthenticationException("Учётная запись заблокирована")

    return user


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
