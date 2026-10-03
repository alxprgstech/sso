from __future__ import annotations

import uuid
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AuthorizationException
from app.models.user import Role, User, UserRole

ROLE_ADMIN = "admin"
ROLE_USER = "user"


async def lock_admin_invariant(db: AsyncSession) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(1129466199)"))


async def is_last_active_admin(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """
    Проверяет, является ли пользователь с указанным ID последним активным администратором.
    Защита от случайной блокировки или удаления последнего администратора (USR-03).
    """
    stmt = (
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .outerjoin(UserRole, User.id == UserRole.user_id)
        .outerjoin(Role, UserRole.role_id == Role.id)
        .where(
            User.is_active.is_(True),
            User.deletion_scheduled_for.is_(None),
            (User.is_superuser.is_(True)) | (Role.name == ROLE_ADMIN),
        )
    )
    result = await db.execute(stmt)
    total_admins = result.scalar_one_or_none() or 0

    if total_admins <= 1:
        # Проверяем, является ли именно этот пользователь одним из администраторов
        user_admin_stmt = (
            select(User.id)
            .distinct()
            .outerjoin(UserRole, User.id == UserRole.user_id)
            .outerjoin(Role, UserRole.role_id == Role.id)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                (User.is_superuser.is_(True)) | (Role.name == ROLE_ADMIN),
            )
        )
        res = await db.execute(user_admin_stmt)
        if res.scalar_one_or_none() is not None:
            return True
    return False


async def ensure_not_last_admin(db: AsyncSession, user_id: uuid.UUID) -> None:
    if await is_last_active_admin(db, user_id):
        raise AuthorizationException(
            "Запрещено удалять, блокировать или лишать прав последнего активного администратора системы"
        )
