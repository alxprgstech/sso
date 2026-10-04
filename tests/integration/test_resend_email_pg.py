"""Real guarded PostgreSQL/auth flows with offline Resend HTTP responses."""

import json
import re
import uuid

import httpx
import pytest
import pytest_asyncio
from app.config import Settings, get_settings
from app.legal import REQUIRED_DOCUMENTS
from app.main import app
from app.models.user import User
from app.services import resend_email, verification_email
from app.services.mfa_service import sent_emails_sink
from sqlalchemy import select, text

pytestmark = pytest.mark.postgres
KEY = "re_" + "synthetic-postgres-resend-key"


@pytest_asyncio.fixture
async def resend_transport(pg_session, pg_client, monkeypatch):
    cfg = Settings(
        _env_file=None,
        ENVIRONMENT="testing",
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY=KEY,
        SMTP_HOST="",
        REQUIRE_VERIFIED_EMAIL=True,
    )
    state = {"status": 200, "requests": []}

    def reply(request):
        state["requests"].append(json.loads(request.content))
        return httpx.Response(
            state["status"],
            json={"id": str(uuid.uuid4()), "name": "restricted_api_key", "message": KEY},
        )

    async def submit(message, settings):
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            return await resend_email.send_resend_email(message, settings, client=client)

    def forbidden(*args, **kwargs):
        raise AssertionError("Fallback must never occur")

    monkeypatch.setattr(verification_email, "send_resend_email", submit)
    monkeypatch.setattr(verification_email, "_send_smtp", forbidden)
    monkeypatch.setattr(verification_email, "send_ses_email", forbidden)
    app.dependency_overrides[get_settings] = lambda: cfg
    sent_emails_sink.clear()
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed=true, registration_mode='open' WHERE id=1"
        )
    )
    await pg_session.commit()
    try:
        yield state
    finally:
        app.dependency_overrides.pop(get_settings, None)
        sent_emails_sink.clear()


async def register(client):
    password = "Synthetic" + "Resend2026!"  # pragma: allowlist secret -- synthetic signup
    return await client.post(
        "/api/v1/auth/register",
        json={
            "terms_accepted": True,
            "data_processing_consent": True,
            "legal_versions": REQUIRED_DOCUMENTS,
            "username": "resend_signup",
            "email": "resend_signup@example.test",
            "password": password,
            "confirm_password": password,
        },
    )


def secrets_from_payload(payload):
    code = re.search(r"Ваш код подтверждения: ([0-9]{6})", payload["text"]).group(1)
    token = re.search(r"[?&]token=([A-Za-z0-9_-]+)", payload["text"]).group(1)
    return code, token


@pytest.mark.asyncio
async def test_resend_registration_confirmation_replay_and_resend(
    pg_session, pg_client, resend_transport
):
    response = await register(pg_client)
    assert response.status_code == 202
    assert await pg_session.scalar(select(User).where(User.username == "resend_signup")) is None
    challenge = response.json()["challenge_id"]
    original_code, original_token = secrets_from_payload(resend_transport["requests"][0])
    repeat = await pg_client.post("/api/v1/auth/register/resend", json={"challenge_id": challenge})
    assert repeat.status_code == 202
    assert len(resend_transport["requests"]) == 2
    new_code, new_token = secrets_from_payload(resend_transport["requests"][1])
    assert new_token != original_token
    assert new_code == sent_emails_sink[-1]["code"]
    # No probabilistic assertion that independently generated six-digit codes must differ.
    stale = await pg_client.post(
        "/api/v1/auth/register/confirm-link", json={"token": original_token}
    )
    assert stale.status_code == 401
    confirmed = await pg_client.post(
        "/api/v1/auth/register/confirm-code", json={"challenge_id": challenge, "code": new_code}
    )
    assert confirmed.status_code == 200
    user = await pg_session.scalar(select(User).where(User.username == "resend_signup"))
    assert user.email_verified and not user.is_superuser
    assert [role.name for role in user.roles] == ["user"]
    replay = await pg_client.post("/api/v1/auth/register/confirm-link", json={"token": new_token})
    assert replay.status_code == 401
    assert original_code in resend_transport["requests"][0]["text"]


@pytest.mark.asyncio
async def test_resend_registration_failure_keeps_pending_and_safe_audit(
    pg_session, pg_client, resend_transport
):
    resend_transport["status"] = 403
    response = await register(pg_client)
    assert response.status_code == 503
    assert response.json() == {"detail": {"error": "email_delivery_failed"}}
    assert KEY not in response.text
    assert (
        await pg_session.scalar(
            text("SELECT count(*) FROM pending_registrations WHERE username='resend_signup'")
        )
        == 1
    )
    assert await pg_session.scalar(select(User).where(User.username == "resend_signup")) is None
    audit = await pg_session.scalar(
        text("SELECT details FROM audit_events WHERE event_type='email_delivery_failed'")
    )
    assert_safe_audit(audit, "access_denied")


@pytest.mark.parametrize("status", [200, 429])
@pytest.mark.asyncio
async def test_existing_account_resend_success_and_neutral_failure(
    pg_session, pg_client, resend_transport, status
):
    # Synthetic ordinary admin-created/unverified account; no fabricated confirmation.
    user = User(
        username="resend_existing",
        email="existing@example.test",
        is_active=True,
        email_verified=False,
    )
    pg_session.add(user)
    await pg_session.commit()
    resend_transport["status"] = status
    response = await pg_client.post("/api/v1/mfa/email/request", json={"email": user.email})
    unknown = await pg_client.post(
        "/api/v1/mfa/email/request", json={"email": "unknown@example.test"}
    )
    assert response.status_code == unknown.status_code == 200
    assert response.json() == unknown.json()
    assert len(resend_transport["requests"]) == 1
    assert KEY not in response.text
    if status == 429:
        audit = await pg_session.scalar(
            text("SELECT details FROM audit_events WHERE event_type='email_delivery_failed'")
        )
        assert_safe_audit(audit, "quota_exceeded")
        await pg_session.refresh(user)
        assert not user.email_verified
    else:
        _, token = secrets_from_payload(resend_transport["requests"][0])
        confirmed = await pg_client.post("/api/v1/mfa/email/confirm", json={"token": token})
        assert confirmed.status_code == 200
        await pg_session.refresh(user)
        assert user.email_verified and not user.is_superuser
        replay = await pg_client.post("/api/v1/mfa/email/confirm", json={"token": token})
        assert replay.status_code == 401


def assert_safe_audit(audit, reason):
    assert set(audit) == {"provider", "reason", "request_id"}
    assert audit["provider"] == "resend"
    assert audit["reason"] == reason
    assert str(uuid.UUID(audit["request_id"])) == audit["request_id"]
    assert KEY not in json.dumps(audit)
