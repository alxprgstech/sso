"""Administrator MFA enforcement, onboarding and session assurance on PostgreSQL."""

from datetime import datetime, timedelta, timezone

import httpx
import pyotp
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.core.security import async_hash_password, generate_random_token, hash_token
from app.models.session import Session
from app.models.user import PasswordCredential, Role, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.mfa import login_admin_with_mfa
from tests.helpers.privacy import accept_current_documents, record_test_consent
from tests.helpers.reauthentication import (
    MutationRequest,
    RequestAuthorization,
    authorized_request,
)

PASSWORD = "AdminMfaPolicy2026!"


async def bootstrap_admin(pg_session, username: str = "mfa_admin") -> User:
    code, _ = await execute_bootstrap(
        session=pg_session,
        username=username,
        email=f"{username}@example.test",
        password=PASSWORD,
        registration_mode="closed",
    )
    assert code == 0
    return (await pg_session.execute(select(User).where(User.username == username))).scalar_one()


async def password_login(client, username: str):
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.json()
    await accept_current_documents(client, response)
    return response


def csrf(response) -> dict[str, str]:
    return {"X-CSRF-Token": response.json()["csrf_token"]}


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_password_only_admin_is_limited_until_real_mfa(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    admin = await bootstrap_admin(pg_session)
    login = await password_login(pg_client, admin.username)
    assert login.json()["user"]["session_purpose"] == "admin_mfa_enrollment"
    assert login.json()["user"]["admin_mfa_required"] is True
    assert login.json()["user"]["mfa_verified"] is False
    headers = csrf(login)

    denied = await pg_client.get("/api/v1/admin/users")
    assert denied.status_code == 401
    assert denied.json()["error"] == "admin_mfa_enrollment_required"
    # Onboarding cannot be skipped by inventing an assurance field.
    forged = await pg_client.post(
        "/api/v1/auth/session/elevate",
        headers=headers,
        json={"method": "passkey", "credential": {}, "mfa_verified": True},
    )
    assert forged.status_code == 422

    setup = await authorized_request(
        pg_client,
        MutationRequest("POST", "/api/v1/mfa/totp/setup"),
        RequestAuthorization(PASSWORD, headers),
    )
    assert setup.status_code == 200, setup.json()
    totp = pyotp.TOTP(setup.json()["secret"])
    confirmed = await authorized_request(
        pg_client,
        MutationRequest("POST", "/api/v1/mfa/totp/confirm", json_body={"code": totp.now()}),
        RequestAuthorization(PASSWORD, headers),
    )
    assert confirmed.status_code == 200, confirmed.json()

    # Enrolment alone is not assurance: this same session still cannot enter.
    still_denied = await pg_client.get("/api/v1/admin/users")
    assert still_denied.status_code == 401
    me = await pg_client.get("/api/v1/auth/me")
    assert me.json()["mfa_verified"] is False
    assert me.json()["admin_mfa_required"] is True

    wrong = await pg_client.post(
        "/api/v1/auth/session/elevate",
        headers=headers,
        json={"method": "totp", "code": "000000"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"] == "factor_verification_failed"

    next_code = totp.at(datetime.now(timezone.utc) + timedelta(seconds=30))
    elevated = await pg_client.post(
        "/api/v1/auth/session/elevate",
        headers=headers,
        json={"method": "totp", "code": next_code},
    )
    assert elevated.status_code == 200, elevated.json()
    assert elevated.json()["mfa_verified"] is True
    assert elevated.json()["mfa_method"] == "totp"
    assert elevated.json()["admin_mfa_required"] is False
    assert elevated.json()["session_purpose"] == "full"

    allowed = await pg_client.get("/api/v1/admin/users")
    assert allowed.status_code == 200

    row = await pg_session.scalar(
        select(Session).where(Session.user_id == admin.id, Session.mfa_verified.is_(True))
    )
    assert row is not None and row.mfa_method == "totp"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_legacy_full_session_without_assurance_cannot_use_admin_api(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    admin = await bootstrap_admin(pg_session, "legacy_admin")
    await record_test_consent(pg_session, admin)
    now = datetime.now(timezone.utc)
    raw = generate_random_token(32)
    pg_session.add(
        Session(
            user_id=admin.id,
            session_token_hash=hash_token(raw),
            expires_at=now + timedelta(hours=1),
            last_activity_at=now,
            purpose="full",
            security_revision=admin.security_revision,
            auth_time=now,
            mfa_verified=False,
            amr="pwd",
        )
    )
    await pg_session.commit()
    pg_client.cookies.set("alx_session", raw, path="/")

    denied = await pg_client.get("/api/v1/admin/users")
    assert denied.status_code == 403
    assert denied.json()["error"] == "admin_mfa_required"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_admin_role_grant_revokes_password_only_session(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    admin = await bootstrap_admin(pg_session, "granting_admin")
    session = await login_admin_with_mfa(pg_client, admin.username, PASSWORD)

    user_role = (await pg_session.execute(select(Role).where(Role.name == "user"))).scalar_one()
    target = User(
        username="future_admin",
        email="future_admin@example.test",
        is_active=True,
        is_superuser=False,
        email_verified=True,
        roles=[user_role],
    )
    pg_session.add(target)
    await pg_session.flush()
    pg_session.add(
        PasswordCredential(
            user_id=target.id,
            password_hash=await async_hash_password("FutureAdminPass2026!"),
        )
    )
    await pg_session.commit()
    target_id = str(target.id)

    other = httpx.AsyncClient(transport=pg_client._transport, base_url="http://testserver")
    async with other:
        user_login = await other.post(
            "/api/v1/auth/login",
            json={"username": "future_admin", "password": "FutureAdminPass2026!"},
        )
        await accept_current_documents(other, user_login)
        assert user_login.status_code == 200
        assert user_login.json()["user"]["session_purpose"] == "full"
        assert (await other.get("/api/v1/admin/users")).status_code == 403

        granted = await authorized_request(
            pg_client,
            MutationRequest(
                "PATCH",
                f"/api/v1/admin/users/{target_id}",
                json_body={"roles": ["admin", "user"], "is_superuser": True},
            ),
            RequestAuthorization(PASSWORD, session.headers, factor=session.factor),
        )
        assert granted.status_code == 200, granted.json()

        # The old password-only session is revoked and cannot inherit admin.
        assert (await other.get("/api/v1/admin/users")).status_code == 401
        relogin = await other.post(
            "/api/v1/auth/login",
            json={"username": "future_admin", "password": "FutureAdminPass2026!"},
        )
        await accept_current_documents(other, relogin)
        assert relogin.status_code == 200
        assert relogin.json()["user"]["session_purpose"] == "admin_mfa_enrollment"
        assert relogin.json()["user"]["admin_mfa_required"] is True


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_deleting_last_admin_factor_revokes_admin_access(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    admin = await bootstrap_admin(pg_session, "factorless_admin")
    session = await login_admin_with_mfa(pg_client, admin.username, PASSWORD)
    credentials = await pg_client.get("/api/v1/mfa/passkey/credentials")
    assert len(credentials.json()) == 1
    credential_id = credentials.json()[0]["id"]

    deleted = await authorized_request(
        pg_client,
        MutationRequest("DELETE", f"/api/v1/mfa/passkey/credentials/{credential_id}"),
        RequestAuthorization(PASSWORD, session.headers, factor=session.factor),
    )
    assert deleted.status_code == 200, deleted.json()

    me = await pg_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["mfa_verified"] is False
    denied = await pg_client.get("/api/v1/admin/users")
    assert denied.status_code == 403
    assert denied.json()["error"] == "admin_mfa_required"

    # A fresh password login lands in onboarding, never in the admin panel.
    pg_client.cookies.clear()
    relogin = await password_login(pg_client, admin.username)
    assert relogin.json()["user"]["session_purpose"] == "admin_mfa_enrollment"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_existing_mfa_session_keeps_admin_access_after_policy_upgrade(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    admin = await bootstrap_admin(pg_session, "upgraded_admin")
    session = await login_admin_with_mfa(pg_client, admin.username, PASSWORD)
    assert (await pg_client.get("/api/v1/admin/users")).status_code == 200
    me = await pg_client.get("/api/v1/auth/me")
    assert me.json()["mfa_verified"] is True
    assert me.json()["mfa_method"] == "passkey"
    assert session.headers["X-CSRF-Token"]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_session_elevation_is_bound_to_current_session(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """A stale cookie cannot be elevated by a code verified for another session."""
    admin = await bootstrap_admin(pg_session, "bound_admin")
    login = await password_login(pg_client, admin.username)
    headers = csrf(login)
    setup = await authorized_request(
        pg_client,
        MutationRequest("POST", "/api/v1/mfa/totp/setup"),
        RequestAuthorization(PASSWORD, headers),
    )
    totp = pyotp.TOTP(setup.json()["secret"])
    confirmed = await authorized_request(
        pg_client,
        MutationRequest("POST", "/api/v1/mfa/totp/confirm", json_body={"code": totp.now()}),
        RequestAuthorization(PASSWORD, headers),
    )
    assert confirmed.status_code == 200

    # Replacing the browser cookie with an unrelated session must not inherit
    # the TOTP verification or its assurance.
    await pg_session.refresh(admin)
    other_client = httpx.AsyncClient(transport=pg_client._transport, base_url="http://testserver")
    async with other_client:
        now = datetime.now(timezone.utc)
        raw = generate_random_token(32)
        pg_session.add(
            Session(
                user_id=admin.id,
                session_token_hash=hash_token(raw),
                expires_at=now + timedelta(hours=1),
                last_activity_at=now,
                purpose="admin_mfa_enrollment",
                security_revision=admin.security_revision,
                auth_time=now,
            )
        )
        await pg_session.commit()
        other_client.cookies.set("alx_session", raw, path="/")
        stolen = await other_client.post(
            "/api/v1/auth/session/elevate",
            headers=headers,
            json={
                "method": "totp",
                "code": totp.at(datetime.now(timezone.utc) + timedelta(seconds=30)),
            },
        )
        # CSRF is bound to the session id; the stale header cannot authorize it.
        assert stolen.status_code == 403
        assert stolen.json()["detail"]["error"] == "csrf_invalid"
        assert (await other_client.get("/api/v1/admin/users")).status_code == 401
