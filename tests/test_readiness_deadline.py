"""Unit checks: readiness cancels a stalled DB operation and returns fail-closed 503."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from app import main


@pytest.mark.asyncio
async def test_stalled_database_is_cancelled_before_the_readiness_response(monkeypatch):
    cancelled = asyncio.Event()

    async def stalled_query(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    db = AsyncMock()
    db.execute.side_effect = stalled_query
    monkeypatch.setattr(main, "READINESS_DATABASE_TIMEOUT_SECONDS", 0.01)
    response = await asyncio.wait_for(main.health_ready(db), timeout=1)
    assert response.status_code == 503
    assert response.body == b'{"status":"unavailable","database":"disconnected"}'
    assert cancelled.is_set()
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_database_check_remains_required_for_readiness():
    db = AsyncMock()
    response = await main.health_ready(db)
    assert response.status_code == 200
    db.execute.assert_awaited_once()
