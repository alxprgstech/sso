"""SSO-SEC-0003: repeated IDs, mail budgets and delivery errors reveal no membership."""

from secrets import token_urlsafe

import httpx
import pytest
from app.legal import REQUIRED_DOCUMENTS
from app.main import app
from app.models.user import User
from app.services import registration_service
from app.services.ses_email import SESEmailDeliveryError
from app.services.verification_email import MAX_SENDS
from sqlalchemy import func, select, text

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]


async def prepare(db):
    db.add(User(username="occupied", email="occupied@example.test"))
    await db.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed=true, registration_mode='open' WHERE id=1"
        )
    )
    await db.commit()


def payload(occupied):
    credential = token_urlsafe(32)
    return {
        "username": "occupied" if occupied else "available",
        "email": "probe-occupied@example.test" if occupied else "probe-available@example.test",
        "password": credential,
        "confirm_password": credential,
        "terms_accepted": True,
        "data_processing_consent": True,
        "legal_versions": REQUIRED_DOCUMENTS,
    }


async def test_repeated_start_ids_and_send_cap_are_identical(pg_session, pg_client, monkeypatch):
    await prepare(pg_session)
    messages = []

    async def capture(message, settings):
        messages.append(message)

    monkeypatch.setattr(registration_service, "deliver_message", capture)
    statuses = {False: [], True: []}
    identifiers = {False: set(), True: set()}
    assert MAX_SENDS == 3
    for attempt in range(4):
        transport = httpx.ASGITransport(app=app, client=(f"192.0.2.{120 + attempt}", 123))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as source:
            for occupied in (False, True):
                reply = await source.post("/api/v1/auth/register", json=payload(occupied))
                statuses[occupied].append(reply.status_code)
                if reply.status_code == 202:
                    identifiers[occupied].add(reply.json()["challenge_id"])
    assert statuses[False] == statuses[True] == [202] * 3 + [429]
    assert len(identifiers[False]) == len(identifiers[True]) == 1
    assert len(messages) == 6
    assert await pg_session.scalar(select(func.count(User.id))) == 1


async def test_delivery_error_contract_is_identical_and_cannot_create_users(
    pg_session, pg_client, monkeypatch
):
    await prepare(pg_session)

    async def fail(message, settings):
        raise SESEmailDeliveryError("credentials_unavailable")

    monkeypatch.setattr(registration_service, "deliver_message", fail)
    replies = [
        await pg_client.post("/api/v1/auth/register", json=payload(occupied))
        for occupied in (False, True)
    ]
    assert [reply.status_code for reply in replies] == [503, 503]
    assert replies[0].json() == replies[1].json() == {"detail": {"error": "email_delivery_failed"}}
    assert await pg_session.scalar(select(func.count(User.id))) == 1
