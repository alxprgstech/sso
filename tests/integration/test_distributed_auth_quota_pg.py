"""Two independent Python server processes share the login attempt budget."""

import asyncio
import json
import os
import subprocess
import sys

import pytest

WORKER = """
import asyncio, json
from fastapi import HTTPException
from app.config import get_settings
from app.database import async_session_maker, engine
from app.services.auth_service import AuthService
from tests.db_guard import verify_test_database_marker
async def run():
    results = []
    async with async_session_maker() as db:
        await verify_test_database_marker(db)
        await db.rollback()
        for _ in range(4):
            try:
                await AuthService.authenticate_user(db, 'shared_absent_user', 'WrongSyntheticPassword2026!', settings=get_settings())
            except HTTPException as error:
                results.append(error.status_code)
            await db.rollback()
    await engine.dispose()
    print(json.dumps(results))
asyncio.run(run())
"""


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_two_process_login_quota_survives_failed_password_rollback(pg_session):
    # The fixture verified and cleared only the explicitly marked test database.
    async def worker():
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", WORKER],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "Independent login worker failed (no DSN logged)"
        return json.loads(result.stdout.strip().splitlines()[-1])

    groups = await asyncio.gather(worker(), worker())
    statuses = [status for group in groups for status in group]
    assert statuses.count(401) == 5
    assert statuses.count(429) == 3
    # A new process also sees the consumed budget, rather than resetting it.
    assert await worker() == [429] * 4
