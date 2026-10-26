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
from app.services.auth_service import AuthService, SessionRequest
from app.services.mfa_service import TOTPService
from app.services.reauthentication_service import payload_digest
from sqlalchemy import select

from tests.helpers.mfa import AdminMfaSession, login_admin_with_mfa_direct
from tests.helpers.privacy import record_test_consent
from tests.helpers.reauthentication import MutationRequest

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
PASSWORD = "ReauthenticationRegression2026!"


async def _complete_factor(client, session: AdminMfaSession, started):
    assert started.status_code == 200, started.json()
    data = started.json()
    if data["factor_required"]:
        confirmed = await client.post(
            "/api/v1/auth/reauthentication/factor",
            headers=session.headers,
            json={"authorization": data["authorization"], **session.factor(data)},
        )
        assert confirmed.status_code == 200, confirmed.json()
        data = confirmed.json()
    return data


async def session_proof(
    client,
    session: AdminMfaSession,
    method="GET",
    path="/api/v1/auth/sessions",
):
    started = await client.post(
        "/api/v1/auth/reauthentication",
        headers=session.headers,
        json={
            "current_password": PASSWORD,
            "action": f"{method} {path}",
            "payload_hash": payload_digest(b""),
        },
    )
    data = await _complete_factor(client, session, started)
    return {**session.headers, "X-Reauthentication": data["authorization"]}


async def test_session_read_grant_and_mutation_proof_are_separate(pg_session, pg_client):
    session = await login(pg_client, pg_session)
    path = "/api/v1/auth/sessions"
    assert (await pg_client.get(path)).status_code == 401
    read = await session_proof(pg_client, session)
    assert (await pg_client.get(path, headers=read)).status_code == 200
    assert (await pg_client.get(path, headers=read)).status_code == 200
    assert (await pg_client.delete(path, headers=read)).status_code == 401
    mutation = await session_proof(pg_client, session, "DELETE")
    assert (await pg_client.get(path, headers=mutation)).status_code == 401
    assert (await pg_client.delete(path, headers=mutation)).status_code == 200
    assert (await pg_client.delete(path, headers=mutation)).status_code == 401
    row = await pg_session.scalar(select(SecurityAuthorization))
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await pg_session.commit()
    assert (await pg_client.get(path, headers=read)).status_code == 401


async def test_denied_session_action_uses_trusted_actor_and_redacts_input(pg_session, pg_client):
    from app.models.audit import AuditEvent

    await login(pg_client, pg_session)
    owner_id = await pg_session.scalar(select(User.id))
    response = await pg_client.get(
        "/api/v1/auth/sessions?token=never-record-this", headers={"X-Actor-ID": str(uuid.uuid4())}
    )
    assert response.status_code == 401
    events = (
        await pg_session.scalars(select(AuditEvent).where(AuditEvent.event_type == "action_denied"))
    ).all()
    assert len(events) == 1
    assert events[0].user_id == owner_id
    assert events[0].details["route"] == "list_sessions"
    assert events[0].details["reason"] == "authentication_required"
    assert "never-record-this" not in json.dumps(events[0].details)


async def login(client, db):
    assert (await execute_bootstrap(db, "proof_admin", "proof@example.test", PASSWORD, "closed"))[
        0
    ] == 0
    return await login_admin_with_mfa_direct(db, client, "proof_admin", PASSWORD)


async def proof(client, request: MutationRequest, session: AdminMfaSession):
    path, payload = request.path, request.json_body
    started = await client.post(
        "/api/v1/auth/reauthentication",
        headers=session.headers,
        json={
            "current_password": PASSWORD,
            "action": f"POST {path}",
            "payload_hash": payload_digest(json.dumps(payload).encode()),
        },
    )
    if started.status_code != 200 or not started.json().get("factor_required"):
        return started
    confirmed = await client.post(
        "/api/v1/auth/reauthentication/factor",
        headers=session.headers,
        json={"authorization": started.json()["authorization"], **session.factor(started.json())},
    )
    return confirmed


async def test_sensitive_admin_action_requires_exact_one_use_proof(pg_session, pg_client):
    session = await login(pg_client, pg_session)
    headers = session.headers
    path = "/api/v1/admin/clients"
    payload = {
        "client_name": "Proof Client",
        "client_type": "public",
        "redirect_uris": ["https://service.example.test/callback"],
    }
    assert (await pg_client.post(path, headers=headers, json=payload)).status_code == 401
    # A wrong password never starts a proof, even with a valid MFA session.
    assert (
        await pg_client.post(
            "/api/v1/auth/reauthentication",
            headers=headers,
            json={
                "current_password": "incorrect-password",
                "action": f"POST {path}",
                "payload_hash": payload_digest(json.dumps(payload).encode()),
            },
        )
    ).status_code == 401
    issued = await proof(pg_client, MutationRequest("POST", path, payload), session)
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


async def _login_existing_mfa(client, session: AdminMfaSession) -> dict[str, str]:
    started = await client.post(
        "/api/v1/auth/login", json={"username": "proof_admin", "password": PASSWORD}
    )
    assert started.status_code == 200, started.json()
    assert started.json()["mfa_required"] is True
    assert "passkey" in started.json()["available_methods"]
    options = await client.post("/api/v1/mfa/passkey/auth/options")
    assert options.status_code == 200, options.json()
    verified = await client.post(
        "/api/v1/mfa/passkey/auth/verify",
        json={
            "mfa_token": started.json()["mfa_token"],
            "credential": session.authenticator.assertion(options.json(), session.origin),
        },
    )
    assert verified.status_code == 200, verified.json()
    return {"X-CSRF-Token": verified.json()["csrf_token"]}


async def test_expired_and_other_session_proof_cannot_mutate(pg_session, pg_client):
    session = await login(pg_client, pg_session)
    headers = session.headers
    path = "/api/v1/admin/clients"
    payload = {
        "client_name": "Expired",
        "client_type": "public",
        "redirect_uris": ["https://service.example.test/callback"],
    }
    issued = await proof(pg_client, MutationRequest("POST", path, payload), session)
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
    issued = await proof(pg_client, MutationRequest("POST", path, payload), session)
    # A second browser session for the same administrator cannot redeem the
    # proof that was issued for the first session.
    second_headers = await _login_existing_mfa(pg_client, session)
    assert (
        await pg_client.post(
            path,
            headers={**second_headers, "X-Reauthentication": issued.json()["authorization"]},
            json=payload,
        )
    ).status_code == 401


async def test_pending_totp_preserves_active_factor_and_checks_session(pg_session):
    user = User(username="pending_totp", email="pending@example.test")
    user.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    pg_session.add(user)
    await record_test_consent(pg_session, user)
    cfg = Settings(_env_file=None, FEATURE_TOTP_ENABLED=True)
    _, session, _ = await AuthService.create_user_session(
        db=pg_session, request=SessionRequest(user.id, None, None), settings=cfg
    )
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
    first = await login(pg_client, pg_session)
    path = "/api/v1/admin/clients"
    payload = {
        "client_name": "Cross-user proof",
        "client_type": "public",
        "redirect_uris": ["https://proof.example.test/callback"],
    }
    foreign = (await proof(pg_client, MutationRequest("POST", path, payload), first)).json()[
        "authorization"
    ]
    other = User(username="second_proof_admin", email="secondproof@example.test", is_superuser=True)
    other.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    pg_session.add(other)
    await record_test_consent(pg_session, other)
    await pg_session.commit()
    second = await login_admin_with_mfa_direct(pg_session, pg_client, other.username, PASSWORD)
    own_headers = second.headers
    assert (
        await pg_client.post(
            path, json=payload, headers={**own_headers, "X-Reauthentication": foreign}
        )
    ).status_code == 401
    own = (await proof(pg_client, MutationRequest("POST", path, payload), second)).json()[
        "authorization"
    ]
    assert (
        await pg_client.post(path, json=payload, headers={**own_headers, "X-Reauthentication": own})
    ).status_code == 201
