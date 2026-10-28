"""Unit checks: readiness cancels a stalled DB operation and returns fail-closed 503."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from app import main

COMMIT = "a" * 40


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


@pytest.mark.asyncio
async def test_identity_endpoint_returns_exact_sha_and_is_not_cacheable(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_build_info",
        lambda: {"version": "0.3.0", "commit_sha": COMMIT, "release": "sso@0.3.0"},
    )
    db = AsyncMock()
    response = await main.health_identity(db)
    assert response.status_code == 200
    assert json.loads(response.body) == {
        "status": "ready",
        "database": "connected",
        "commit_sha": COMMIT,
    }
    assert response.headers["Cache-Control"] == "no-store"
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_identity_endpoint_fails_closed_without_ready_database(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_build_info",
        lambda: {"version": "0.3.0", "commit_sha": COMMIT, "release": "sso@0.3.0"},
    )
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("database unavailable")
    response = await main.health_identity(db)
    assert response.status_code == 503
    assert json.loads(response.body)["status"] == "unavailable"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_identity_endpoint_never_claims_installed_without_build_metadata(monkeypatch):
    monkeypatch.setattr(main, "get_build_info", lambda: {"commit_sha": ""})
    db = AsyncMock()
    response = await main.health_identity(db)
    assert response.status_code == 503
    assert json.loads(response.body)["commit_sha"] == ""
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_identity_endpoint_rejects_malformed_build_metadata(monkeypatch):
    def broken():
        raise ValueError("malformed artifact")

    monkeypatch.setattr(main, "get_build_info", broken)
    response = await main.health_identity(AsyncMock())
    assert response.status_code == 503
    assert json.loads(response.body)["commit_sha"] == ""
