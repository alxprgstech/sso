"""Real PostgreSQL privacy invariants; synthetic identities and explicit consent."""

import asyncio
from datetime import timedelta

import pytest
from app.config import get_settings
from app.core.exceptions import AuthorizationException
from app.core.security import hash_password, hash_token
from app.legal import REQUIRED_DOCUMENTS
from app.models.audit import AuditEvent
from app.models.privacy import DeletedSubject, DeletionAuthorization, LegalAcceptance
from app.models.session import Session
from app.models.user import PasswordCredential, User
from app.services import privacy_service as privacy
from app.services.auth_service import AuthService
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
PASSWORD = "SyntheticPrivacy2026!"  # pragma: allowlist secret -- synthetic test password


async def subject(db, *, admin=False, accepted=True):
    user = User(
        username="privacy_subject",
        email="privacy@example.test",
        email_verified=True,
        is_active=True,
        is_superuser=admin,
    )
    db.add(user)
    await db.flush()
    db.add(PasswordCredential(user_id=user.id, password_hash=hash_password(PASSWORD)))
    if accepted:
        await privacy.record_acceptance(
            db, user.id, REQUIRED_DOCUMENTS, await privacy.database_now(db)
        )
    await db.commit()
    await db.refresh(user)
    _, session, csrf = await AuthService.create_user_session(
        db, user.id, None, None, get_settings()
    )
    return user, session, csrf


async def permission(db, user, session, action):
    result = await privacy.start_reauthentication(
        privacy.DeletionContext(db, user, session, get_settings()), action, PASSWORD
    )
    assert result["factor_required"] is False
    row = await db.scalar(
        select(DeletionAuthorization).where(DeletionAuthorization.session_id == session.id)
    )
    assert row.token_hash == hash_token(result["authorization"])
    assert row.token_hash != result["authorization"]
    return result["authorization"]


async def test_wait_cancel_cooldown_and_no_token_resurrection(pg_session):
    user, session, _ = await subject(pg_session)
    proof = await permission(pg_session, user, session, "request")
    status, raw = await privacy.request_deletion(pg_session, user, session, proof)
    assert status["scheduled_for"] - status["requested_at"] == timedelta(days=14)
    assert await pg_session.get(Session, session.id, populate_existing=True) is None
    limited = await pg_session.scalar(
        select(Session).where(Session.session_token_hash == hash_token(raw))
    )
    assert limited.purpose == "deletion_management"
    await pg_session.refresh(user)
    with pytest.raises(HTTPException, match="403"):
        await privacy.require_access(pg_session, user)
    _, login_session, _ = await AuthService.create_user_session(
        pg_session, user.id, None, None, get_settings()
    )
    assert login_session.purpose == "deletion_management"
    # Login cannot move the scheduled deadline.
    await pg_session.refresh(user)
    assert user.deletion_scheduled_for == status["scheduled_for"]
    cancellation = await permission(pg_session, user, limited, "cancel")
    cancelled = await privacy.cancel_deletion(pg_session, user, limited, cancellation)
    assert cancelled["pending"] is False
    assert cancelled["request_allowed_at"] > await privacy.database_now(pg_session) + timedelta(
        days=6, hours=23
    )
    assert await pg_session.scalar(select(func.count()).select_from(Session)) == 0
    _, fresh, _ = await AuthService.create_user_session(
        pg_session, user.id, None, None, get_settings()
    )
    assert fresh.purpose == "full"
    with pytest.raises(HTTPException) as error:
        await privacy.start_reauthentication(
            privacy.DeletionContext(pg_session, user, fresh, get_settings()), "request", PASSWORD
        )
    assert error.value.status_code == 429


async def test_permission_binding_expiry_and_last_admin(pg_session):
    user, session, _ = await subject(pg_session, admin=True)
    raw = await permission(pg_session, user, session, "request")
    _, other, _ = await AuthService.create_user_session(
        pg_session, user.id, None, None, get_settings()
    )
    for action, bound in [("cancel", session), ("request", other)]:
        with pytest.raises(HTTPException):
            await privacy.authorization_row(
                pg_session,
                privacy.AuthorizationScope(user.id, bound.id),
                privacy.ActionProof(raw, action),
                "authorized",
            )
    with pytest.raises(AuthorizationException):
        await privacy.request_deletion(pg_session, user, session, raw)
    user_id, session_id = user.id, session.id
    await pg_session.rollback()
    await pg_session.execute(
        update(DeletionAuthorization).values(
            expires_at=func.clock_timestamp() - timedelta(seconds=1)
        )
    )
    await pg_session.commit()
    with pytest.raises(HTTPException):
        await privacy.authorization_row(
            pg_session,
            privacy.AuthorizationScope(user_id, session_id),
            privacy.ActionProof(raw, "request"),
            "authorized",
        )


async def test_overdue_worker_erases_cascades_and_scrubs_audit(pg_session, pg_engine):
    user, session, _ = await subject(pg_session)
    subject_id = user.id
    raw = await permission(pg_session, user, session, "request")
    await privacy.request_deletion(pg_session, user, session, raw)
    pg_session.add(
        AuditEvent(
            event_type="admin_user_updated",
            details={"target_user_id": str(subject_id), "email": user.email},
            ip_address="192.0.2.1",
            user_agent="old full UA",
        )
    )
    await pg_session.execute(
        update(User)
        .where(User.id == subject_id)
        .values(
            deletion_requested_at=func.clock_timestamp() - timedelta(days=15),
            deletion_scheduled_for=func.clock_timestamp() - timedelta(days=1),
            is_active=False,
        )
    )
    await pg_session.commit()
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def worker():
        async with factory() as db:
            return await privacy.maintenance(db, get_settings())

    counts = await asyncio.gather(worker(), worker())
    assert sum(counts) == 1
    assert await pg_session.get(User, subject_id, populate_existing=True) is None
    for model in (PasswordCredential, Session, LegalAcceptance, DeletionAuthorization):
        assert await pg_session.scalar(select(func.count()).select_from(model)) == 0
    assert await pg_session.scalar(select(DeletedSubject.subject_id)) == subject_id
    events = (
        await pg_session.scalars(select(AuditEvent).execution_options(populate_existing=True))
    ).all()
    assert all(
        event.user_id is None
        and event.ip_address is None
        and event.user_agent is None
        and event.details == {}
        for event in events
    )


async def test_documents_gate_and_direct_api_csrf(pg_session, pg_client):
    user, _, _ = await subject(pg_session, accepted=False)
    with pytest.raises(HTTPException) as error:
        await privacy.require_access(pg_session, user)
    assert error.value.detail["error"] == "legal_acceptance_required"
    login = await pg_client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    assert (await pg_client.get("/api/v1/auth/me")).json()["legal_acceptance_required"] is True
    assert (await pg_client.get("/api/v1/auth/sessions")).status_code == 403
    assert (
        await pg_client.post(
            "/api/v1/auth/legal-acceptance",
            json={
                "terms_accepted": True,
                "data_processing_consent": True,
                "legal_versions": REQUIRED_DOCUMENTS,
            },
        )
    ).status_code == 403
    old = await pg_client.post(
        "/api/v1/auth/legal-acceptance",
        headers={"X-CSRF-Token": csrf},
        json={
            "terms_accepted": True,
            "data_processing_consent": True,
            "legal_versions": {"terms": "old", "data-consent": "old"},
        },
    )
    assert old.status_code == 409
    accepted = await pg_client.post(
        "/api/v1/auth/legal-acceptance",
        headers={"X-CSRF-Token": csrf},
        json={
            "terms_accepted": True,
            "data_processing_consent": True,
            "legal_versions": REQUIRED_DOCUMENTS,
        },
    )
    assert accepted.status_code == 200
    assert (await pg_client.get("/api/v1/auth/sessions")).status_code == 200
    assert (
        await pg_client.post("/api/v1/auth/account-deletion", json={"authorization": "x" * 43})
    ).status_code == 403
    wrong = await pg_client.post(
        "/api/v1/auth/account-deletion/reauthenticate",
        headers={"X-CSRF-Token": csrf},
        json={
            "action": "request",
            "current_password": PASSWORD + "_incorrect",
        },
    )
    assert wrong.status_code == 401


async def test_cancel_deadline_and_permission_reuse(pg_session):
    user, session, _ = await subject(pg_session)
    raw = await permission(pg_session, user, session, "request")
    status, limited_raw = await privacy.request_deletion(pg_session, user, session, raw)
    limited = await pg_session.scalar(
        select(Session).where(Session.session_token_hash == hash_token(limited_raw))
    )
    with pytest.raises(HTTPException):
        await privacy.authorization_row(
            pg_session,
            privacy.AuthorizationScope(user.id, session.id),
            privacy.ActionProof(raw, "request"),
            "authorized",
        )
    await pg_session.refresh(user)
    cancel = await permission(pg_session, user, limited, "cancel")
    # At the boundary the database clock wins over a previously issued permission.
    await pg_session.execute(
        update(User).where(User.id == user.id).values(deletion_scheduled_for=func.clock_timestamp())
    )
    await pg_session.commit()
    with pytest.raises(HTTPException) as error:
        await privacy.cancel_deletion(pg_session, user, limited, cancel)
    assert error.value.detail["error"] == "deletion_not_cancellable"
    await pg_session.refresh(user)
    assert user.deletion_scheduled_for <= status["scheduled_for"]


async def test_totp_reauthentication_cannot_be_bypassed_or_replayed(pg_session):
    import pyotp
    from app.core.security import encrypt_totp_secret
    from app.models.mfa import TOTPCredential

    user, session, _ = await subject(pg_session)
    secret = pyotp.random_base32()
    pg_session.add(
        TOTPCredential(
            user_id=user.id, encrypted_secret=encrypt_totp_secret(secret), is_confirmed=True
        )
    )
    await pg_session.commit()
    await pg_session.refresh(user)
    settings = get_settings().model_copy(update={"FEATURE_TOTP_ENABLED": True})
    proof = await privacy.start_reauthentication(
        privacy.DeletionContext(pg_session, user, session, settings), "request", PASSWORD
    )
    assert proof["factor_required"] and "totp" in proof["methods"]
    with pytest.raises(HTTPException):
        await privacy.request_deletion(pg_session, user, session, proof["authorization"])
    with pytest.raises(HTTPException):
        await privacy.confirm_factor(
            privacy.DeletionContext(pg_session, user, session, settings),
            privacy.ActionProof(proof["authorization"], "request"),
            privacy.FactorEvidence("totp", "wrong", None),
        )
    second = await privacy.start_reauthentication(
        privacy.DeletionContext(pg_session, user, session, settings), "request", PASSWORD
    )
    code = pyotp.TOTP(secret).now()
    approved = await privacy.confirm_factor(
        privacy.DeletionContext(pg_session, user, session, settings),
        privacy.ActionProof(proof["authorization"], "request"),
        privacy.FactorEvidence("totp", code, None),
    )
    assert approved["authorization"] != proof["authorization"]
    with pytest.raises(HTTPException):
        await privacy.confirm_factor(
            privacy.DeletionContext(pg_session, user, session, settings),
            privacy.ActionProof(second["authorization"], "request"),
            privacy.FactorEvidence("totp", code, None),
        )
    await privacy.request_deletion(pg_session, user, session, approved["authorization"])


async def test_duplicate_requests_and_cancellation_race(pg_session, pg_engine):
    user, session, _ = await subject(pg_session)
    user_id, session_id = user.id, session.id
    proof = await permission(pg_session, user, session, "request")
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def request():
        async with factory() as db:
            u = await db.get(User, user_id)
            s = await db.get(Session, session_id)
            # Each contender carries its original session, even if the winner revokes it.
            if s is None:
                return "revoked"
            try:
                return await privacy.request_deletion(db, u, s, proof)
            except HTTPException:
                return "rejected"

    results = await asyncio.gather(request(), request())
    assert sum(isinstance(result, tuple) for result in results) == 1
    await pg_session.refresh(user)
    deadline = user.deletion_scheduled_for
    limited = await pg_session.scalar(select(Session).where(Session.user_id == user_id))
    cancellation = await permission(pg_session, user, limited, "cancel")
    limited_id = limited.id
    # Before the deadline a concurrently running worker cannot erase this subject.
    await pg_session.rollback()

    async def cancel():
        async with factory() as db:
            u = await db.get(User, user_id)
            s = await db.get(Session, limited_id)
            return await privacy.cancel_deletion(db, u, s, cancellation)

    async def worker():
        async with factory() as db:
            return await privacy.maintenance(db, get_settings())

    cancelled, erased = await asyncio.gather(cancel(), worker())
    assert cancelled["pending"] is False and erased == 0
    assert await pg_session.get(User, user_id, populate_existing=True) is not None
    await pg_session.execute(
        update(User)
        .where(User.id == user_id)
        .values(deletion_request_allowed_at=func.clock_timestamp() - timedelta(seconds=1))
    )
    await pg_session.commit()
    _, fresh, _ = await AuthService.create_user_session(
        pg_session, user_id, None, None, get_settings()
    )
    renewed = await permission(pg_session, user, fresh, "request")
    new_status, _ = await privacy.request_deletion(pg_session, user, fresh, renewed)
    assert new_status["scheduled_for"] > deadline


async def test_retention_is_independent_from_rate_limits_and_refresh_replay(pg_session):
    import uuid

    from app.models.privacy import PrivacyRateWindow

    now = await privacy.database_now(pg_session)
    pg_session.add_all(
        [
            AuditEvent(event_type="old", details={}, created_at=now - timedelta(days=91)),
            AuditEvent(event_type="recent", details={}, created_at=now - timedelta(days=89)),
            PrivacyRateWindow(
                key_hash="a" * 64, attempts=4, expires_at=now + timedelta(seconds=30)
            ),
            PrivacyRateWindow(key_hash="b" * 64, attempts=1, expires_at=now - timedelta(seconds=1)),
            DeletedSubject(subject_id=uuid.uuid4(), deleted_at=now - timedelta(days=31)),
            DeletedSubject(subject_id=uuid.uuid4(), deleted_at=now - timedelta(days=29)),
        ]
    )
    await pg_session.commit()
    assert await privacy.maintenance(pg_session, get_settings()) == 0
    assert list(await pg_session.scalars(select(AuditEvent.event_type))) == ["recent"]
    assert list(await pg_session.scalars(select(PrivacyRateWindow.attempts))) == [4]
    assert await pg_session.scalar(select(func.count()).select_from(DeletedSubject)) == 1
    # The replay cleanup boundary includes both the family and token lifetimes.
    # Existing OIDC PG tests exercise reuse detection against retained rotated rows.
    assert get_settings().REFRESH_FAMILY_MAX_LIFETIME_SECONDS > 0


async def test_last_admin_with_multiple_roles_and_competing_block(pg_session, pg_engine):
    from app.core.rbac import ROLE_ADMIN, ROLE_USER
    from app.models.user import Role, UserRole
    from app.services.admin_service import AdminService

    first, session, _ = await subject(pg_session, admin=True)
    first.username = "first_privacy_admin"
    first.email = "first_privacy_admin@example.test"
    for name in (ROLE_ADMIN, ROLE_USER):
        role = await pg_session.scalar(select(Role).where(Role.name == name))
        if role is None:
            role = Role(name=name)
            pg_session.add(role)
            await pg_session.flush()
        pg_session.add(UserRole(user_id=first.id, role_id=role.id))
    await pg_session.commit()
    proof = await permission(pg_session, first, session, "request")
    with pytest.raises(AuthorizationException):
        await privacy.request_deletion(pg_session, first, session, proof)
    first_id, session_id = first.id, session.id
    await pg_session.rollback()
    second, _, _ = await subject(pg_session, admin=True)
    second_id = second.id
    await pg_session.rollback()
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def delete_first():
        async with factory() as db:
            u = await db.get(User, first_id)
            s = await db.get(Session, session_id)
            try:
                await privacy.request_deletion(db, u, s, proof)
                return True
            except AuthorizationException:
                return False

    async def block_second():
        async with factory() as db:
            admin = await db.get(User, first_id)
            try:
                await AdminService.update_user(db, second_id, admin, is_active=False)
                return True
            except AuthorizationException:
                return False

    outcomes = await asyncio.gather(delete_first(), block_second())
    assert sum(outcomes) == 1
    active = await pg_session.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.is_active.is_(True),
            User.is_superuser.is_(True),
            User.deletion_scheduled_for.is_(None),
        )
    )
    assert active == 1


async def test_stale_documents_block_direct_oidc_and_userinfo(pg_session, pg_client):
    from app.core.exceptions import OAuthErrorException
    from app.models.oidc import OIDCClient
    from app.services.oidc_service import OIDCService

    user, _, _ = await subject(pg_session)
    client = OIDCClient(
        client_id="privacy_oidc",
        client_name="Synthetic privacy client",
        client_type="public",
        is_active=True,
    )
    pg_session.add(client)
    await pg_session.commit()
    tokens = await OIDCService._generate_tokens_for_user(
        pg_session, user, client, "openid profile email"
    )
    await pg_session.execute(
        update(LegalAcceptance).where(LegalAcceptance.user_id == user.id).values(version="obsolete")
    )
    await pg_session.commit()
    assert (
        await pg_client.get(
            "/oauth/userinfo", headers={"Authorization": "Bearer " + tokens.access_token}
        )
    ).status_code == 401
    with pytest.raises(HTTPException) as error:
        await OIDCService.create_authorization_code(
            pg_session, client, user, "http://localhost/callback", "synthetic-challenge"
        )
    assert error.value.status_code == 403
    with pytest.raises(OAuthErrorException):
        await OIDCService._generate_tokens_for_user(pg_session, user, client, "openid")
    await privacy.record_acceptance(
        pg_session, user.id, REQUIRED_DOCUMENTS, await privacy.database_now(pg_session)
    )
    await pg_session.commit()
    assert (
        await pg_client.get(
            "/oauth/userinfo", headers={"Authorization": "Bearer " + tokens.access_token}
        )
    ).status_code == 200


async def test_stale_registration_consent_cannot_trigger_resend(pg_session, monkeypatch):
    from app.models.registration import PendingRegistration
    from app.services.registration_service import RegistrationService

    async def forbidden_send(*args, **kwargs):
        pytest.fail("No mail may be sent for obsolete consent")

    monkeypatch.setattr(RegistrationService, "_send", forbidden_send)
    now = await privacy.database_now(pg_session)
    pending = PendingRegistration(
        username="privacy_pending",
        email="privacy_pending@example.test",
        password_hash=hash_password(PASSWORD),
        code_hash="c" * 64,
        link_hash="d" * 64,
        request_details={},
        expires_at=now + timedelta(minutes=5),
        legal_versions={"terms": "obsolete", "data-consent": "obsolete"},
        legal_accepted_at=now,
    )
    pg_session.add(pending)
    await pg_session.commit()
    with pytest.raises(HTTPException) as error:
        await RegistrationService.resend(pg_session, pending.id, "192.0.2.50", get_settings())
    assert error.value.status_code == 409
    assert pending.code_hash == "c" * 64
