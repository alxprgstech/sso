import copy
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, os.path.abspath("backend"))

from app.api.deps import generate_csrf_token, verify_csrf
from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationException, OAuthErrorException
from app.core.security import hash_password
from app.main import app
from app.models.oidc import AuthorizationCode, OIDCClient, RefreshToken
from app.models.session import Session
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.oidc_service import OIDCService
from fastapi.testclient import TestClient

client = TestClient(app)
settings = get_settings()


async def seed_oidc(db):
    from app.models.user import PasswordCredential

    from tests.helpers.privacy import record_test_consent

    user = User(username="security_case", email="security@example.test")
    user.password_credential = PasswordCredential(
        password_hash=hash_password("SecurityRegression2026!")
    )
    client_obj = OIDCClient(client_id="test_client", client_name="Security", client_type="public")
    db.add_all([user, client_obj])
    await record_test_consent(db, user)
    raw = await OIDCService.create_authorization_code(
        db,
        client_obj,
        user,
        "https://client.example.test/callback",
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    )
    return user, client_obj, raw


async def exchange(db, raw, verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"):
    return await OIDCService.exchange_code(
        db, "test_client", None, raw, verifier, "https://client.example.test/callback"
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_invalid_pkce_verifier_rejected(pg_session):
    _, _, raw = await seed_oidc(pg_session)
    with pytest.raises(OAuthErrorException) as exc:
        await exchange(pg_session, raw, "wrong_verifier_123456789012345678901234567890123")
    assert exc.value.status_code == 400 and exc.value.detail["error"] == "invalid_grant"
    assert "code_verifier" in exc.value.detail["error_description"]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_expired_auth_code_rejected(pg_session):
    from sqlalchemy import update

    _, _, raw = await seed_oidc(pg_session)
    await pg_session.execute(
        update(AuthorizationCode).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=5)
        )
    )
    await pg_session.commit()
    with pytest.raises(OAuthErrorException) as exc:
        await exchange(pg_session, raw)
    assert (
        exc.value.detail["error"] == "invalid_grant"
        and "истёк" in exc.value.detail["error_description"]
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_reused_auth_code_rejected(pg_session):
    _, _, raw = await seed_oidc(pg_session)
    assert (await exchange(pg_session, raw)).access_token
    with pytest.raises(OAuthErrorException) as exc:
        await exchange(pg_session, raw)
    assert (
        exc.value.detail["error"] == "invalid_grant"
        and "уже был использован" in exc.value.detail["error_description"]
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_refresh_token_replay_revokes_family(pg_session):
    from sqlalchemy import select

    _, _, raw = await seed_oidc(pg_session)
    initial = await exchange(pg_session, raw)
    rotated = await OIDCService.rotate_refresh_token(
        pg_session, "test_client", None, initial.refresh_token
    )
    assert rotated.refresh_token != initial.refresh_token
    with pytest.raises(OAuthErrorException) as exc:
        await OIDCService.rotate_refresh_token(
            pg_session, "test_client", None, initial.refresh_token
        )
    assert exc.value.detail["error"] == "invalid_grant"
    assert "Всё семейство токенов отозвано" in exc.value.detail["error_description"]
    assert not await pg_session.scalar(select(RefreshToken).where(~RefreshToken.is_revoked))


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_client_authentication_failure(pg_session):
    confidential = OIDCClient(
        client_id="conf_client",
        client_name="Confidential",
        client_type="confidential",
        client_secret_hash=hash_password("CorrectClientSecret2026!"),
    )
    pg_session.add(confidential)
    await pg_session.commit()
    with pytest.raises(OAuthErrorException) as exc:
        await OIDCService.get_and_validate_client(
            pg_session, "conf_client", "wrong_secret", require_secret=True
        )
    assert exc.value.status_code == 401 and exc.value.detail["error"] == "invalid_client"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_blocked_user_cannot_authenticate(pg_session):
    user, _, _ = await seed_oidc(pg_session)
    user.is_active = False
    await pg_session.commit()
    with pytest.raises(AuthenticationException) as exc:
        await AuthService.authenticate_user(pg_session, "security_case", "SecurityRegression2026!")
    assert exc.value.status_code == 401 and exc.value.detail["error"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_csrf_protection_enforcement_direct():
    """Запрос без валидного CSRF токена возвращает 403 Forbidden."""
    session_id = uuid.uuid4()
    session = Session(
        id=session_id,
        user_id=uuid.uuid4(),
        session_token_hash="hash",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        last_activity_at=datetime.now(timezone.utc),
    )

    # 1. Missing CSRF header
    req_missing = MagicMock()
    req_missing.method = "POST"
    req_missing.headers.get.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await verify_csrf(req_missing, session=session, settings=settings)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "csrf_missing"

    # 2. Invalid CSRF header
    req_invalid = MagicMock()
    req_invalid.method = "POST"
    req_invalid.headers.get.return_value = "invalid_token_value"

    with pytest.raises(HTTPException) as exc_info:
        await verify_csrf(req_invalid, session=session, settings=settings)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "csrf_invalid"

    # 3. Valid CSRF header passes
    valid_csrf = generate_csrf_token(session_id, settings)
    req_valid = MagicMock()
    req_valid.method = "POST"
    req_valid.headers.get.return_value = valid_csrf

    # Should not raise
    await verify_csrf(req_valid, session=session, settings=settings)


def test_deferred_features_return_404_when_disabled():
    """Все эндпоинты отложенных возможностей возвращают 404 feature_disabled при флагах=false."""
    from app.database import get_db

    def _get_default_off_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_TOTP_ENABLED = False
        overridden.FEATURE_PASSKEY_ENABLED = False
        overridden.FEATURE_RECOVERY_CODES_ENABLED = False
        overridden.FEATURE_EMAIL_VERIFICATION_ENABLED = True
        overridden.REQUIRE_VERIFIED_EMAIL = False
        return overridden

    fake_db = AsyncMock(spec=AsyncSession)
    fake_db.execute.side_effect = [
        MagicMock(scalar_one=MagicMock(return_value=datetime.now(timezone.utc))),
        MagicMock(scalar_one=MagicMock(return_value=1)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
    ]
    fake_db.scalar.return_value = None

    async def _get_fake_db():
        yield fake_db

    app.dependency_overrides[get_settings] = _get_default_off_settings
    app.dependency_overrides[get_db] = _get_fake_db
    try:
        endpoints = [
            ("POST", "/api/v1/mfa/totp/setup", None, "FEATURE_TOTP_ENABLED"),
            ("POST", "/api/v1/mfa/passkey/register/options", None, "FEATURE_PASSKEY_ENABLED"),
            ("POST", "/api/v1/mfa/recovery-codes/generate", None, "FEATURE_RECOVERY_CODES_ENABLED"),
        ]

        for method, path, payload, feature in endpoints:
            res = client.post(path, json=payload or {})
            assert res.status_code == 404, f"Endpoint {path} did not return 404"
            assert res.json()["error"] == "feature_disabled", (
                f"Endpoint {path} didn't return feature_disabled"
            )
            assert res.json()["feature"] == feature

        # Email request обязателен и доступен (не отключается флагом)
        email_res = client.post("/api/v1/mfa/email/request", json={"email": "user@example.com"})
        assert email_res.status_code == 200
        assert email_res.json()["status"] == "ok"
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_atomic_code_redemption_race_condition(pg_session, pg_engine):
    """Two independent PostgreSQL transactions contend for the same real code."""
    import asyncio

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    _, _, raw = await seed_oidc(pg_session)
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def attempt():
        async with factory() as db:
            try:
                return await exchange(db, raw)
            except OAuthErrorException as exc:
                return exc

    results = await asyncio.gather(attempt(), attempt())
    success = [item for item in results if not isinstance(item, OAuthErrorException)]
    rejected = [item for item in results if isinstance(item, OAuthErrorException)]
    assert len(success) == len(rejected) == 1
    assert success[0].access_token
    assert rejected[0].status_code == 400 and rejected[0].detail["error"] == "invalid_grant"
    assert "уже был использован" in rejected[0].detail["error_description"]
    assert await pg_session.scalar(select(func.count()).select_from(RefreshToken)) == 1
