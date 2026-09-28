"""
Модуль защиты тестовой базы данных PostgreSQL (G4-DB, QA-02).
Гарантирует изоляцию тестового контура, исключает случайную очистку боевой БД (sso_db),
требует явную переменную TEST_DATABASE_URL (без fallback на DATABASE_URL),
маскирует учетные данные в DSN и проверяет маркер владения тестовой средой перед TRUNCATE/DROP.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

MARKER_TABLE_NAME = "test_database_marker"
MARKER_ID = "ALXPRGS_TEST_ENV_MARKER"
EXPECTED_ENVIRONMENT = "alxprgs_sso_isolated_test"

FORBIDDEN_DATABASES = frozenset(
    {
        "sso_db",
        "postgres",
        "production",
        "alxprgs_sso",
        "alxprgs_sso_prod",
        "prod",
        "master",
    }
)


class TestDatabaseSafetyError(Exception):
    """Исключение безопасности: попытка работы с небезопасной или рабочей БД в тестах."""

    __test__ = False


def mask_dsn(url: str) -> str:
    """Безопасно маскирует пароль в DSN строке подключения."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        if parts.password:
            netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        pass
    return re.sub(r":([^/@]+)@", ":***@", url)


def get_test_database_url() -> str:
    """
    Возвращает строку подключения к тестовой базе данных PostgreSQL.

    Требование G4-DB:
    - Выделена переменная TEST_DATABASE_URL;
    - Fallback на рабочий DATABASE_URL строго запрещён;
    - Отсутствие TEST_DATABASE_URL вызывает понятный отказ до открытия соединений.
    """
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        has_generic_db = "DATABASE_URL" in os.environ
        prod_warning = (
            " Внимание: обнаружена переменная DATABASE_URL, но fallback на неё строго "
            "запрещён архитектурным инвариантом G4-DB во избежание потери рабочих данных."
            if has_generic_db
            else ""
        )
        raise TestDatabaseSafetyError(
            "ОШИБКА G4-DB: Переменная окружения TEST_DATABASE_URL не задана."
            f"{prod_warning} Задайте TEST_DATABASE_URL для запуска интеграционных тестов "
            "(например: postgresql+psycopg://sso_test_user:sso_test_password@localhost:5433/alxprgs_sso_test)."
        )

    # Предварительная проверка безопасности имени базы из DSN
    try:
        parts = urlsplit(test_url)
        db_name = parts.path.lstrip("/").split("?")[0].lower()
        if db_name in FORBIDDEN_DATABASES:
            raise TestDatabaseSafetyError(
                f"ОШИБКА G4-DB: TEST_DATABASE_URL указывает на запрещённую рабочую базу данных '{db_name}'. "
                f"Подключение заблокировано для предотвращения уничтожения данных. DSN: {mask_dsn(test_url)}"
            )
        if "test" not in db_name:
            raise TestDatabaseSafetyError(
                f"ОШИБКА G4-DB: Имя базы данных '{db_name}' не содержит маркер 'test'. "
                f"Использование базы данных в качестве тестовой отклонено. DSN: {mask_dsn(test_url)}"
            )
    except TestDatabaseSafetyError:
        raise
    except Exception as exc:
        raise TestDatabaseSafetyError(
            f"ОШИБКА G4-DB: Некорректный формат TEST_DATABASE_URL: {mask_dsn(test_url)}. Исключение: {exc}"
        ) from exc

    return test_url


async def verify_test_database_marker(conn: AsyncConnection | AsyncSession) -> None:
    """
    Проверяет, что текущая база данных содержит валидный маркер тестовой среды.
    Если маркерная таблица отсутствует или запись не валидна — очистка блокируется.
    """
    # 1. Проверяем текущее имя базы данных
    res_db = await conn.execute(text("SELECT current_database()"))
    current_db = (res_db.scalar_one() or "").lower()

    if current_db in FORBIDDEN_DATABASES:
        raise TestDatabaseSafetyError(
            f"ОШИБКА G4-DB: Текущая база данных '{current_db}' входит в список запрещённых рабочих баз. "
            "Любые деструктивные операции немедленно заблокированы!"
        )

    if "test" not in current_db:
        raise TestDatabaseSafetyError(
            f"ОШИБКА G4-DB: База данных '{current_db}' не содержит маркера 'test' в имени. "
            "Операция отменена в целях безопасности."
        )

    # 2. Проверяем наличие таблицы test_database_marker
    check_table_stmt = text(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables "
        "  WHERE table_schema = 'public' AND table_name = :tbl"
        ")"
    )
    res_table = await conn.execute(check_table_stmt, {"tbl": MARKER_TABLE_NAME})
    table_exists = res_table.scalar_one()
    if not table_exists:
        raise TestDatabaseSafetyError(
            f"ОШИБКА G4-DB: База данных '{current_db}' не содержит таблицы маркера владения "
            f"'{MARKER_TABLE_NAME}'. Очистка и запуск тестов запрещены."
        )

    # 3. Проверяем запись маркера
    marker_stmt = text(
        f"SELECT environment, is_safe_to_truncate FROM {MARKER_TABLE_NAME} WHERE marker_id = :mid"
    )
    res_marker = await conn.execute(marker_stmt, {"mid": MARKER_ID})
    row = res_marker.fetchone()
    if not row:
        raise TestDatabaseSafetyError(
            f"ОШИБКА G4-DB: В таблице '{MARKER_TABLE_NAME}' базы '{current_db}' отсутствует запись маркера "
            f"'{MARKER_ID}'. Очистка запрещена."
        )

    env, is_safe = row[0], row[1]
    if env != EXPECTED_ENVIRONMENT or not is_safe:
        raise TestDatabaseSafetyError(
            f"ОШИБКА G4-DB: Маркер владения базы '{current_db}' недействителен (env='{env}', is_safe={is_safe}). "
            "Очистка запрещена!"
        )


async def safe_truncate_test_tables(session: AsyncSession) -> None:
    """
    Безопасная очистка изменяемых таблиц тестовой базы данных.
    Перед TRUNCATE обязательно вызывается verify_test_database_marker.
    При малейшем несоответствии операция прерывается без выполнения TRUNCATE.
    """
    await verify_test_database_marker(session)

    truncate_sql = text(
        "TRUNCATE TABLE audit_events, authorization_codes, refresh_tokens, "
        "oidc_redirect_uris, oidc_clients, sessions, password_credentials, "
        "user_roles, users, recovery_codes, email_verification_tokens, "
        "webauthn_challenges, webauthn_credentials, totp_credentials CASCADE;"
    )
    await session.execute(truncate_sql)
