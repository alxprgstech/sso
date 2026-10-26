"""OIDC assurance propagation and Passkey-backed recovery codes."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.config import get_settings
from app.core.security import (
    async_hash_password,
    decode_jwt,
    generate_random_token,
    hash_token,
)
from app.models.mfa import RecoveryCode, WebAuthnCredential
from app.models.session import Session
from app.models.user import PasswordCredential, Role, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.mfa import login_admin_with_mfa_direct
from tests.helpers.privacy import accept_current_documents
from tests.helpers.reauthentication import (
    MutationRequest,
    RequestAuthorization,
    authorized_request,
)
from tests.helpers.webauthn_authenticator import Authenticator

PASSWORD = "AssurancePolicy2026!"


async def _make_client(pg_client, session) -> tuple[str, str]:
    response = await authorized_request(
        pg_client,
        MutationRequest(
            "POST",
            "/api/v1/admin/clients",
            json_body={
                "client_name": "Assurance Client",
                "client_type": "public",
                "redirect_uris": ["https://assurance.example.test/callback"],
            },
        ),
        RequestAuthorization(PASSWORD, session.headers, factor=session.factor),
    )
    assert response.status_code == 201, response.json()
    return response.json()["client_id"], "https://assurance.example.test/callback"


async def _authorize_and_exchange(pg_client, client_id: str, redirect_uri: str):
    verifier = "assurance_verifier_1234567890_abcdefghijklmnopqrstuvwxyz"
    import base64
    import hashlib

    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    authorize = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert authorize.status_code == 302, authorize.text
    query = authorize.headers["Location"].split("?", 1)[1]
    code = dict(item.split("=", 1) for item in query.split("&"))["code"]
    token = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200, token.text
    return token.json()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_admin_role_requires_session_assurance_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="assurance_admin",
        email="assurance_admin@example.test",
        password=PASSWORD,
        registration_mode="closed",
    )
    assert code == 0
    admin_session = await login_admin_with_mfa_direct(
        pg_session, pg_client, "assurance_admin", PASSWORD
    )
    client_id, redirect_uri = await _make_client(pg_client, admin_session)

    assured = await _authorize_and_exchange(pg_client, client_id, redirect_uri)
    access = decode_jwt(assured["access_token"], audience=client_id, expected_use="access_token")
    identity = decode_jwt(assured["id_token"], audience=client_id, expected_use="id_token")
    assert "admin" in access["roles"]
    assert set(access["amr"]) >= {"pwd", "hwk"}
    assert access["acr"] == "urn:alxprgs:acr:mfa"
    assert identity["amr"] == access["amr"]
    assert identity["acr"] == access["acr"]

    user = (
        await pg_session.execute(select(User).where(User.username == "assurance_admin"))
    ).scalar_one()
    now = datetime.now(timezone.utc)
    raw = generate_random_token(32)
    pg_session.add(
        Session(
            user_id=user.id,
            session_token_hash=hash_token(raw),
            expires_at=now + timedelta(hours=1),
            last_activity_at=now,
            purpose="admin_mfa_enrollment",
            security_revision=user.security_revision,
            auth_time=now,
            mfa_verified=False,
            amr="pwd",
        )
    )
    await pg_session.commit()
    pg_client.cookies.set("alx_session", raw, path="/")

    unassured = await _authorize_and_exchange(pg_client, client_id, redirect_uri)
    access = decode_jwt(unassured["access_token"], audience=client_id, expected_use="access_token")
    identity = decode_jwt(unassured["id_token"], audience=client_id, expected_use="id_token")
    assert "admin" not in access["roles"]
    assert access["amr"] == ["pwd"]
    assert access["acr"] == "urn:alxprgs:acr:pwd"
    assert "admin" not in identity["roles"]
    assert identity["amr"] == ["pwd"]

    # Refresh inherits the grant snapshot; it cannot acquire the admin role.
    rotated = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": unassured["refresh_token"],
            "client_id": client_id,
        },
    )
    assert rotated.status_code == 200, rotated.text
    rotated_access = decode_jwt(
        rotated.json()["access_token"], audience=client_id, expected_use="access_token"
    )
    assert "admin" not in rotated_access["roles"]
    assert rotated_access["amr"] == ["pwd"]

    # UserInfo uses the token assurance, not the current database role alone.
    userinfo = await pg_client.get(
        "/oauth/userinfo", headers={"Authorization": f"Bearer {unassured['access_token']}"}
    )
    assert userinfo.status_code == 200
    assert "admin" not in userinfo.json()["roles"]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_recovery_codes_work_with_passkey_only_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    user_role = (await pg_session.execute(select(Role).where(Role.name == "user"))).scalar_one()
    user = User(
        username="passkey_only_user",
        email="passkey_only@example.test",
        is_active=True,
        email_verified=True,
        roles=[user_role],
    )
    pg_session.add(user)
    await pg_session.flush()
    pg_session.add(
        PasswordCredential(user_id=user.id, password_hash=await async_hash_password(PASSWORD))
    )
    await pg_session.commit()

    login = await pg_client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert login.status_code == 200
    await accept_current_documents(pg_client, login)
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}

    authenticator = Authenticator()
    origin = get_settings().WEBAUTHN_ORIGIN
    options = await authorized_request(
        pg_client,
        MutationRequest("POST", "/api/v1/mfa/passkey/register/options"),
        RequestAuthorization(PASSWORD, headers),
    )
    assert options.status_code == 200, options.json()
    registered = await authorized_request(
        pg_client,
        MutationRequest(
            "POST",
            "/api/v1/mfa/passkey/register/verify",
            json_body={
                "name": "Recovery key",
                "credential": authenticator.registration(options.json(), origin),
            },
        ),
        RequestAuthorization(PASSWORD, headers),
    )
    assert registered.status_code == 200, registered.json()

    def factor(data):
        return {
            "method": "passkey",
            "credential": authenticator.assertion(data["passkey_options"], origin),
        }

    generated = await authorized_request(
        pg_client,
        MutationRequest("POST", "/api/v1/mfa/recovery-codes/generate"),
        RequestAuthorization(PASSWORD, headers, factor=factor),
    )
    assert generated.status_code == 200, generated.json()
    codes = generated.json()["recovery_codes"]
    assert len(codes) == 10

    await pg_client.post("/api/v1/auth/logout", headers=headers)
    step_one = await pg_client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert step_one.status_code == 200
    assert step_one.json()["mfa_required"] is True
    assert {"passkey", "recovery_code"} <= set(step_one.json()["available_methods"])

    used = await pg_client.post(
        "/api/v1/mfa/recovery-codes/verify",
        json={"mfa_token": step_one.json()["mfa_token"], "recovery_code": codes[0]},
    )
    assert used.status_code == 200, used.json()
    me = await pg_client.get("/api/v1/auth/me")
    assert me.json()["mfa_verified"] is True
    assert me.json()["mfa_method"] == "recovery_code"

    replay_start = await pg_client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    replay = await pg_client.post(
        "/api/v1/mfa/recovery-codes/verify",
        json={
            "mfa_token": replay_start.json()["mfa_token"],
            "recovery_code": codes[0],
        },
    )
    assert replay.status_code == 401

    # Removing the last passkey also removes dormant recovery codes, so they
    # cannot become valid again after a later factor enrolment.
    session_headers = {"X-CSRF-Token": used.json()["csrf_token"]}
    credential = await pg_session.scalar(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
    )
    removed = await authorized_request(
        pg_client,
        MutationRequest("DELETE", f"/api/v1/mfa/passkey/credentials/{credential.credential_id}"),
        RequestAuthorization(PASSWORD, session_headers, factor=factor),
    )
    assert removed.status_code == 200, removed.json()
    assert (
        await pg_session.scalar(
            select(func.count(RecoveryCode.id)).where(RecoveryCode.user_id == user.id)
        )
        == 0
    )
