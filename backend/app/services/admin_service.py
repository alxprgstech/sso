from __future__ import annotations

import secrets
import string
import uuid
from typing import Any
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.exceptions import AuthenticationException, AuthorizationException
from app.core.rbac import ROLE_ADMIN, ROLE_USER, ensure_not_last_admin
from app.core.security import generate_random_token, hash_password, hash_token
from app.models.audit import AuditEvent
from app.models.oidc import OIDCClient, OIDCRedirectUri
from app.models.session import Session
from app.models.user import PasswordCredential, Role, User, UserRole
from app.services.audit_service import AuditService


class AdminService:
    # =========================================================================
    # 1. УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ (USR-01..03, USR-07, USR-08)
    # =========================================================================

    @staticmethod
    async def list_users(
        db: AsyncSession,
        offset: int = 0,
        limit: int = 50,
        search: str | None = None,
    ) -> list[User]:
        stmt = (
            select(User)
            .options(
                selectinload(User.roles),
                selectinload(User.password_credential),
            )
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if search:
            search_pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                (User.username.ilike(search_pattern)) | (User.email.ilike(search_pattern))
            )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
        stmt = (
            select(User)
            .options(
                selectinload(User.roles),
                selectinload(User.password_credential),
            )
            .where(User.id == user_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_user(
        db: AsyncSession,
        username: str,
        email: str,
        password: str,
        roles: list[str] | None = None,
        is_superuser: bool = False,
        admin_user_id: uuid.UUID | None = None,
    ) -> User:
        # Проверка уникальности
        stmt = select(User).where((User.username == username) | (User.email == email))
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            raise AuthorizationException("Пользователь с таким именем или email уже существует")

        user = User(
            id=uuid.uuid4(),
            username=username.strip(),
            email=email.strip().lower(),
            is_active=True,
            is_superuser=is_superuser,
            email_verified=False,
        )
        db.add(user)
        await db.flush()

        # Создание пароля (Argon2id)
        pwd_hash = hash_password(password)
        pwd_cred = PasswordCredential(
            user_id=user.id,
            password_hash=pwd_hash,
            algorithm="argon2id",
        )
        db.add(pwd_cred)

        # Назначение ролей
        role_names = roles or [ROLE_USER]
        if is_superuser and ROLE_ADMIN not in role_names:
            role_names.append(ROLE_ADMIN)

        for r_name in set(role_names):
            r_stmt = select(Role).where(Role.name == r_name)
            role_obj = (await db.execute(r_stmt)).scalar_one_or_none()
            if not role_obj:
                role_obj = Role(name=r_name)
                db.add(role_obj)
                await db.flush()
            user_role = UserRole(user_id=user.id, role_id=role_obj.id)
            db.add(user_role)

        await db.commit()

        # Аудит создания
        await AuditService.log_event(
            db,
            event_type="user_created",
            user_id=admin_user_id,
            details={"created_user_id": str(user.id), "username": username},
        )

        return await AdminService.get_user_by_id(db, user.id)  # type: ignore

    @staticmethod
    async def update_user(
        db: AsyncSession,
        user_id: uuid.UUID,
        current_admin: User,
        email: str | None = None,
        is_active: bool | None = None,
        is_superuser: bool | None = None,
        roles: list[str] | None = None,
        new_password: str | None = None,
    ) -> User:
        user = await AdminService.get_user_by_id(db, user_id)
        if not user:
            raise AuthorizationException("Пользователь не найден")

        # Защита от блокировки или снятия прав последнего администратора (USR-08)
        is_admin_now = user.is_superuser or any(r.name == ROLE_ADMIN for r in user.roles)
        if is_admin_now:
            if is_active is False or is_superuser is False or (roles is not None and ROLE_ADMIN not in roles):
                await ensure_not_last_admin(db, user.id)

        if email is not None:
            user.email = email.strip().lower()

        must_revoke_sessions = False

        if is_active is not None and is_active != user.is_active:
            user.is_active = is_active
            if not is_active:
                must_revoke_sessions = True
            await AuditService.log_event(
                db,
                event_type="user_blocked" if not is_active else "user_unblocked",
                user_id=current_admin.id,
                details={"target_user_id": str(user.id)},
            )

        if is_superuser is not None:
            user.is_superuser = is_superuser

        if roles is not None:
            # Переопределяем роли
            await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
            for r_name in set(roles):
                r_stmt = select(Role).where(Role.name == r_name)
                role_obj = (await db.execute(r_stmt)).scalar_one_or_none()
                if not role_obj:
                    role_obj = Role(name=r_name)
                    db.add(role_obj)
                    await db.flush()
                db.add(UserRole(user_id=user.id, role_id=role_obj.id))

        if new_password is not None:
            pwd_hash = hash_password(new_password)
            if user.password_credential:
                user.password_credential.password_hash = pwd_hash
            else:
                db.add(PasswordCredential(user_id=user.id, password_hash=pwd_hash))
            must_revoke_sessions = True
            await AuditService.log_event(
                db,
                event_type="admin_password_reset",
                user_id=current_admin.id,
                details={"target_user_id": str(user.id)},
            )

        if must_revoke_sessions:
            await db.execute(delete(Session).where(Session.user_id == user.id))

        await db.commit()
        return await AdminService.get_user_by_id(db, user.id)  # type: ignore

    @staticmethod
    async def revoke_all_user_sessions(
        db: AsyncSession,
        user_id: uuid.UUID,
        admin_user_id: uuid.UUID,
    ) -> int:
        stmt = delete(Session).where(Session.user_id == user_id)
        res = await db.execute(stmt)
        await db.commit()
        count = res.rowcount or 0
        await AuditService.log_event(
            db,
            event_type="admin_revoked_sessions",
            user_id=admin_user_id,
            details={"target_user_id": str(user_id), "revoked_count": count},
        )
        return count

    # =========================================================================
    # 2. УПРАВЛЕНИЕ OIDC-КЛИЕНТАМИ (USR-09, SSO-02)
    # =========================================================================

    @staticmethod
    async def list_clients(
        db: AsyncSession,
        offset: int = 0,
        limit: int = 50,
    ) -> list[OIDCClient]:
        stmt = (
            select(OIDCClient)
            .options(selectinload(OIDCClient.redirect_uris))
            .order_by(OIDCClient.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_client(
        db: AsyncSession,
        client_name: str,
        client_type: str,
        redirect_uris: list[str],
        admin_user_id: uuid.UUID | None = None,
    ) -> tuple[OIDCClient, str | None]:
        """
        Регистрация нового OIDC клиента.
        Секрет генерируется и возвращается ТОЛЬКО ОДИН РАЗ (USR-09).
        """
        client_id = f"client_{generate_random_token(16)}"
        raw_secret: str | None = None
        secret_hash: str | None = None

        if client_type == "confidential":
            raw_secret = f"sec_{generate_random_token(32)}"
            secret_hash = hash_password(raw_secret)

        client = OIDCClient(
            id=uuid.uuid4(),
            client_id=client_id,
            client_name=client_name.strip(),
            client_type=client_type,
            client_secret_hash=secret_hash,
            is_active=True,
        )
        db.add(client)
        await db.flush()

        for uri in set(redirect_uris):
            if uri.strip():
                redirect = OIDCRedirectUri(client_id=client.id, uri=uri.strip())
                db.add(redirect)

        await db.commit()

        await AuditService.log_event(
            db,
            event_type="oidc_client_created",
            user_id=admin_user_id,
            details={"client_id": client_id, "client_name": client_name},
        )

        loaded_client = (
            await db.execute(
                select(OIDCClient)
                .options(selectinload(OIDCClient.redirect_uris))
                .where(OIDCClient.id == client.id)
            )
        ).scalar_one()

        return loaded_client, raw_secret

    @staticmethod
    async def rotate_client_secret(
        db: AsyncSession,
        client_id: str,
        admin_user_id: uuid.UUID | None = None,
    ) -> tuple[OIDCClient, str]:
        stmt = (
            select(OIDCClient)
            .options(selectinload(OIDCClient.redirect_uris))
            .where(OIDCClient.client_id == client_id)
        )
        client = (await db.execute(stmt)).scalar_one_or_none()
        if not client:
            raise AuthorizationException("Клиент не найден")

        raw_secret = f"sec_{generate_random_token(32)}"
        client.client_secret_hash = hash_password(raw_secret)
        await db.commit()

        await AuditService.log_event(
            db,
            event_type="oidc_client_secret_rotated",
            user_id=admin_user_id,
            details={"client_id": client_id},
        )
        return client, raw_secret

    @staticmethod
    async def delete_client(
        db: AsyncSession,
        client_id: str,
        admin_user_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = delete(OIDCClient).where(OIDCClient.client_id == client_id)
        res = await db.execute(stmt)
        await db.commit()
        if (res.rowcount or 0) > 0:
            await AuditService.log_event(
                db,
                event_type="oidc_client_deleted",
                user_id=admin_user_id,
                details={"client_id": client_id},
            )
            return True
        return False

    # =========================================================================
    # 3. ЖУРНАЛ АУДИТА (AUDIT-01..03)
    # =========================================================================

    @staticmethod
    async def list_audit_events(
        db: AsyncSession,
        offset: int = 0,
        limit: int = 50,
        user_id: uuid.UUID | None = None,
        event_type: str | None = None,
    ) -> list[AuditEvent]:
        stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)
        if user_id:
            stmt = stmt.where(AuditEvent.user_id == user_id)
        if event_type:
            stmt = stmt.where(AuditEvent.event_type == event_type)

        result = await db.execute(stmt)
        return list(result.scalars().all())
