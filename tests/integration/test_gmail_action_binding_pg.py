"""Permanent regression, originating in SEC-01 audit fixture."""

from docs.audit.test_security_audit_20261007 import test_gmail_bearer_reused_for_unrelated_mailboxes

__all__ = ["test_gmail_bearer_reused_for_unrelated_mailboxes"]

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.config import Settings
from app.core.security import generate_random_token, hash_password, hash_token
from app.legal import REQUIRED_DOCUMENTS
from app.models.registration import PendingRegistration
from app.models.user import User
from app.services.registration_service import RegistrationService
from app.services.verification_email import code_hash, link_digest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


async def pending(db):
    now = datetime.now(timezone.utc)
    secret = generate_random_token(32)
    browser = generate_random_token(32)
    identifier = uuid.uuid4()
    cfg = Settings(_env_file=None, ENVIRONMENT="testing")
    row = PendingRegistration(
        id=identifier,
        username="gmail_race",
        email="gmail-race@example.test",
        password_hash=hash_password(generate_random_token(32)),
        code_hash=code_hash(cfg, identifier, "123456"),
        link_hash=link_digest("synthetic-link"),
        action_hash=hash_token(secret),
        browser_secret_hash=hash_token(browser),
        request_details={},
        legal_versions=REQUIRED_DOCUMENTS,
        legal_accepted_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    db.add(row)
    await db.commit()
    return row, secret, cfg, browser


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_gmail_resend_expiry_and_other_confirmation_invalidate_action(
    pg_session, monkeypatch
):
    row, old, cfg, browser = await pending(pg_session)
    captured = []

    async def send(db, pending, code, link, action, settings):
        captured.append(action)

    monkeypatch.setattr(RegistrationService, "_send", send)
    await RegistrationService.resend(pg_session, row.id, "192.0.2.19", cfg, browser_secret=browser)
    assert captured[0] != old and row.action_hash == hash_token(captured[0])
    with pytest.raises(HTTPException):
        await RegistrationService.confirm(
            pg_session, settings=cfg, action_id=row.id, action_token=old, browser_secret=browser
        )
    await pg_session.rollback()
    row = await pg_session.scalar(select(PendingRegistration))
    identifier = row.id
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await pg_session.commit()
    with pytest.raises(HTTPException):
        await RegistrationService.confirm(
            pg_session,
            settings=cfg,
            action_id=identifier,
            action_token=captured[0],
            browser_secret=browser,
        )
    await pg_session.rollback()
    row = await pg_session.scalar(select(PendingRegistration))
    row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    row.action_hash = None  # Simulate a migrated legacy pending registration.
    row.link_hash = link_digest("legacy-safe-link")
    await pg_session.commit()
    with pytest.raises(HTTPException):
        await RegistrationService.confirm(
            pg_session,
            settings=cfg,
            action_id=identifier,
            action_token=captured[0],
            browser_secret=browser,
        )
    await pg_session.rollback()
    assert await RegistrationService.confirm(
        pg_session, settings=cfg, link="legacy-safe-link", browser_secret=browser
    )
    with pytest.raises(HTTPException):
        await RegistrationService.confirm(
            pg_session,
            settings=cfg,
            action_id=identifier,
            action_token=captured[0],
            browser_secret=browser,
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_gmail_concurrent_confirmation_has_one_success(pg_session, pg_engine):
    row, secret, cfg, browser = await pending(pg_session)
    identifier = row.id
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def confirm():
        async with sessions() as db:
            try:
                await RegistrationService.confirm(
                    db,
                    settings=cfg,
                    action_id=identifier,
                    action_token=secret,
                    browser_secret=browser,
                )
                return True
            except HTTPException:
                await db.rollback()
                return False

    assert sum(await asyncio.gather(confirm(), confirm())) == 1
    assert await pg_session.scalar(select(func.count(User.id))) == 1
