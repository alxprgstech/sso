"""
Комплексные тесты механизмов защиты тестовой базы данных PostgreSQL (G4-DB, QA-02, BUG-010).
Проверяют негативные и позитивные сценарии изоляции, маскирование DSN,
запрет fallback на DATABASE_URL и сохранение данных в контрольной БД.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.db_guard import (
    FORBIDDEN_DATABASES,
    MARKER_ID,
    MARKER_TABLE_NAME,
    TestDatabaseSafetyError,
    get_test_database_url,
    mask_dsn,
    safe_truncate_test_tables,
    verify_test_database_marker,
)


def test_mask_dsn():
    """Проверка корректного маскирования пароля в DSN."""
    url = "postgresql+psycopg://myuser:superSecretPassword123!@localhost:5433/my_test_db"
    masked = mask_dsn(url)
    assert "superSecretPassword123!" not in masked
    assert "myuser:***@localhost:5433/my_test_db" in masked


def test_get_test_database_url_missing_env(monkeypatch: pytest.MonkeyPatch):
    """
    Негативный тест: при отсутствии TEST_DATABASE_URL выбрасывается
    понятное исключение TestDatabaseSafetyError до любых обращений к сети/БД.
    """
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(TestDatabaseSafetyError) as exc_info:
        get_test_database_url()
    assert "TEST_DATABASE_URL не задана" in str(exc_info.value)


def test_get_test_database_url_no_fallback_to_generic_database_url(monkeypatch: pytest.MonkeyPatch):
    """
    Негативный тест: наличие только DATABASE_URL категорически не используется
    в качестве fallback и вызывает явный отказ с предупреждением.
    """
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://sso_user:pass@localhost:5432/sso_db")

    with pytest.raises(TestDatabaseSafetyError) as exc_info:
        get_test_database_url()
    msg = str(exc_info.value)
    assert "TEST_DATABASE_URL не задана" in msg
    assert "fallback на неё строго запрещён" in msg


@pytest.mark.parametrize("forbidden_db", list(FORBIDDEN_DATABASES))
def test_get_test_database_url_forbidden_database_names(
    forbidden_db: str, monkeypatch: pytest.MonkeyPatch
):
    """
    Негативный тест: передача боевых или системных баз данных (sso_db, postgres, prod и т.д.)
    в TEST_DATABASE_URL блокируется до подключения.
    """
    url = f"postgresql+psycopg://user:secret@localhost:5432/{forbidden_db}"
    monkeypatch.setenv("TEST_DATABASE_URL", url)

    with pytest.raises(TestDatabaseSafetyError) as exc_info:
        get_test_database_url()
    assert f"запрещённую рабочую базу данных '{forbidden_db}'" in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


def test_get_test_database_url_requires_test_in_name(monkeypatch: pytest.MonkeyPatch):
    """
    Негативный тест: имя базы без подстроки 'test' отклоняется.
    """
    url = "postgresql+psycopg://user:secret@localhost:5432/custom_database"
    monkeypatch.setenv("TEST_DATABASE_URL", url)

    with pytest.raises(TestDatabaseSafetyError) as exc_info:
        get_test_database_url()
    assert "не содержит маркер 'test'" in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_guard_rejects_missing_marker_and_preserves_control_data(
    pg_session: AsyncSession, pg_engine: AsyncEngine
):
    """
    Негативный тест безопасности маркера владения:
    Если маркерная таблица отсутствует или запись удалена, safe_truncate_test_tables
    ОБЯЗАН выбросить исключение ДО выполнения TRUNCATE, сохранив контрольные данные.
    """
    control_table = f"control_data_{uuid.uuid4().hex[:8]}"
    async with pg_engine.begin() as conn:
        await conn.execute(
            text(f"CREATE TABLE IF NOT EXISTS {control_table} (id INT PRIMARY KEY, payload TEXT);")
        )
        await conn.execute(
            text(
                f"INSERT INTO {control_table} (id, payload) VALUES (1, 'CRITICAL_DATA_PRESERVED');"
            )
        )
        # Временно переименовываем маркерную таблицу, имитируя неразмеченную БД
        await conn.execute(
            text(f"ALTER TABLE {MARKER_TABLE_NAME} RENAME TO {MARKER_TABLE_NAME}_hidden;")
        )

    try:
        # Попытка очистки должна немедленно упасть
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            await safe_truncate_test_tables(pg_session)
        assert "не содержит таблицы маркера владения" in str(exc_info.value)
    finally:
        # Восстанавливаем имя маркерной таблицы на чистом соединении движка
        async with pg_engine.begin() as conn:
            check_hidden = await conn.execute(
                text(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables "
                    "  WHERE table_schema = 'public' AND table_name = :tbl"
                    ")"
                ),
                {"tbl": f"{MARKER_TABLE_NAME}_hidden"},
            )
            if check_hidden.scalar_one():
                await conn.execute(
                    text(f"ALTER TABLE {MARKER_TABLE_NAME}_hidden RENAME TO {MARKER_TABLE_NAME};")
                )

    # Проверяем, что контрольные данные не тронуты
    async with pg_engine.begin() as conn:
        res = await conn.execute(text(f"SELECT payload FROM {control_table} WHERE id = 1;"))
        assert res.scalar_one() == "CRITICAL_DATA_PRESERVED"
        await conn.execute(text(f"DROP TABLE IF EXISTS {control_table};"))


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_guard_rejects_invalid_marker_environment_or_unsafe(
    pg_session: AsyncSession, pg_engine: AsyncEngine
):
    """
    Негативный тест: если маркер существует, но помечен как is_safe_to_truncate=False
    или принадлежит другому окружению, очистка немедленно блокируется.
    """
    # Устанавливаем флаг is_safe_to_truncate = False
    async with pg_engine.begin() as conn:
        await conn.execute(
            text(
                f"UPDATE {MARKER_TABLE_NAME} SET is_safe_to_truncate = FALSE WHERE marker_id = :mid"
            ),
            {"mid": MARKER_ID},
        )

    try:
        with pytest.raises(TestDatabaseSafetyError) as exc_info:
            await safe_truncate_test_tables(pg_session)
        assert "Маркер владения базы" in str(exc_info.value)
        assert "is_safe=False" in str(exc_info.value)
    finally:
        # Возвращаем валидное состояние на чистом соединении
        async with pg_engine.begin() as conn:
            await conn.execute(
                text(
                    f"UPDATE {MARKER_TABLE_NAME} SET is_safe_to_truncate = TRUE WHERE marker_id = :mid"
                ),
                {"mid": MARKER_ID},
            )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_guard_positive_verified_isolated_circuit(pg_session: AsyncSession):
    """
    Положительный тест: подтвержденная тестовая база с корректным маркером
    успешно проходит верификацию и безопасную очистку, не затрагивая соседние базы.
    """
    # 1. Проверяем маркер
    await verify_test_database_marker(pg_session)

    # 2. Выполняем очистку
    await safe_truncate_test_tables(pg_session)

    # 3. Вставляем временную запись пользователя в тестовую БД
    user_id = uuid.uuid4()
    await pg_session.execute(
        text(
            "INSERT INTO users (id, username, email, is_active, is_superuser, email_verified) "
            "VALUES (:uid, 'test_circuit_user', 'circuit@alxprgs.tech', true, false, false)"
        ),
        {"uid": user_id},
    )
    await pg_session.commit()

    # 4. Проверяем наличие записи
    chk = await pg_session.execute(
        text("SELECT username FROM users WHERE id = :uid"), {"uid": user_id}
    )
    assert chk.scalar_one() == "test_circuit_user"

    # 5. Очищаем снова
    await safe_truncate_test_tables(pg_session)

    # 6. Проверяем, что очищено
    chk2 = await pg_session.execute(
        text("SELECT count(*) FROM users WHERE id = :uid"), {"uid": user_id}
    )
    assert chk2.scalar_one() == 0
