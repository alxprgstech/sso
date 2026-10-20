"""Bounded cardinality/counts and transactional failure recovery, explicit unit doubles."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from app.services.denied_audit import MAX_COUNT, MAX_ROUTES, DeniedAuditBuffer


@pytest.mark.asyncio
async def test_cardinality_and_all_statuses_preserve_overflow_counts(monkeypatch):
    buffer = DeniedAuditBuffer()
    for index in range(300):
        for status in (401, 403, 429):
            buffer.record(f"route_{index}", status)
    assert len(buffer._counts) <= MAX_ROUTES + 3
    assert sum(buffer._counts.values()) == 900
    buffer.record("bounded", 401, MAX_COUNT)
    buffer.record("bounded", 401, MAX_COUNT)
    assert max(buffer._counts.values()) == MAX_COUNT


@pytest.mark.asyncio
async def test_failed_batch_is_rolled_back_and_recounted(monkeypatch):
    buffer = DeniedAuditBuffer()
    buffer.record("get_me", 401, 20)
    db = AsyncMock()
    db.commit.side_effect = RuntimeError("synthetic database outage")
    writer = AsyncMock()
    monkeypatch.setattr("app.services.denied_audit.AuditService.log_event", writer)
    with pytest.raises(RuntimeError):
        await buffer.flush(db)
    db.rollback.assert_awaited_once()
    assert sum(buffer._counts.values()) == 20
    db.commit.side_effect = None
    await buffer.flush(db)
    assert not buffer._counts
    assert writer.await_args.kwargs["details"]["count"] == 20


@pytest.mark.asyncio
async def test_concurrent_flush_and_rollback_failure_keep_bounded_counts(monkeypatch):
    buffer = DeniedAuditBuffer()
    buffer.record("get_me", 401, 10)
    started, release = asyncio.Event(), asyncio.Event()

    async def blocked_write(*args, **kwargs):
        started.set()
        await release.wait()
        raise RuntimeError("synthetic write failure")

    monkeypatch.setattr("app.services.denied_audit.AuditService.log_event", blocked_write)
    db = AsyncMock()
    db.rollback.side_effect = RuntimeError("synthetic rollback failure")
    task = asyncio.create_task(buffer.flush(db))
    await started.wait()
    buffer.record("get_me", 401, 5)
    other_db = AsyncMock()
    await buffer.flush(other_db)
    other_db.commit.assert_not_awaited()
    release.set()
    with pytest.raises(RuntimeError):
        await task
    assert sum(buffer._counts.values()) == 15
    assert not buffer._flushing
