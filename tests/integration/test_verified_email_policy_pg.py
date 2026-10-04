"""Unverified legacy accounts never receive sessions/grants in the required policy."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.config import Settings
from app.core.exceptions import AuthenticationException, OAuthErrorException
from app.core.security import create_jwt, encrypt_totp_secret, hash_password, hash_token
from app.models.authentication import AuthenticationStep
from app.models.mfa import TOTPCredential
from app.models.oidc import OIDCClient, RefreshToken
from app.models.user import PasswordCredential, User
from app.services import oidc_service
from app.services.auth_service import AuthService
from app.services.oidc_service import OIDCService
from sqlalchemy import func, select

from tests.helpers.privacy import record_test_consent

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]


async def test_required_email_rejects_password_before_mfa_and_session(pg_session):
    user = User(username="legacy_unverified", email="legacy@example.test", email_verified=False)
    user.password_credential = PasswordCredential(
        password_hash=hash_password("LegacyUnverifiedPassword2026!")
    )
    user.totp_credential = TOTPCredential(
        encrypted_secret=encrypt_totp_secret("JBSWY3DPEHPK3PXP"), is_confirmed=True
    )
    pg_session.add(user)
    await record_test_consent(pg_session, user)
    cfg = Settings(_env_file=None, REQUIRE_VERIFIED_EMAIL=True, FEATURE_TOTP_ENABLED=True)
    with pytest.raises(AuthenticationException) as failure:
        await AuthService.authenticate_user(
            pg_session, user.username, "LegacyUnverifiedPassword2026!", settings=cfg
        )
    assert failure.value.detail["error"] == "email_verification_required"
    assert await pg_session.scalar(select(func.count()).select_from(AuthenticationStep)) == 0
    with pytest.raises(AuthenticationException):
        await AuthService.create_user_session(pg_session, user.id, None, None, cfg)


async def test_required_email_rejects_legacy_refresh_access_and_code_issue(pg_session, monkeypatch):
    cfg = Settings(_env_file=None, REQUIRE_VERIFIED_EMAIL=True)
    monkeypatch.setattr(oidc_service, "settings", cfg)
    user = User(username="legacy_grants", email="legacygrants@example.test", email_verified=False)
    client = OIDCClient(client_id="legacy_client", client_type="public", client_name="Legacy")
    pg_session.add_all([user, client])
    await record_test_consent(pg_session, user)
    now = datetime.now(timezone.utc)
    # Explicit old-policy grant fixtures, with a true unverified account; no
    # security setting or verification flag changes during the tested request.
    pg_session.add(
        RefreshToken(
            user_id=user.id,
            client_id=client.id,
            family_id=uuid.uuid4(),
            token_hash=hash_token("legacy-refresh"),
            scope="openid",
            security_revision=0,
            expires_at=now + timedelta(minutes=5),
            is_revoked=False,
        )
    )
    await pg_session.commit()
    access = create_jwt(
        {
            "sub": str(user.id),
            "aud": client.client_id,
            "token_use": "access_token",
            "scope": "openid",
            "security_revision": 0,
        },
        expires_in_seconds=300,
    )
    with pytest.raises(OAuthErrorException):
        await OIDCService.get_userinfo(pg_session, access)
    with pytest.raises(OAuthErrorException):
        await OIDCService.rotate_refresh_token(pg_session, client.client_id, None, "legacy-refresh")
    with pytest.raises((AuthenticationException, OAuthErrorException)):
        await OIDCService.create_authorization_code(
            pg_session,
            client,
            user,
            "https://legacy.example.test/callback",
            "a" * 43,
            "S256",
            "openid",
        )
