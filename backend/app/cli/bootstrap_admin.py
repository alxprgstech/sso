#!/usr/bin/env python3
"""
Идемпотентная административная команда создания первого администратора (USR-02).
Секрет не передаётся в аргументах командной строки, не попадает в историю и логи.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
import uuid
from sqlalchemy import select
from app.config import get_settings
from app.core.rbac import ROLE_ADMIN, ROLE_USER
from app.core.security import hash_password
from app.database import async_session_maker
from app.models.user import PasswordCredential, Role, User, UserRole


async def bootstrap_admin(username: str, email: str, password: str | None = None) -> int:
    settings = get_settings()

    async with async_session_maker() as session:
        # Проверяем, существует ли уже хотя бы один активный суперпользователь
        admin_check_stmt = select(User).where(
            User.is_active.is_(True),
            User.is_superuser.is_(True),
        )
        existing_admins = (await session.execute(admin_check_stmt)).scalars().all()
        if existing_admins:
            print("[INFO] В системе уже существует активный администратор. Действие не требуется (идемпотентно).")
            return 0

        # Если пароль не передан через переменную окружения, запрашиваем через безопасный ввод getpass
        if not password:
            env_pwd = os.environ.get("ADMIN_INITIAL_PASSWORD", "").strip()
            if env_pwd:
                password = env_pwd
            else:
                if not sys.stdin.isatty():
                    print(
                        "[ERROR] Пароль не задан. Укажите ADMIN_INITIAL_PASSWORD или запустите в интерактивном терминале.",
                        file=sys.stderr,
                    )
                    return 1
                while True:
                    p1 = getpass.getpass("Введите пароль первого администратора: ")
                    if len(p1) < 8:
                        print("Ошибка: пароль должен содержать не менее 8 символов.")
                        continue
                    p2 = getpass.getpass("Повторите пароль: ")
                    if p1 != p2:
                        print("Ошибка: пароли не совпадают. Повторите ввод.")
                        continue
                    password = p1
                    break

        # Проверка и создание ролей admin и user
        for r_name, r_desc in [
            (ROLE_ADMIN, "Системный администратор ALXPRGS SSO"),
            (ROLE_USER, "Стандартный пользователь экосистемы"),
        ]:
            role_stmt = select(Role).where(Role.name == r_name)
            role_obj = (await session.execute(role_stmt)).scalar_one_or_none()
            if not role_obj:
                role_obj = Role(name=r_name, description=r_desc)
                session.add(role_obj)
        await session.flush()

        admin_role_stmt = select(Role).where(Role.name == ROLE_ADMIN)
        admin_role = (await session.execute(admin_role_stmt)).scalar_one()

        # Проверяем, существует ли пользователь с таким username или email
        user_stmt = select(User).where((User.username == username) | (User.email == email))
        user_obj = (await session.execute(user_stmt)).scalar_one_or_none()

        pw_hash = hash_password(password)

        if user_obj:
            print(f"[INFO] Пользователь '{username}' существует, повышаем привилегии до суперпользователя.")
            user_obj.is_superuser = True
            user_obj.is_active = True
            user_obj.email_verified = True

            # Обновляем пароль
            if user_obj.password_credential:
                user_obj.password_credential.password_hash = pw_hash
            else:
                user_obj.password_credential = PasswordCredential(
                    user_id=user_obj.id,
                    password_hash=pw_hash,
                )
        else:
            print(f"[INFO] Создание нового администратора '{username}' ({email})...")
            user_obj = User(
                username=username,
                email=email,
                is_superuser=True,
                is_active=True,
                email_verified=True,
            )
            session.add(user_obj)
            await session.flush()

            cred = PasswordCredential(
                user_id=user_obj.id,
                password_hash=pw_hash,
            )
            session.add(cred)

        # Назначаем роль admin
        ur_stmt = select(UserRole).where(
            UserRole.user_id == user_obj.id,
            UserRole.role_id == admin_role.id,
        )
        if not (await session.execute(ur_stmt)).scalar_one_or_none():
            session.add(UserRole(user_id=user_obj.id, role_id=admin_role.id))

        await session.commit()
        print(f"[SUCCESS] Первый администратор '{username}' успешно инициализирован.")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Инициализация первого администратора ALXPRGS SSO (USR-02)",
    )
    parser.add_argument("--username", default="admin", help="Логин администратора (по умолчанию: admin)")
    parser.add_argument("--email", default="admin@alxprgs.tech", help="Email администратора (по умолчанию: admin@alxprgs.tech)")
    args = parser.parse_args()

    exit_code = asyncio.run(bootstrap_admin(username=args.username, email=args.email))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
