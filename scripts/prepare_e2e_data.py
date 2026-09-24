#!/usr/bin/env python3
"""
Скрипт автоматической подготовки синтетических учетных записей для E2E-тестов Playwright (G4-CI, QA-11).
Создает учетные записи первого администратора (compose_admin) и пользователей WebAuthn/Passkey,
обеспечивая полную воспроизводимость и независимость E2E-тестов от ручного bootstrap.
Поддерживает защиту тестовой базы через tests.db_guard.
"""
# ruff: noqa: E402

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

# Обеспечиваем доступ к модулям бэкенда и тестов
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.core.rbac import ROLE_ADMIN, ROLE_USER
from app.core.security import hash_password
from app.models.system import SystemConfiguration
from app.models.user import PasswordCredential, Role, User, UserRole
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.db_guard import (
    get_test_database_url,
    initialize_test_database_marker,
    mask_dsn,
    verify_test_database_marker,
)

SYNTHETIC_USERS = [
    {
        "username": "compose_admin",
        "email": "compose_admin@alxprgs.tech",
        "password": "ComposeAdminPass2026!",
        "is_superuser": True,
        "roles": [ROLE_ADMIN, ROLE_USER],
    },
    {
        "username": "e2e_passkey_multi_user",
        "email": "e2e_passkey_multi@alxprgs.tech",
        "password": "PasskeyE2E2026!",
        "is_superuser": False,
        "roles": [ROLE_USER],
    },
    {
        "username": "e2e_passkey_login_user",
        "email": "e2e_passkey_login@alxprgs.tech",
        "password": "PasskeyE2E2026!",
        "is_superuser": False,
        "roles": [ROLE_USER],
    },
    {
        "username": "e2e_passkey_delete_user",
        "email": "e2e_passkey_delete@alxprgs.tech",
        "password": "PasskeyE2E2026!",
        "is_superuser": False,
        "roles": [ROLE_USER],
    },
]


async def prepare_e2e_data() -> None:
    db_url = get_test_database_url()
    print(f"[INFO] Подготовка E2E данных на тестовой базе: {mask_dsn(db_url)}")

    engine = create_async_engine(db_url, echo=False)

    async with AsyncSession(engine) as session:
        # 0. Обеспечиваем защиту тестовой БД через db_guard маркер
        await initialize_test_database_marker(session)
        await verify_test_database_marker(session)

        # 1. Обеспечиваем наличие базовых ролей
        role_map: dict[str, Role] = {}
        for role_name in (ROLE_ADMIN, ROLE_USER):
            res = await session.execute(select(Role).where(Role.name == role_name))
            role = res.scalar_one_or_none()
            if not role:
                role = Role(name=role_name, description=f"E2E {role_name} role")
                session.add(role)
                await session.flush()
            role_map[role_name] = role

        # 2. Обеспечиваем SystemConfiguration id=1
        cfg_res = await session.execute(
            select(SystemConfiguration).where(SystemConfiguration.id == 1)
        )
        cfg = cfg_res.scalar_one_or_none()
        if not cfg:
            cfg = SystemConfiguration(
                id=1,
                bootstrap_completed=True,
                bootstrap_completed_at=datetime.now(timezone.utc),
                registration_mode="closed",
                updated_at=datetime.now(timezone.utc),
            )
            session.add(cfg)
        else:
            cfg.bootstrap_completed = True
            if not cfg.bootstrap_completed_at:
                cfg.bootstrap_completed_at = datetime.now(timezone.utc)
            cfg.registration_mode = "closed"
        await session.flush()

        # 3. Создаем/обновляем синтетических пользователей
        for u_data in SYNTHETIC_USERS:
            res = await session.execute(select(User).where(User.username == u_data["username"]))
            user = res.scalar_one_or_none()
            if not user:
                user = User(
                    username=u_data["username"],
                    email=u_data["email"],
                    is_active=True,
                    email_verified=True,
                    is_superuser=u_data["is_superuser"],
                )
                session.add(user)
                await session.flush()

                # Устанавливаем пароль
                pwd_cred = PasswordCredential(
                    user_id=user.id,
                    password_hash=hash_password(u_data["password"]),
                )
                session.add(pwd_cred)

                # Назначаем роли
                for r_name in u_data["roles"]:
                    ur = UserRole(user_id=user.id, role_id=role_map[r_name].id)
                    session.add(ur)
                print(f"[OK] Создан синтетический пользователь {u_data['username']}")
            else:
                user.is_active = True
                user.email_verified = True
                user.is_superuser = u_data["is_superuser"]
                # Обновляем пароль на детерминированный
                pwd_res = await session.execute(
                    select(PasswordCredential).where(PasswordCredential.user_id == user.id)
                )
                pwd_cred = pwd_res.scalar_one_or_none()
                if pwd_cred:
                    pwd_cred.password_hash = hash_password(u_data["password"])
                else:
                    session.add(
                        PasswordCredential(
                            user_id=user.id,
                            password_hash=hash_password(u_data["password"]),
                        )
                    )
                print(f"[OK] Обновлен синтетический пользователь {u_data['username']}")

        # 4. Очищаем устаревшие webauthn credentials для синтетических passkey пользователей
        await session.execute(
            text(
                "DELETE FROM webauthn_credentials WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'e2e_passkey_%')"
            )
        )
        await session.execute(
            text(
                "DELETE FROM webauthn_challenges WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'e2e_passkey_%')"
            )
        )

        await session.commit()
        print("[SUCCESS] Все E2E данные и учетные записи успешно подготовлены.")

    await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(prepare_e2e_data())
