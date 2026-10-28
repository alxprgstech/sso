"""Admin RBAC is decided before any reauthentication challenge is issued."""

import secrets
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from app.api.deps import generate_csrf_token
from app.config import get_settings
from app.core.security import generate_random_token, hash_password, hash_token
from app.models.authentication import SecurityAuthorization
from app.models.session import Session
from app.models.user import PasswordCredential, User
from sqlalchemy import select

from tests.helpers.privacy import record_test_consent

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
PASSWORD = f"Synth{secrets.token_urlsafe(18)}"


async def _regular_session(pg_session, pg_client) -> tuple[dict[str, str], User]:
    user = User(username="order_regular", email="order_regular@example.test")
    user.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    pg_session.add(user)
    await pg_session.flush()
    await record_test_consent(pg_session, user)
    now = datetime.now(timezone.utc)
    raw = generate_random_token(32)
    session = Session(
        user_id=user.id,
        session_token_hash=hash_token(raw),
        expires_at=now + timedelta(hours=1),
        last_activity_at=now,
        purpose="full",
        security_revision=user.security_revision,
        auth_time=now,
        mfa_verified=False,
        amr="pwd",
    )
    pg_session.add(session)
    await pg_session.commit()
    pg_client.cookies.set("alx_session", raw, path="/")
    return {"X-CSRF-Token": generate_csrf_token(session.id, get_settings())}, user


async def test_regular_user_gets_403_without_a_reauth_challenge(pg_session, pg_client):
    headers, _ = await _regular_session(pg_session, pg_client)
    payload = {
        "client_name": "Should never be created",
        "client_type": "public",
        "redirect_uris": ["https://service.example.test/callback"],
    }
    response = await pg_client.post("/api/v1/admin/clients", headers=headers, json=payload)
    assert response.status_code == 403, response.json()
    assert response.json()["error"] == "forbidden"
    # No fresh-factor challenge may be created for an identity that cannot act.
    rows = await pg_session.scalars(select(SecurityAuthorization))
    assert rows.all() == []
    # Read endpoints follow the same order and remain denied.
    assert (await pg_client.get("/api/v1/admin/users", headers=headers)).status_code == 403


async def test_anonymous_admin_request_stays_401(pg_client: httpx.AsyncClient):
    response = await pg_client.post(
        "/api/v1/admin/users",
        json={"username": "x", "email": "x@example.test", "password": secrets.token_urlsafe(16)},
    )
    assert response.status_code == 401


async def test_admin_without_assurance_still_gets_explicit_mfa_error(pg_session, pg_client):
    user = User(username="order_admin", email="order_admin@example.test", is_superuser=True)
    user.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    pg_session.add(user)
    await pg_session.flush()
    await record_test_consent(pg_session, user)
    now = datetime.now(timezone.utc)
    raw = generate_random_token(32)
    session = Session(
        user_id=user.id,
        session_token_hash=hash_token(raw),
        expires_at=now + timedelta(hours=1),
        last_activity_at=now,
        purpose="full",
        security_revision=user.security_revision,
        auth_time=now,
        mfa_verified=False,
        amr="pwd",
    )
    pg_session.add(session)
    await pg_session.commit()
    pg_client.cookies.set("alx_session", raw, path="/")
    headers = {"X-CSRF-Token": generate_csrf_token(session.id, get_settings())}
    response = await pg_client.post("/api/v1/admin/users", headers=headers, json={"username": "y"})
    assert response.status_code == 403
    assert response.json()["error"] == "admin_mfa_required"
    assert (await pg_client.get("/api/v1/admin/users")).json()["error"] == "admin_mfa_required"
