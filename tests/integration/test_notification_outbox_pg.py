import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from app.config import Settings
from app.core.security import hash_password, verify_password
from app.models.audit import AuditEvent
from app.models.notification import SecurityNotification
from app.models.user import PasswordCredential, User
from app.services import notification_service
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.notification_service import dispatch, enqueue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]


async def owner(db):
    user = User(
        username="notice_owner", email="previous@example.test", email_verified=True, is_active=True
    )
    db.add(user)
    await db.flush()
    return user


async def test_outbox_and_audit_rollback_with_mutation(pg_session):
    user = await owner(pg_session)
    await pg_session.commit()
    await AuditService.log_event(pg_session, "password_change", user_id=user.id, commit=False)
    assert await pg_session.scalar(select(func.count(SecurityNotification.id))) == 1
    await pg_session.rollback()
    assert await pg_session.scalar(select(func.count(SecurityNotification.id))) == 0
    assert await pg_session.scalar(select(func.count(AuditEvent.id))) == 0


async def test_outbox_targets_previous_verified_address_and_retries(pg_session, monkeypatch):
    user = await owner(pg_session)
    enqueue(pg_session, user, "email_changed")
    user.email = "new@example.test"
    user.email_verified = False
    enqueue(pg_session, user, "password_change")
    await pg_session.commit()
    provider = AsyncMock(side_effect=RuntimeError("sensitive provider detail"))
    monkeypatch.setattr(notification_service, "deliver_message", provider)
    assert await dispatch(pg_session, Settings(_env_file=None)) == 0
    row = await pg_session.scalar(select(SecurityNotification))
    assert row.attempts == 1 and row.recipient == "previous@example.test"
    message = provider.call_args.args[0]
    assert message["To"] == "previous@example.test" and message["From"]
    assert "sensitive provider detail" not in message.as_string()
    assert await dispatch(pg_session, Settings(_env_file=None)) == 0
    provider.assert_awaited_once()
    row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await pg_session.commit()
    provider.side_effect = None
    assert await dispatch(pg_session, Settings(_env_file=None)) == 1
    assert await pg_session.scalar(select(func.count(SecurityNotification.id))) == 0


async def test_outbox_skip_locked_workers_and_retention(pg_session, pg_engine, monkeypatch):
    user = await owner(pg_session)
    for _ in range(4):
        enqueue(pg_session, user, "password_change")
    await pg_session.commit()
    provider = AsyncMock()
    monkeypatch.setattr(notification_service, "deliver_message", provider)
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def worker():
        async with sessions() as db:
            return await dispatch(db, Settings(_env_file=None), limit=2)

    assert sum(await asyncio.gather(worker(), worker())) == 4
    assert provider.await_count == 4
    enqueue(pg_session, user, "password_change")
    await pg_session.flush()
    row = await pg_session.scalar(select(SecurityNotification))
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await pg_session.commit()
    assert await dispatch(pg_session, Settings(_env_file=None)) == 0
    assert provider.await_count == 4
    assert await pg_session.scalar(select(func.count(SecurityNotification.id))) == 0


async def test_outbox_fifth_failure_removes_recipient_data(pg_session, monkeypatch):
    user = await owner(pg_session)
    enqueue(pg_session, user, "password_change")
    await pg_session.flush()
    row = await pg_session.scalar(select(SecurityNotification))
    row.attempts = 4
    await pg_session.commit()
    provider = AsyncMock(side_effect=RuntimeError("provider failed"))
    monkeypatch.setattr(notification_service, "deliver_message", provider)
    assert await dispatch(pg_session, Settings(_env_file=None)) == 0
    assert await pg_session.scalar(select(func.count(SecurityNotification.id))) == 0
    provider.assert_awaited_once()


async def test_outbox_rechecks_expiry_after_previous_slow_delivery(pg_session, monkeypatch):
    user = await owner(pg_session)
    for _ in range(2):
        enqueue(pg_session, user, "password_change")
    await pg_session.flush()
    clock = datetime.now(timezone.utc)
    for row in (await pg_session.scalars(select(SecurityNotification))).all():
        row.next_attempt_at = clock
        row.expires_at = clock + timedelta(minutes=1)
    await pg_session.commit()

    class Clock:
        @staticmethod
        def now(zone):
            return clock

    async def deliver(message, settings):
        nonlocal clock
        clock += timedelta(minutes=2)

    provider = AsyncMock(side_effect=deliver)
    monkeypatch.setattr(notification_service, "datetime", Clock)
    monkeypatch.setattr(notification_service, "deliver_message", provider)
    assert await dispatch(pg_session, Settings(_env_file=None)) == 1
    provider.assert_awaited_once()
    assert await pg_session.scalar(select(func.count(SecurityNotification.id))) == 0


async def test_password_mutation_and_notice_rollback_on_audit_failure(
    pg_session, pg_engine, monkeypatch
):
    user = await owner(pg_session)
    password = "SyntheticOutboxRegression2026!"  # pragma: allowlist secret -- isolated fixture
    pg_session.add(PasswordCredential(user_id=user.id, password_hash=hash_password(password)))
    await pg_session.commit()
    identifier = user.id
    original = AuditService.log_event

    async def fail_after_audit(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(AuditService, "log_event", fail_after_audit)
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with sessions() as db:
        with pytest.raises(RuntimeError, match="audit failure"):
            async with db.begin():
                await AuthService.change_password(
                    db, user, password, "SyntheticChangedPassword2026!"
                )
    async with sessions() as db:
        stored = await db.scalar(
            select(PasswordCredential.password_hash).where(PasswordCredential.user_id == identifier)
        )
        assert verify_password(password, stored)
        assert await db.scalar(select(func.count(SecurityNotification.id))) == 0
        assert await db.scalar(select(func.count(AuditEvent.id))) == 0
