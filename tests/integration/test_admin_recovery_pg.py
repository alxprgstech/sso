"""Offline administrator recovery is auditable and never creates assurance."""

import httpx
import pytest
from app.cli.admin_recovery import admin_status, reset_admin_factors
from app.cli.bootstrap_admin import execute_bootstrap
from app.models.audit import AuditEvent
from app.models.mfa import RecoveryCode, TOTPCredential, WebAuthnCredential
from app.models.session import Session
from app.models.user import User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.mfa import login_admin_with_mfa_direct
from tests.helpers.privacy import accept_current_documents

PASSWORD = "AdminRecovery2026!"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_admin_recovery_requires_confirmation_and_revokes_everything(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient, capsys
):
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="recoverable_admin",
        email="recoverable@example.test",
        password=PASSWORD,
        registration_mode="closed",
    )
    assert code == 0
    await login_admin_with_mfa_direct(pg_session, pg_client, "recoverable_admin", PASSWORD)
    assert (await pg_client.get("/api/v1/admin/users")).status_code == 200
    user = (
        await pg_session.execute(select(User).where(User.username == "recoverable_admin"))
    ).scalar_one()
    revision_before = user.security_revision
    assert (
        await pg_session.scalar(select(TOTPCredential.id).where(TOTPCredential.user_id == user.id))
        is None
    )
    assert (
        await pg_session.scalar(
            select(func.count(WebAuthnCredential.id)).where(WebAuthnCredential.user_id == user.id)
        )
        == 1
    )

    assert await admin_status(pg_session) == 0
    assert "recoverable_admin" in capsys.readouterr().out

    assert (
        await reset_admin_factors(pg_session, "recoverable_admin", "owner_request", "wrong-name")
        == 1
    )
    await pg_session.refresh(user)
    assert (
        await pg_session.scalar(
            select(func.count(WebAuthnCredential.id)).where(WebAuthnCredential.user_id == user.id)
        )
        == 1
    )

    assert (
        await reset_admin_factors(
            pg_session, "recoverable_admin", "owner_request", "recoverable_admin"
        )
        == 0
    )
    await pg_session.refresh(user)
    for model in (TOTPCredential, WebAuthnCredential, RecoveryCode):
        assert (
            await pg_session.scalar(select(func.count(model.id)).where(model.user_id == user.id))
            == 0
        )
    assert user.security_revision == revision_before + 1
    assert await pg_session.scalar(select(Session.id).where(Session.user_id == user.id)) is None
    event = await pg_session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == "admin_mfa_recovery_reset",
            AuditEvent.user_id == user.id,
        )
    )
    assert event is not None and event.details["reason"] == "owner_request"

    # The old browser session was revoked and cannot reach admin APIs.
    assert (await pg_client.get("/api/v1/admin/users")).status_code == 401

    # A fresh password login is onboarding only; recovery did not grant MFA.
    relogin = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "recoverable_admin", "password": PASSWORD},
    )
    assert relogin.status_code == 200
    await accept_current_documents(pg_client, relogin)
    assert relogin.json()["user"]["session_purpose"] == "admin_mfa_enrollment"
    assert relogin.json()["user"]["mfa_verified"] is False
    assert (await pg_client.get("/api/v1/admin/users")).status_code == 401
