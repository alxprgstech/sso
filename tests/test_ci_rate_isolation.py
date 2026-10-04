"""Case isolation preserves real quotas and refuses cleanup without ownership."""

from datetime import datetime, timedelta, timezone

import pytest
from app.core.rate_limit import IN_MEMORY_MAX_REQUESTS, check_in_memory_rate_limit
from app.models.privacy import PrivacyRateWindow
from fastapi import HTTPException
from sqlalchemy import select, text

from scripts.prepare_e2e_data import reset_e2e_rate_windows
from tests.db_guard import MARKER_TABLE_NAME, TestDatabaseSafetyError


@pytest.mark.parametrize("independent_case", [1, 2])
def test_each_independent_case_enforces_the_entire_process_quota(independent_case):
    # Identical key across cases: only the fixture boundary clears its state.
    for _ in range(IN_MEMORY_MAX_REQUESTS):
        check_in_memory_rate_limit("email_req_127.0.0.1")
    with pytest.raises(HTTPException) as failure:
        check_in_memory_rate_limit("email_req_127.0.0.1")
    assert failure.value.status_code == 429


@pytest.mark.asyncio
async def test_e2e_case_cleanup_requires_a_valid_test_database_marker(pg_session):
    window = PrivacyRateWindow(
        key_hash="a" * 64,
        attempts=40,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    pg_session.add(window)
    await pg_session.commit()
    await pg_session.execute(text(f"DELETE FROM {MARKER_TABLE_NAME}"))
    try:
        with pytest.raises(TestDatabaseSafetyError):
            await reset_e2e_rate_windows(pg_session)
    finally:
        await pg_session.rollback()  # Restore the marker, even on a failed assertion.
    assert (await pg_session.execute(select(PrivacyRateWindow.attempts))).scalar_one() == 40
    await reset_e2e_rate_windows(pg_session)
    await pg_session.commit()
    assert (await pg_session.execute(select(PrivacyRateWindow))).scalar_one_or_none() is None
