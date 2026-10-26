"""One TOTP time step authorises exactly one operation, also across login/reauth.

These are real PostgreSQL + HTTP scenarios: a spent code is reported with a
distinct, retryable error while the one-use reauthentication authorization
itself survives, so the user can enter the next code without repeating the
password and MFA challenge.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import httpx
import pyotp
import pytest
from app.config import get_settings
from app.core.security import (
    encrypt_totp_secret,
    generate_random_token,
    hash_password,
    hash_token,
)
from app.models.authentication import SecurityAuthorization
from app.models.mfa import TOTPCredential
from app.models.session import Session
from app.models.user import PasswordCredential, User
from app.services.reauthentication_service import payload_digest
from sqlalchemy import select

from tests.helpers.privacy import record_test_consent

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]

PASSWORD = f"Synth{secrets.token_urlsafe(18)}"
SESSIONS_PATH = "/api/v1/auth/sessions"


def _code(secret: str, offset: int = 0) -> str:
    step = int(datetime.now(timezone.utc).timestamp()) // 30 + offset
    return pyotp.TOTP(secret).at(step * 30)


def _wrong_code(secret: str) -> str:
    valid = {_code(secret, offset) for offset in (-1, 0, 1)}
    return next(f"{value:06}" for value in range(10**6) if f"{value:06}" not in valid)


async def _synthetic_totp_user(
    pg_session,
    *,
    username: str,
    last_verified_step: int | None,
) -> tuple[User, str]:
    user = User(username=username, email=f"{username}@example.test")
    user.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    pg_session.add(user)
    await pg_session.flush()
    secret = pyotp.random_base32()
    pg_session.add(
        TOTPCredential(
            user_id=user.id,
            encrypted_secret=encrypt_totp_secret(secret),
            is_confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
            last_verified_step=last_verified_step,
        )
    )
    await record_test_consent(pg_session, user)
    return user, secret


async def _session_headers(pg_session, pg_client, user: User) -> dict[str, str]:
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
        mfa_verified=True,
        mfa_method="totp",
        amr="pwd otp",
    )
    pg_session.add(session)
    await pg_session.commit()
    from app.api.deps import generate_csrf_token

    pg_client.cookies.set("alx_session", raw, path="/")
    return {"X-CSRF-Token": generate_csrf_token(session.id, get_settings())}


async def _start(client, headers: dict[str, str]) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/reauthentication",
        headers=headers,
        json={
            "current_password": PASSWORD,
            "action": f"GET {SESSIONS_PATH}",
            "payload_hash": payload_digest(b""),
        },
    )


async def _confirm(
    client, headers: dict[str, str], authorization: str, code: str
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/reauthentication/factor",
        headers=headers,
        json={"authorization": authorization, "method": "totp", "code": code},
    )


async def test_spent_step_reports_retry_hint_and_keeps_authorization_alive(pg_session, pg_client):
    current_step = int(datetime.now(timezone.utc).timestamp()) // 30
    user, secret = await _synthetic_totp_user(
        pg_session, username="totp_spent_step", last_verified_step=current_step
    )
    headers = await _session_headers(pg_session, pg_client, user)

    started = await _start(pg_client, headers)
    assert started.status_code == 200, started.json()
    assert started.json()["factor_required"] is True
    assert "totp" in started.json()["methods"]

    replayed = await _confirm(pg_client, headers, started.json()["authorization"], _code(secret, 0))
    assert replayed.status_code == 401, replayed.json()
    assert replayed.json()["error"] == "totp_code_reused"
    assert 1 <= replayed.json()["retry_after"] <= 31
    assert replayed.headers["Retry-After"] == str(replayed.json()["retry_after"])

    row = await pg_session.scalar(select(SecurityAuthorization))
    assert row.stage == "factor"
    assert row.failed_attempts == 0, "a real but spent code is not a wrong guess"

    # The same one-use authorization still accepts the next RFC 6238 step.
    confirmed = await _confirm(
        pg_client, headers, started.json()["authorization"], _code(secret, 1)
    )
    assert confirmed.status_code == 200, confirmed.json()
    proof = {**headers, "X-Reauthentication": confirmed.json()["authorization"]}
    assert (await pg_client.get(SESSIONS_PATH, headers=proof)).status_code == 200
    # The code is still single-use after the authorization was redeemed.
    again = await _confirm(pg_client, headers, started.json()["authorization"], _code(secret, 1))
    assert again.status_code == 401


async def test_wrong_totp_code_stays_generic_and_counts_a_failure(pg_session, pg_client):
    user, secret = await _synthetic_totp_user(
        pg_session, username="totp_wrong_code", last_verified_step=None
    )
    headers = await _session_headers(pg_session, pg_client, user)
    started = await _start(pg_client, headers)
    assert started.status_code == 200, started.json()
    rejected = await _confirm(
        pg_client, headers, started.json()["authorization"], _wrong_code(secret)
    )
    assert rejected.status_code == 401
    assert rejected.json()["error"] == "reauthentication_required"
    assert "retry_after" not in rejected.json()
    row = await pg_session.scalar(select(SecurityAuthorization))
    assert row.failed_attempts == 1


async def test_concurrent_same_step_confirmations_have_one_winner(pg_session, pg_client):
    current_step = int(datetime.now(timezone.utc).timestamp()) // 30
    user, secret = await _synthetic_totp_user(
        pg_session, username="totp_concurrent", last_verified_step=current_step - 1
    )
    headers = await _session_headers(pg_session, pg_client, user)
    first = await _start(pg_client, headers)
    second = await _start(pg_client, headers)
    assert first.status_code == 200 and second.status_code == 200

    code = _code(secret, 0)
    results = await asyncio.gather(
        _confirm(pg_client, headers, first.json()["authorization"], code),
        _confirm(pg_client, headers, second.json()["authorization"], code),
    )
    statuses = sorted(response.status_code for response in results)
    assert statuses == [200, 401], [response.json() for response in results]
    loser = next(response for response in results if response.status_code == 401)
    assert loser.json()["error"] == "totp_code_reused"
    authorized = await pg_session.scalars(
        select(SecurityAuthorization).where(SecurityAuthorization.stage == "authorized")
    )
    assert len(authorized.all()) == 1


async def test_login_totp_code_cannot_be_reused_for_reauthentication(pg_session, pg_client):
    user, secret = await _synthetic_totp_user(
        pg_session, username="totp_login_then_reauth", last_verified_step=None
    )
    login = await pg_client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": PASSWORD}
    )
    assert login.status_code == 200, login.json()
    assert login.json()["mfa_required"] is True
    verified = await pg_client.post(
        "/api/v1/mfa/totp/verify",
        json={"code": _code(secret, 0), "mfa_token": login.json()["mfa_token"]},
    )
    assert verified.status_code == 200, verified.json()
    headers = {"X-CSRF-Token": verified.json()["csrf_token"]}

    started = await _start(pg_client, headers)
    assert started.status_code == 200, started.json()
    replayed = await _confirm(pg_client, headers, started.json()["authorization"], _code(secret, 0))
    assert replayed.status_code == 401
    assert replayed.json()["error"] == "totp_code_reused"
    next_step = await _confirm(
        pg_client, headers, started.json()["authorization"], _code(secret, 1)
    )
    assert next_step.status_code == 200, next_step.json()
