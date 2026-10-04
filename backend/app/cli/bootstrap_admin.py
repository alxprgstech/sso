#!/usr/bin/env python3
"""
Интерактивный и идемпотентный CLI-мастер первичной инициализации ALXPRGS SSO (SETUP-03..SETUP-10).
Атомарно создаёт первого администратора, настраивает режим регистрации и фиксирует
состояние завершения bootstrap в PostgreSQL.
Секреты не передаются в аргументах командной строки, не попадают в историю терминала и логи.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import ROLE_ADMIN, ROLE_USER
from app.core.security import async_hash_password
from app.database import async_session_maker
from app.models.system import SystemConfiguration
from app.models.user import PasswordCredential, Role, User, UserRole
from app.services.audit_service import AuditService


async def execute_bootstrap(
    session: AsyncSession,
    username: str,
    email: str,
    password: str,
    registration_mode: str = "closed",
) -> tuple[int, str]:
    """
    Выполняет транзакционную инициализацию первого администратора и состояния системы (SETUP-05, SETUP-06).
    Возвращает (exit_code, message).
    """
    # 1. Проверяем состояние SystemConfiguration с блокировкой строки (FOR UPDATE)
    config_stmt = select(SystemConfiguration).where(SystemConfiguration.id == 1).with_for_update()
    res = await session.execute(config_stmt)
    config = res.scalar_one_or_none()

    # Проверяем наличие активных администраторов
    admin_check_stmt = select(User).where(
        User.is_active.is_(True),
        User.is_superuser.is_(True),
    )
    existing_admins = (await session.execute(admin_check_stmt)).scalars().all()

    if (config and config.bootstrap_completed) or existing_admins:
        if not config:
            config = SystemConfiguration(
                id=1,
                bootstrap_completed=True,
                bootstrap_completed_at=datetime.now(timezone.utc),
                registration_mode="closed",
                updated_at=datetime.now(timezone.utc),
            )
            session.add(config)
            await session.commit()
        elif not config.bootstrap_completed:
            config.bootstrap_completed = True
            if not config.bootstrap_completed_at:
                config.bootstrap_completed_at = datetime.now(timezone.utc)
            await session.commit()

        msg = (
            "[INFO] Начальная настройка системы (bootstrap) уже выполнена ранее.\n"
            "[INFO] Администратор уже существует. Повторная инициализация не требуется (идемпотентно).\n"
            "[INFO] Адрес для входа: http://localhost:3000\n"
            "[INFO] Панель администратора: http://localhost:3000/admin"
        )
        return 0, msg

    # 2. SETUP-06: Запрет повышения прав уже существующего обычного пользователя
    user_check_stmt = select(User).where((User.username == username) | (User.email == email))
    existing_user = (await session.execute(user_check_stmt)).scalar_one_or_none()
    if existing_user:
        msg = (
            f"[ERROR] Пользователь с логином '{username}' или email '{email}' уже существует.\n"
            f"[ERROR] Автоматическое повышение прав существующих пользователей запрещено (SETUP-06).\n"
            f"[ERROR] Укажите уникальные учётные данные для первичного администратора."
        )
        return 1, msg

    # 3. Валидация длины пароля
    if len(password) < 8:
        return 1, "[ERROR] Длина пароля администратора должна быть не менее 8 символов."

    # 4. Проверка и создание системных ролей
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

    admin_role = (await session.execute(select(Role).where(Role.name == ROLE_ADMIN))).scalar_one()

    # 5. Создание суперпользователя (SETUP-07, SETUP-10: email_verified=False в default-профиле)
    admin_user = User(
        username=username,
        email=email,
        is_superuser=True,
        is_active=True,
        email_verified=False,
    )
    session.add(admin_user)
    await session.flush()

    # 6. Хеширование пароля через Argon2id
    pw_hash = await async_hash_password(password)
    cred = PasswordCredential(
        user_id=admin_user.id,
        password_hash=pw_hash,
    )
    session.add(cred)

    # 7. Назначение роли admin
    session.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))

    # 8. Создание или обновление SystemConfiguration
    if not config:
        config = SystemConfiguration(
            id=1,
            bootstrap_completed=True,
            bootstrap_completed_at=datetime.now(timezone.utc),
            registration_mode=registration_mode,
            updated_at=datetime.now(timezone.utc),
        )
        session.add(config)
    else:
        config.bootstrap_completed = True
        config.bootstrap_completed_at = datetime.now(timezone.utc)
        config.registration_mode = registration_mode
        config.updated_at = datetime.now(timezone.utc)

    # 9. Запись события в аудит
    await AuditService.log_event(
        session,
        event_type="bootstrap_admin_created",
        user_id=admin_user.id,
        details={
            "username": username,
            "registration_mode": registration_mode,
            "email_verified": False,
        },
    )

    await session.commit()

    msg = (
        "\n" + "=" * 64 + "\n"
        "[SUCCESS] Начальная инициализация системы успешно завершена!\n"
        f"Логин администратора: {username}\n"
        f"Email: {email}\n"
        f"Режим регистрации: {registration_mode}\n"
        f"Статус подтверждения email: False (email_verified=False, default-профиль)\n"
        f"Адрес для входа: http://localhost:3000\n"
        f"Панель управления: http://localhost:3000/admin\n" + "=" * 64
    )
    return 0, msg


async def bootstrap_admin(
    username: str | None = None,
    email: str | None = None,
    password: str | None = None,
    registration_mode: str | None = None,
    session: AsyncSession | None = None,
) -> int:
    """
    Интерактивный или автоматизированный запуск мастера первичного администратора.
    """

    # Быстрая проверка: если уже инициализирован, не запрашиваем пароль
    async def _check_already_initialized(s: AsyncSession) -> bool:
        config_stmt = select(SystemConfiguration).where(SystemConfiguration.id == 1)
        config = (await s.execute(config_stmt)).scalar_one_or_none()
        if config and config.bootstrap_completed:
            return True
        admin_check_stmt = select(User).where(User.is_active.is_(True), User.is_superuser.is_(True))
        existing_admins = (await s.execute(admin_check_stmt)).scalars().all()
        return bool(existing_admins)

    if session is not None:
        if await _check_already_initialized(session):
            print("[INFO] Начальная настройка системы (bootstrap) уже выполнена ранее.")
            print("[INFO] Повторная инициализация не требуется (идемпотентно).")
            print("[INFO] Адрес для входа: http://localhost:3000")
            return 0
    else:
        try:
            async with async_session_maker() as chk_sess:
                if await _check_already_initialized(chk_sess):
                    print("[INFO] Начальная настройка системы (bootstrap) уже выполнена ранее.")
                    print("[INFO] Повторная инициализация не требуется (идемпотентно).")
                    print("[INFO] Адрес для входа: http://localhost:3000")
                    return 0
        except Exception:
            # Если база данных пока не создана или подключение не удалось,
            # ошибка проявится на основном шаге
            pass

    is_tty = sys.stdin.isatty()

    # 1. Логин
    if not username:
        username = os.environ.get("ADMIN_INITIAL_USERNAME", "").strip()
    if not username and is_tty:
        try:
            u_in = input("Логин первого администратора [admin]: ").strip()
            username = u_in if u_in else "admin"
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] Инициализация прервана пользователем.", file=sys.stderr)
            return 1
    elif not username:
        username = "admin"

    # 2. Email
    if not email:
        email = os.environ.get("ADMIN_INITIAL_EMAIL", "").strip()
    if not email and is_tty:
        try:
            e_in = input("Email первого администратора [admin@alxprgs.tech]: ").strip()
            email = e_in if e_in else "admin@alxprgs.tech"
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] Инициализация прервана пользователем.", file=sys.stderr)
            return 1
    elif not email:
        email = "admin@alxprgs.tech"

    # 3. Пароль (SETUP-03: скрытый ввод через TTY или ADMIN_INITIAL_PASSWORD)
    if not password:
        env_pwd = os.environ.get("ADMIN_INITIAL_PASSWORD", "").strip()
        if env_pwd:
            password = env_pwd
        elif is_tty:
            try:
                while True:
                    p1 = getpass.getpass(
                        "Введите пароль первого администратора (мин. 8 символов): "
                    )
                    if len(p1) < 8:
                        print(
                            "[ERROR] Пароль должен содержать не менее 8 символов.", file=sys.stderr
                        )
                        continue
                    p2 = getpass.getpass("Повторите пароль: ")
                    if p1 != p2:
                        print("[ERROR] Пароли не совпадают. Повторите ввод.", file=sys.stderr)
                        continue
                    password = p1
                    break
            except (EOFError, KeyboardInterrupt):
                print("\n[INFO] Инициализация прервана пользователем.", file=sys.stderr)
                return 1
        else:
            print(
                "[ERROR] TTY недоступен и переменная окружения ADMIN_INITIAL_PASSWORD не задана (SETUP-03, SETUP-09).\n"
                "Для неинтерактивного запуска укажите ADMIN_INITIAL_PASSWORD.\n"
                "Для интерактивного запуска выполните команду в терминале с поддержкой TTY.",
                file=sys.stderr,
            )
            return 1

    # 4. Режим регистрации
    if not registration_mode:
        registration_mode = os.environ.get("REGISTRATION_MODE", "").strip().lower()

    if registration_mode not in ("closed", "open"):
        if is_tty:
            try:
                print("\nВыберите режим регистрации пользователей:")
                print(
                    "  [1] Закрытый (closed) — регистрация отключена (рекомендуется по умолчанию)"
                )
                print("  [2] Открытый (open) — свободная самостоятельная регистрация")
                m_in = input("Ваш выбор [1]: ").strip().lower()
                if m_in in ("2", "open", "открытый", "o"):
                    registration_mode = "open"
                else:
                    registration_mode = "closed"
            except (EOFError, KeyboardInterrupt):
                print("\n[INFO] Инициализация прервана пользователем.", file=sys.stderr)
                return 1
        else:
            registration_mode = "closed"

    # Выполнение транзакции
    if session is not None:
        code, msg = await execute_bootstrap(session, username, email, password, registration_mode)
        if code == 0:
            print(msg)
        else:
            print(msg, file=sys.stderr)
        return code

    async with async_session_maker() as s:
        code, msg = await execute_bootstrap(s, username, email, password, registration_mode)
        if code == 0:
            print(msg)
        else:
            print(msg, file=sys.stderr)
        return code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Инициализация первого администратора ALXPRGS SSO (SETUP-03..SETUP-10)",
    )
    parser.add_argument(
        "--username", default=None, help="Логин администратора (по умолчанию: admin)"
    )
    parser.add_argument(
        "--email", default=None, help="Email администратора (по умолчанию: admin@alxprgs.tech)"
    )
    parser.add_argument(
        "--registration-mode",
        choices=["closed", "open"],
        default=None,
        help="Режим регистрации пользователей (closed или open)",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(
        bootstrap_admin(
            username=args.username,
            email=args.email,
            registration_mode=args.registration_mode,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
