import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_connection_and_ddl(pg_session: AsyncSession):
    """
    QA-02: Проверка реального подключения к PostgreSQL, выполнения запросов
    и валидации структуры таблиц.
    """
    res = await pg_session.execute(text("SELECT version();"))
    version = res.scalar_one()
    assert "PostgreSQL 16" in version

    # Проверяем наличие таблицы system_configuration
    cfg = await pg_session.execute(
        text(
            "SELECT id, bootstrap_completed, registration_mode FROM system_configuration WHERE id = 1"
        )
    )
    row = cfg.fetchone()
    assert row is not None
    assert row[0] == 1
    assert row[1] is False
    assert row[2] == "closed"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_api_client_capabilities(pg_client: httpx.AsyncClient):
    """
    QA-02: Проверка обращения FastAPI к реальной PostgreSQL через pg_client.
    """
    response = await pg_client.get("/api/v1/auth/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["registration_mode"] == "closed"
    assert data["totp_enabled"] is False
    assert data["passkey_enabled"] is False
