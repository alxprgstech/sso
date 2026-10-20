"""SSO-SEC-0005: mailbox and initiating-browser proofs must describe the same flow."""

import re
from secrets import token_urlsafe
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from app.legal import REQUIRED_DOCUMENTS
from app.main import app
from app.models.user import User
from app.services import registration_service
from sqlalchemy import func, select, text

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
VICTIM_PASSWORD = token_urlsafe(32)
ATTACKER_PASSWORD = token_urlsafe(32)


@pytest.mark.parametrize("attacker_first", [False, True])
@pytest.mark.parametrize("method", ["code", "link"])
async def test_replaced_flow_cannot_be_confirmed_by_another_browser(
    pg_session, pg_client, monkeypatch, attacker_first, method
):
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed=true, registration_mode='open' WHERE id=1"
        )
    )
    await pg_session.commit()
    messages = []

    async def capture(message, settings):
        messages.append(message)

    monkeypatch.setattr(registration_service, "deliver_message", capture)
    transport = httpx.ASGITransport(app=app, client=("192.0.2.93", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as attacker:

        async def start(browser, name, password):
            reply = await browser.post(
                "/api/v1/auth/register",
                json={
                    "username": name,
                    "email": "victim@example.test",
                    "password": password,
                    "confirm_password": password,
                    "terms_accepted": True,
                    "data_processing_consent": True,
                    "legal_versions": REQUIRED_DOCUMENTS,
                },
            )
            assert reply.status_code == 202
            assert "HttpOnly" in reply.headers["set-cookie"]
            assert "SameSite=lax" in reply.headers["set-cookie"]
            return reply.json()["challenge_id"]

        if attacker_first:
            await start(attacker, "attacker", ATTACKER_PASSWORD)
            current = await start(pg_client, "victim", VICTIM_PASSWORD)
            stale, owner = attacker, pg_client
        else:
            await start(pg_client, "victim", VICTIM_PASSWORD)
            current = await start(attacker, "attacker", ATTACKER_PASSWORD)
            stale, owner = pg_client, attacker
        plain = messages[-1].get_body(preferencelist=("plain",)).get_content()
        code = re.search(r"Ваш код подтверждения: ([0-9]{6})", plain).group(1)
        url = re.search(r"https?://\S+/verify-email\?\S+", plain).group(0)
        link = parse_qs(urlsplit(url).query)["token"][0]
        path = f"/api/v1/auth/register/confirm-{method}"
        payload = {"challenge_id": current, "code": code} if method == "code" else {"token": link}
        # The victim opening the replacement email must not create the attacker's account.
        assert (await stale.post(path, json=payload)).status_code == 401
        assert (
            await stale.post("/api/v1/auth/register/resend", json={"challenge_id": current})
        ).status_code == 401
        assert await pg_session.scalar(select(func.count(User.id))) == 0
        # A copied mail link alone, in a browser with no enrollment cookie, is insufficient.
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as stranger:
            assert (await stranger.post(path, json=payload)).status_code == 401
        assert (
            await owner.post(path, json=payload, headers={"Origin": "https://foreign.example.test"})
        ).status_code == 403
        if not attacker_first:
            # The victim restarts deliberately; its new credentials/proof replace the stale flow.
            current = await start(pg_client, "victim", VICTIM_PASSWORD)
            plain = messages[-1].get_body(preferencelist=("plain",)).get_content()
            code = re.search(r"Ваш код подтверждения: ([0-9]{6})", plain).group(1)
            url = re.search(r"https?://\S+/verify-email\?\S+", plain).group(0)
            payload = (
                {"challenge_id": current, "code": code}
                if method == "code"
                else {"token": parse_qs(urlsplit(url).query)["token"][0]}
            )
            owner = pg_client
        assert (await owner.post(path, json=payload)).status_code == 200
        assert (await owner.post(path, json=payload)).status_code == 401
        user = await pg_session.scalar(select(User))
        assert user.username == "victim" and user.email_verified and not user.is_superuser
        assert (
            await pg_client.post(
                "/api/v1/auth/login", json={"username": "attacker", "password": ATTACKER_PASSWORD}
            )
        ).status_code == 401
        assert (
            await pg_client.post(
                "/api/v1/auth/login", json={"username": "victim", "password": VICTIM_PASSWORD}
            )
        ).status_code == 200


async def test_legacy_pending_without_browser_hash_fails_closed(pg_session):
    from app.config import get_settings
    from app.services.registration_service import RegistrationService
    from fastapi import HTTPException

    from tests.integration.test_gmail_action_binding_pg import pending

    row, action, cfg, browser = await pending(pg_session)
    identifier = row.id
    row.browser_secret_hash = None
    await pg_session.commit()
    for kwargs in (
        {"link": "synthetic-link"},
        {"action_id": identifier, "action_token": action},
        {"challenge_id": identifier, "code": "123456"},
    ):
        with pytest.raises(HTTPException):
            await RegistrationService.confirm(
                pg_session, settings=cfg, browser_secret=browser, **kwargs
            )
        await pg_session.rollback()
    with pytest.raises(HTTPException):
        await RegistrationService.resend(
            pg_session, identifier, "192.0.2.40", get_settings(), browser_secret=browser
        )
    assert await pg_session.scalar(select(func.count(User.id))) == 0


async def test_neutral_resend_keeps_browser_proof_even_when_send_budget_is_exhausted(
    pg_session, pg_client, monkeypatch
):
    """Combined #17/#19: neutral replies must never bypass the originating browser."""
    import uuid

    from tests.integration.test_registration_uniform_path_pg import payload, prepare

    await prepare(pg_session)
    messages = []

    async def capture(message, settings):
        messages.append(message)

    monkeypatch.setattr(registration_service, "deliver_message", capture)
    identifier = None
    owner_cookies = None
    for source in (151, 152, 153):
        transport = httpx.ASGITransport(app=app, client=(f"192.0.2.{source}", 123))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as browser:
            reply = await browser.post("/api/v1/auth/register", json=payload(True))
            assert reply.status_code == 202
            if identifier is not None:
                assert reply.json()["challenge_id"] == identifier
            identifier = reply.json()["challenge_id"]
            owner_cookies = httpx.Cookies(browser.cookies)
    transport = httpx.ASGITransport(app=app, client=("192.0.2.154", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as stranger:
        assert (
            await stranger.post("/api/v1/auth/register/resend", json={"challenge_id": identifier})
        ).status_code == 401
        reply = await stranger.post(
            "/api/v1/auth/register/resend", json={"challenge_id": str(uuid.uuid4())}
        )
        assert reply.status_code == 202
    transport = httpx.ASGITransport(app=app, client=("192.0.2.155", 123))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", cookies=owner_cookies
    ) as owner:
        reply = await owner.post("/api/v1/auth/register/resend", json={"challenge_id": identifier})
        assert reply.status_code == 202 and reply.json()["challenge_id"] == identifier
    assert len(messages) == 3
    assert await pg_session.scalar(select(func.count(User.id))) == 1
