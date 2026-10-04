import json
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.config import Settings
from app.core.security import decrypt_totp_secret, hash_password
from app.models.authentication import SecurityAuthorization
from app.models.mfa import TOTPCredential
from app.models.user import PasswordCredential, User
from app.services.auth_service import AuthService
from app.services.mfa_service import TOTPService
from app.services.reauthentication_service import payload_digest
from sqlalchemy import select

from tests.helpers.privacy import accept_current_documents, record_test_consent

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
PASSWORD = "ReauthenticationRegression2026!"


async def login(client, db):
    assert (await execute_bootstrap(db, "proof_admin", "proof@example.test", PASSWORD, "closed"))[
        0
    ] == 0
    response = await client.post(
        "/api/v1/auth/login", json={"username": "proof_admin", "password": PASSWORD}
    )
    await accept_current_documents(client, response)
    return {"X-CSRF-Token": response.json()["csrf_token"]}


async def proof(client, headers, path, payload, password=PASSWORD):
    return await client.post(
        "/api/v1/auth/reauthentication",
        headers=headers,
        json={
            "current_password": password,
            "action": f"POST {path}",
            "payload_hash": payload_digest(json.dumps(payload).encode()),
        },
    )


async def test_sensitive_admin_action_requires_exact_one_use_proof(pg_session, pg_client):
    headers = await login(pg_client, pg_session)
    path = "/api/v1/admin/clients"
    payload = {
        "client_name": "Proof Client",
        "client_type": "public",
        "redirect_uris": ["https://service.example.test/callback"],
    }
    assert (await pg_client.post(path, headers=headers, json=payload)).status_code == 401
    assert (await proof(pg_client, headers, path, payload, "incorrect-password")).status_code == 401
    issued = await proof(pg_client, headers, path, payload)
    assert issued.status_code == 200 and not issued.json()["factor_required"]
    authorized = {**headers, "X-Reauthentication": issued.json()["authorization"]}
    assert (
        await pg_client.post(path, headers=authorized, json={**payload, "client_name": "Changed"})
    ).status_code == 401
    assert (
        await pg_client.post("/api/v1/admin/users", headers=authorized, json={})
    ).status_code == 401
    assert (await pg_client.post(path, headers=authorized, json=payload)).status_code == 201
    assert (await pg_client.post(path, headers=authorized, json=payload)).status_code == 401


async def test_expired_and_other_session_proof_cannot_mutate(pg_session, pg_client):
    headers = await login(pg_client, pg_session)
    path = "/api/v1/admin/clients"
    payload = {
        "client_name": "Expired",
        "client_type": "public",
        "redirect_uris": ["https://service.example.test/callback"],
    }
    issued = await proof(pg_client, headers, path, payload)
    row = await pg_session.scalar(select(SecurityAuthorization))
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await pg_session.commit()
    assert (
        await pg_client.post(
            path,
            json=payload,
            headers={**headers, "X-Reauthentication": issued.json()["authorization"]},
        )
    ).status_code == 401
    issued = await proof(pg_client, headers, path, payload)
    new_login = await pg_client.post(
        "/api/v1/auth/login", json={"username": "proof_admin", "password": PASSWORD}
    )
    headers = {
        "X-CSRF-Token": new_login.json()["csrf_token"],
        "X-Reauthentication": issued.json()["authorization"],
    }
    assert (await pg_client.post(path, headers=headers, json=payload)).status_code == 401


async def test_pending_totp_preserves_active_factor_and_checks_session(pg_session):
    user = User(username="pending_totp", email="pending@example.test")
    user.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    pg_session.add(user)
    await record_test_consent(pg_session, user)
    cfg = Settings(_env_file=None, FEATURE_TOTP_ENABLED=True)
    _, session, _ = await AuthService.create_user_session(pg_session, user.id, None, None, cfg)
    first, _ = await TOTPService.setup_totp(pg_session, user, session.id)
    assert await TOTPService.confirm_totp(pg_session, user, pyotp.TOTP(first).now(), session.id)
    second, _ = await TOTPService.setup_totp(pg_session, user, session.id)
    credential = await pg_session.scalar(select(TOTPCredential))
    assert credential.is_confirmed and decrypt_totp_secret(credential.encrypted_secret) == first
    assert not await TOTPService.confirm_totp(
        pg_session, user, pyotp.TOTP(second).now(), uuid.uuid4()
    )
    assert credential.is_confirmed and decrypt_totp_secret(credential.encrypted_secret) == first
    assert await TOTPService.confirm_totp(pg_session, user, pyotp.TOTP(second).now(), session.id)
    assert decrypt_totp_secret(credential.encrypted_secret) == second
    assert user.security_revision == 2


async def test_proof_from_different_admin_user_does_not_authorize_action(pg_session, pg_client):
    headers = await login(pg_client, pg_session)
    path = "/api/v1/admin/clients"
    payload = {
        "client_name": "Cross-user proof",
        "client_type": "public",
        "redirect_uris": ["https://proof.example.test/callback"],
    }
    foreign = (await proof(pg_client, headers, path, payload)).json()["authorization"]
    other = User(username="second_proof_admin", email="secondproof@example.test", is_superuser=True)
    other.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    pg_session.add(other)
    await record_test_consent(pg_session, other)
    authenticated = await pg_client.post(
        "/api/v1/auth/login", json={"username": other.username, "password": PASSWORD}
    )
    assert authenticated.status_code == 200
    own_headers = {"X-CSRF-Token": authenticated.json()["csrf_token"]}
    assert (
        await pg_client.post(
            path, json=payload, headers={**own_headers, "X-Reauthentication": foreign}
        )
    ).status_code == 401
    own = (await proof(pg_client, own_headers, path, payload)).json()["authorization"]
    assert (
        await pg_client.post(path, json=payload, headers={**own_headers, "X-Reauthentication": own})
    ).status_code == 201
