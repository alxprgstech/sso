"""Independent email confirmations compete against the real PostgreSQL unique constraint."""

import asyncio
import copy
from datetime import datetime, timedelta, timezone

import pytest
from app.config import get_settings
from app.core.security import hash_password, hash_token
from app.main import app
from app.models.mfa import EmailVerificationToken
from app.models.user import PasswordCredential, User
from app.services.admin_service import AdminService
from app.services.mfa_service import EmailVerificationService
from sqlalchemy import select

from tests.helpers.privacy import record_test_consent
from tests.helpers.reauthentication import MutationRequest, RequestAuthorization, authorized_request
from tests.helpers.smtp_message import verification_token
from tests.integration.test_email_verification_pg import MockSMTPServer

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency, pytest.mark.asyncio]


async def test_user_and_admin_email_changes_bind_verification_to_exact_address(
    pg_session, pg_client
):
    password = "EmailIdentityRegression2026!"
    user = User(username="identity_change", email="verified-old@example.test", email_verified=True)
    user.password_credential = PasswordCredential(password_hash=hash_password(password))
    admin = User(username="identity_admin", email="admin@example.test", is_superuser=True)
    pg_session.add_all([user, admin])
    await record_test_consent(pg_session, user)
    smtp = MockSMTPServer(port=0)
    await smtp.start()
    cfg = copy.copy(get_settings())
    cfg.SMTP_HOST, cfg.SMTP_PORT, cfg.SMTP_USE_TLS = "127.0.0.1", smtp.port, False
    cfg.SMTP_USER, cfg.SMTP_PASSWORD, cfg.EMAIL_PROVIDER = "", "", "smtp"
    app.dependency_overrides[get_settings] = lambda: cfg
    try:
        login = await pg_client.post(
            "/api/v1/auth/login", json={"username": user.username, "password": password}
        )
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        path, body = "/api/v1/mfa/email/request", {"email": "verified-new@example.test"}
        assert (await pg_client.post(path, json=body, headers=headers)).status_code == 401
        assert (
            await authorized_request(
                pg_client,
                MutationRequest("POST", path, json_body=body),
                RequestAuthorization(password, headers),
            )
        ).status_code == 200
        assert len(smtp.received_messages) == 1
        await pg_session.refresh(user)
        assert user.email == "verified-old@example.test" and user.email_verified
        # Read the actual SMTP delivery rather than a testing-only in-memory sink.
        pending = verification_token(smtp.received_messages[0])
        assert (
            await pg_client.post("/api/v1/mfa/email/confirm", json={"token": pending})
        ).status_code == 200
        assert (
            await pg_client.post("/api/v1/mfa/email/confirm", json={"token": pending})
        ).status_code == 401
        assert (await pg_client.get("/api/v1/auth/me")).status_code == 401
        await pg_session.refresh(user)
        assert user.email == body["email"] and user.email_verified and user.security_revision == 1
        stale = await EmailVerificationService.send_verification(pg_session, user, user.email, cfg)
        await AdminService.update_user(pg_session, user.id, admin, email="admin-new@example.test")
        await pg_session.refresh(user)
        assert user.email == "admin-new@example.test" and not user.email_verified
        assert not await EmailVerificationService.confirm_email(pg_session, stale)
        new_token = await EmailVerificationService.send_verification(
            pg_session, user, user.email, cfg
        )
        assert await EmailVerificationService.confirm_email(pg_session, new_token)
        await pg_session.refresh(user)
        assert (
            user.email_verified
            and user.email == "admin-new@example.test"
            and user.security_revision == 3
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        await smtp.stop()


async def seed_email_competition(pg_session):
    users = [
        User(username=f"email_race_{index}", email=f"old{index}@example.test", email_verified=False)
        for index in range(2)
    ]
    pg_session.add_all(users)
    await pg_session.flush()
    raw = ["synthetic-email-race-token-" + str(index) for index in range(2)]
    for user, token in zip(users, raw, strict=True):
        pg_session.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=hash_token(token),
                email="unique-new@example.test",
                security_revision=0,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
        )
    await pg_session.commit()
    return raw


def assert_no_integrity_details(responses):
    for response in responses:
        assert not any(
            marker in response.text.lower()
            for marker in ("unique constraint", "insert into", "postgres", "old0@", "old1@")
        )


async def assert_email_competition_state(pg_session):
    pg_session.expire_all()
    current = list(await pg_session.scalars(select(User).order_by(User.username)))
    assert [(user.email_verified, user.security_revision) for user in current].count((True, 1)) == 1
    loser = next(user for user in current if not user.email_verified)
    assert loser.security_revision == 0 and loser.email.startswith("old")


async def test_two_confirmations_cannot_assign_the_same_email_or_leak_integrity_error(
    pg_session, pg_client
):
    raw = await seed_email_competition(pg_session)
    responses = await asyncio.gather(
        *(pg_client.post("/api/v1/mfa/email/confirm", json={"token": token}) for token in raw)
    )
    assert sorted(response.status_code for response in responses) == [200, 401]
    assert_no_integrity_details(responses)
    await assert_email_competition_state(pg_session)
    assert (
        await pg_client.post("/api/v1/mfa/email/confirm", json={"token": raw[0]})
    ).status_code == 401
    assert (
        await pg_client.post("/api/v1/mfa/email/confirm", json={"token": raw[1]})
    ).status_code == 401
