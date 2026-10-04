import json
from datetime import datetime, timedelta, timezone

import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.models.session import Session
from app.services.admin_service import AdminService
from app.services.reauthentication_service import payload_digest
from sqlalchemy import func, select

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
TEMPORARY = "TemporarySyntheticPassword2026!"
PERMANENT = "PermanentSyntheticPassword2026!"


async def create(db):
    assert (
        await execute_bootstrap(
            db, "owner", "owner@example.test", "SyntheticOwnerPassword2026!", "closed"
        )
    )[0] == 0
    return await AdminService.create_user(
        db, "recovering_user", "recovering@example.test", TEMPORARY, roles=["user"]
    )


async def test_temporary_password_is_one_use_limited_then_forces_fresh_login(pg_session, pg_client):
    user = await create(pg_session)
    assert user.password_credential.requires_change
    login = await pg_client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": TEMPORARY}
    )
    assert login.status_code == 200
    assert login.json()["user"]["session_purpose"] == "password_change"
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    assert (await pg_client.get("/api/v1/auth/me")).status_code == 200
    assert (await pg_client.get("/api/v1/auth/sessions")).status_code == 401
    assert (await pg_client.get("/api/v1/admin/users")).status_code == 401
    repeated = await pg_client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": TEMPORARY}
    )
    assert repeated.status_code == 401
    path = "/api/v1/auth/change-password"
    payload = {"current_password": TEMPORARY, "new_password": PERMANENT}
    no_proof = await pg_client.post(path, headers=csrf, json=payload)
    assert no_proof.status_code == 401
    proof = await pg_client.post(
        "/api/v1/auth/reauthentication",
        headers=csrf,
        json={
            "action": f"POST {path}",
            "payload_hash": payload_digest(json.dumps(payload).encode()),
            "current_password": TEMPORARY,
        },
    )
    assert proof.status_code == 200 and not proof.json()["factor_required"]
    result = await pg_client.post(
        path, headers={**csrf, "X-Reauthentication": proof.json()["authorization"]}, json=payload
    )
    assert result.status_code == 200 and result.json()["requires_login"]
    assert (await pg_client.get("/api/v1/auth/me")).status_code == 401
    assert await pg_session.scalar(select(func.count()).select_from(Session)) == 0
    await pg_session.refresh(user)
    assert not user.password_credential.requires_change
    assert (
        await pg_client.post(
            "/api/v1/auth/login", json={"username": user.username, "password": TEMPORARY}
        )
    ).status_code == 401
    fresh = await pg_client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": PERMANENT}
    )
    assert fresh.status_code == 200 and fresh.json()["user"]["session_purpose"] == "full"


async def test_expired_temporary_password_never_creates_session(pg_session, pg_client):
    user = await create(pg_session)
    user.password_credential.temporary_expires_at = datetime.now(timezone.utc) - timedelta(
        seconds=1
    )
    await pg_session.commit()
    result = await pg_client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": TEMPORARY}
    )
    assert result.status_code == 401
    assert await pg_session.scalar(select(func.count()).select_from(Session)) == 0
