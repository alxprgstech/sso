import os
import sys
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

sys.path.insert(0, os.path.abspath("backend"))

from app.api.deps import get_db
from app.core.rbac import ROLE_ADMIN, ROLE_USER
from app.main import app
from app.models.system import SystemConfiguration

from tests.db_guard import (
    TestDatabaseSafetyError,
    get_test_database_url,
    mask_dsn,
    safe_truncate_test_tables,
    verify_test_database_marker,
)


@pytest.fixture
def default_db_mock():
    """
    Явный мок get_db для unit-тестов, которым не требуется подключение к реальной БД.
    """
    mock_session = AsyncMock()
    mock_result = MagicMock()
    default_config = SystemConfiguration(
        id=1,
        bootstrap_completed=True,
        registration_mode="closed",
    )
    mock_result.scalar_one_or_none.return_value = default_config
    mock_result.scalar_one.return_value = default_config
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    async def _mock_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = _mock_get_db
    yield mock_session
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture(scope="session")
async def pg_engine() -> AsyncGenerator[AsyncEngine, None]:
    """
    Создает сессионный движок SQLAlchemy для подключения к PostgreSQL.
    Если PostgreSQL недоступен или TEST_DATABASE_URL не настроен,
    тест падает с понятной ошибкой и маскированным DSN (QA-02, G4-DB).
    """
    try:
        db_url = get_test_database_url()
    except TestDatabaseSafetyError as err:
        pytest.fail(str(err))

    connect_args = {}
    if "asyncpg" in db_url:
        connect_args["timeout"] = 5
    elif "psycopg" in db_url:
        connect_args["connect_timeout"] = 5

    engine = create_async_engine(
        db_url,
        echo=False,
        poolclass=NullPool,
        connect_args=connect_args,
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            # The marker must be provisioned separately on a proven fresh test DB.
            # A fixture must never promote an arbitrary database to a truncate target.
            await verify_test_database_marker(conn)
    except Exception as exc:
        if isinstance(exc, pytest.fail.Exception):
            raise
        pytest.fail(
            f"ОШИБКА QA-02/G4-DB: Тестовая база данных PostgreSQL недоступна по адресу {mask_dsn(db_url)}. "
            f"Убедитесь, что TEST_DATABASE_URL задан корректно и тестовый контейнер alxprgs-sso-test-db "
            f"(порт 5433) запущен. Исключение: {exc}"
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Создает изолированную сессию PostgreSQL для одного теста.
    Автоматически очищает таблицы перед тестом после строгой верификации маркера тестовой БД
    и выполняет rollback при ошибках.
    """
    session_factory = async_sessionmaker(
        bind=pg_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        # Безопасно очищаем данные из изменяемых таблиц с предварительной проверкой маркера
        await safe_truncate_test_tables(session)
        # Гарантируем наличие базовых ролей
        role_admin = await session.execute(
            text("SELECT id FROM roles WHERE name = :name"), {"name": ROLE_ADMIN}
        )
        if not role_admin.scalar_one_or_none():
            await session.execute(
                text(
                    "INSERT INTO roles (id, name, description) "
                    "VALUES (gen_random_uuid(), :name, 'Administrator')"
                ),
                {"name": ROLE_ADMIN},
            )
        role_user = await session.execute(
            text("SELECT id FROM roles WHERE name = :name"), {"name": ROLE_USER}
        )
        if not role_user.scalar_one_or_none():
            await session.execute(
                text(
                    "INSERT INTO roles (id, name, description) "
                    "VALUES (gen_random_uuid(), :name, 'Standard User')"
                ),
                {"name": ROLE_USER},
            )
        # Гарантируем наличие system_configuration (id=1)
        cfg = await session.execute(text("SELECT id FROM system_configuration WHERE id = 1"))
        if not cfg.scalar_one_or_none():
            await session.execute(
                text(
                    "INSERT INTO system_configuration (id, bootstrap_completed, bootstrap_completed_at, registration_mode) "
                    "VALUES (1, false, NULL, 'closed')"
                )
            )
        else:
            await session.execute(
                text(
                    "UPDATE system_configuration SET bootstrap_completed = false, bootstrap_completed_at = NULL, registration_mode = 'closed' WHERE id = 1"
                )
            )
        await session.commit()

        yield session

        await session.rollback()


@pytest_asyncio.fixture
async def pg_client(
    pg_engine: AsyncEngine, pg_session: AsyncSession
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    HTTP-клиент для вызова FastAPI эндпоинтов с независимыми сессиями из реальной PostgreSQL.
    Каждый запрос получает собственную сессию из пула (как в production),
    что гарантирует корректную работу параллелизма и блокировок строк (SELECT FOR UPDATE).
    """
    session_factory = async_sessionmaker(
        bind=pg_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.pop(get_db, None)
