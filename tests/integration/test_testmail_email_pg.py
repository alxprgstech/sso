"""Real API -> PostgreSQL -> SES -> testmail; no email transport mocks."""

import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest
from app.core.rbac import ROLE_USER
from app.core.security import hash_password
from app.legal import REQUIRED_DOCUMENTS
from app.models.user import PasswordCredential, Role, User
from sqlalchemy import select, text

from tests.helpers.privacy import accept_current_documents
from tests.helpers.testmail_client import EmailTestError, assert_verification_message, checkpoint

pytestmark = [pytest.mark.email_external, pytest.mark.postgres, pytest.mark.asyncio]
PASSWORD = "EmailFixture2026!"


def expect_status(response, expected):
    # Never include request/response bodies in assertion introspection.
    if response.status_code != expected:
        raise EmailTestError(
            f"API status mismatch: expected {expected}, got {response.status_code}"
        )


async def receive(context, start, username, mode):
    settings, box, client = context
    message = await asyncio.to_thread(client.wait_for_message, box, start)
    code, link = assert_verification_message(message, box, settings, username=username, mode=mode)
    return message, code, parse_qs(urlsplit(link).query)["token"][0]


async def assert_login_and_role(client, session, username):
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    await accept_current_documents(client, response)
    expect_status(response, 200)
    expect_status(await client.get("/api/v1/auth/me"), 200)
    expect_status(await client.get("/api/v1/admin/users"), 403)
    row = (
        await session.execute(
            text("SELECT email_verified,is_superuser FROM users WHERE username=:username"),
            {"username": username},
        )
    ).one()
    assert row.email_verified is True and row.is_superuser is False
    roles = (
        (
            await session.execute(
                text(
                    "SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id=r.id JOIN users u ON u.id=ur.user_id WHERE u.username=:username"
                ),
                {"username": username},
            )
        )
        .scalars()
        .all()
    )
    assert roles == [ROLE_USER]


@pytest.mark.parametrize(
    "mode,pg_client",
    [("code", "192.0.2.101"), ("link", "192.0.2.102"), ("resend", "192.0.2.103")],
    indirect=["pg_client"],
)
async def test_registration_delivery(mode, pg_client, pg_session, external_email):
    _, box, _ = external_email
    username = f"email_{box.tag[-20:]}"
    start = checkpoint()
    response = await pg_client.post(
        "/api/v1/auth/register",
        json={"terms_accepted": True, "data_processing_consent": True, "legal_versions": REQUIRED_DOCUMENTS,
            "username": username,
            "email": box.address,
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
    )
    expect_status(response, 202)
    challenge = response.json()["challenge_id"]
    assert (
        await pg_session.execute(select(User).where(User.email == box.address))
    ).scalar_one_or_none() is None
    expect_status(
        await pg_client.post(
            "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
        ),
        401,
    )
    message, code, token = await receive(external_email, start, username, "registration")
    if mode == "resend":
        # Snapshot ALL known IDs before the next send, not only the first SES copy.
        client = external_email[2]
        existing = await asyncio.to_thread(client.query_messages, box, start)
        next_start = checkpoint(existing)
        expect_status(
            await pg_client.post("/api/v1/auth/register/resend", json={"challenge_id": challenge}),
            202,
        )
        expect_status(
            await pg_client.post("/api/v1/auth/register/confirm-link", json={"token": token}), 401
        )
        new_message, code, token = await receive(
            external_email, next_start, username, "registration"
        )
        assert new_message.id != message.id
    if mode == "link":
        expect_status(
            await pg_client.post("/api/v1/auth/register/preview-link", json={"token": token}), 200
        )
        assert (
            await pg_session.execute(select(User).where(User.email == box.address))
        ).scalar_one_or_none() is None
        expect_status(
            await pg_client.post("/api/v1/auth/register/confirm-link", json={"token": token}), 200
        )
    else:
        wrong = str((int(code[0]) + 1) % 10) + code[1:]
        expect_status(
            await pg_client.post(
                "/api/v1/auth/register/confirm-code",
                json={"challenge_id": challenge, "code": wrong},
            ),
            401,
        )
        expect_status(
            await pg_client.post(
                "/api/v1/auth/register/confirm-code", json={"challenge_id": challenge, "code": code}
            ),
            200,
        )
    expect_status(
        await pg_client.post("/api/v1/auth/register/confirm-link", json={"token": token}), 401
    )
    expect_status(
        await pg_client.post(
            "/api/v1/auth/register/confirm-code", json={"challenge_id": challenge, "code": code}
        ),
        401,
    )
    assert (
        await pg_session.execute(select(User).where(User.email == box.address))
    ).scalars().one() is not None
    await assert_login_and_role(pg_client, pg_session, username)


@pytest.mark.parametrize(
    "mode,pg_client", [("code", "192.0.2.104"), ("link", "192.0.2.105")], indirect=["pg_client"]
)
async def test_existing_unverified_user_delivery(mode, pg_client, pg_session, external_email):
    _, box, _ = external_email
    username = f"email_{box.tag[-20:]}"
    role = (await pg_session.execute(select(Role).where(Role.name == ROLE_USER))).scalar_one()
    user = User(
        username=username,
        email=box.address,
        email_verified=False,
        is_active=True,
        is_superuser=False,
        roles=[role],
    )
    pg_session.add(user)
    await pg_session.flush()
    pg_session.add(PasswordCredential(user_id=user.id, password_hash=hash_password(PASSWORD)))
    await pg_session.commit()
    expect_status(
        await pg_client.post(
            "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
        ),
        401,
    )
    expect_status(await pg_client.get("/api/v1/auth/me"), 401)
    start = checkpoint()
    expect_status(
        await pg_client.post("/api/v1/mfa/email/request", json={"email": box.address}), 200
    )
    _, code, token = await receive(external_email, start, username, "existing")
    path, payload = (
        ("confirm-code", {"email": box.address, "code": code})
        if mode == "code"
        else ("confirm", {"token": token})
    )
    expect_status(await pg_client.post(f"/api/v1/mfa/email/{path}", json=payload), 200)
    expect_status(await pg_client.post(f"/api/v1/mfa/email/{path}", json=payload), 401)
    expect_status(await pg_client.post("/api/v1/mfa/email/confirm", json={"token": token}), 401)
    await assert_login_and_role(pg_client, pg_session, username)
