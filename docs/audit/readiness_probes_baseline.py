"""Opt-in audit probes, outside ordinary CI collection.

Run from the repository root with PYTHONPATH=backend;packages/python-sdk;.
Assertions express the required safe behavior. Failures reproduce audit findings.
Database objects below are explicit unit doubles, never PostgreSQL evidence.
JWT signatures, password hashing, PKCE and TOTP encryption use real libraries.
No external network, mail or production data is used.
"""

from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from alxprgs_sso import SSOClient
from alxprgs_sso.exceptions import InvalidTokenError
from app import config
from app.api.deps import get_db
from app.core import security
from app.core.exceptions import AuthenticationException, OAuthErrorException
from app.main import app
from app.models.mfa import TOTPCredential
from app.models.oidc import OIDCClient, OIDCRedirectUri
from app.models.session import Session
from app.models.user import PasswordCredential, User
from app.services import auth_service, oidc_service, privacy_service
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService
from app.services.mfa_service import TOTPService
from app.services.oidc_service import OIDCService
from pydantic import ValidationError


@pytest.fixture
def audit_settings(monkeypatch):
    value = config.Settings(
        _env_file=None,
        ENVIRONMENT="testing",
        EMAIL_PROVIDER="smtp",
        SENTRY_ENABLED=False,
        SENTRY_FRONTEND_ENABLED=False,
        BASE_URL="https://auth.example.test",
        FRONTEND_URL="https://auth.example.test",
        OIDC_ISSUER="https://auth.example.test",
        JWT_PRIVATE_KEY_PEM="",
        SESSION_SECRET_KEY=secrets.token_hex(32),
        FEATURE_TOTP_ENABLED=False,
        FEATURE_PASSKEY_ENABLED=False,
        FEATURE_RECOVERY_CODES_ENABLED=False,
        REQUIRE_VERIFIED_EMAIL=False,
    )
    from app import main

    monkeypatch.setattr(main, "settings", value)
    monkeypatch.setattr(security, "settings", value)
    monkeypatch.setattr(auth_service, "settings", value)
    monkeypatch.setattr(oidc_service, "settings", value)
    app.dependency_overrides[config.get_settings] = lambda: value
    yield value
    app.dependency_overrides.clear()


def user_record():
    return User(
        id=uuid.uuid4(),
        username="audit-user",
        email="audit@example.test",
        is_active=True,
        is_superuser=False,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
        roles=[],
    )


def result(value):
    return MagicMock(
        scalar_one_or_none=MagicMock(return_value=value), scalar_one=MagicMock(return_value=value)
    )


def unit_db():
    db = MagicMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.rollback = AsyncMock()
    return db


def sdk():
    client = SSOClient(server_url=security.settings.OIDC_ISSUER, client_id="audit-rp")
    client._cached_jwks = security.get_jwks()
    client._jwks_expires_at = time.time() + 3600
    return client


@pytest.mark.parametrize(
    "kind",
    [
        "none",
        "HS256",
        "wrong_issuer",
        "wrong_audience",
        "expired",
        "unknown_kid",
        "id_as_access",
        "bad_signature",
    ],
)
def test_real_crypto_rejects_adversarial_access_token(audit_settings, kind):
    claims = {
        "iss": audit_settings.OIDC_ISSUER,
        "aud": "audit-rp",
        "sub": str(uuid.uuid4()),
        "exp": int(time.time()) + 60,
        "iat": int(time.time()),
        "token_use": "access_token",
    }
    headers = {"kid": security.get_active_key_id()}
    algorithm, key = "RS256", security.get_rsa_private_key()
    if kind == "none":
        algorithm, key = "none", None
    elif kind == "HS256":
        algorithm, key = "HS256", secrets.token_bytes(32)
    elif kind == "wrong_issuer":
        claims["iss"] = "https://other.example.test"
    elif kind == "wrong_audience":
        claims["aud"] = "other-rp"
    elif kind == "expired":
        claims["exp"] = int(time.time()) - 60
    elif kind == "unknown_kid":
        headers["kid"] = "unregistered-key"
    elif kind == "id_as_access":
        claims["token_use"] = "id_token"
    elif kind == "bad_signature":
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(claims, key, algorithm=algorithm, headers=headers)
    from alxprgs_sso.exceptions import SSOError

    with pytest.raises(SSOError):
        sdk().verify_access_token(token)


def test_real_crypto_accepts_valid_access_and_nonce_id(audit_settings):
    token = security.create_jwt(
        {"sub": str(uuid.uuid4()), "aud": "audit-rp", "token_use": "access_token"}, 60
    )
    assert sdk().verify_access_token(token).sub
    identity = security.create_jwt(
        {
            "sub": str(uuid.uuid4()),
            "aud": "audit-rp",
            "token_use": "id_token",
            "nonce": "audit-nonce",
        },
        60,
    )
    assert sdk().verify_id_token(identity, "audit-nonce")["nonce"] == "audit-nonce"
    with pytest.raises(InvalidTokenError):
        sdk().verify_id_token(identity, "different-nonce")


def test_production_rejects_missing_signing_key():
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None, ENVIRONMENT="production", JWT_PRIVATE_KEY_PEM="")


def test_production_rejects_excess_access_ttl():
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None, ENVIRONMENT="production", ACCESS_TOKEN_TTL_SECONDS=86400)


def test_pkce_rejects_one_character_verifier():
    from authlib.oauth2.rfc7636 import create_s256_code_challenge

    assert security.verify_pkce("x", create_s256_code_challenge("x")) is False


def test_server_requires_expiration(audit_settings):
    token = jwt.encode(
        {"iss": audit_settings.OIDC_ISSUER, "sub": str(uuid.uuid4())},
        security.get_rsa_private_key(),
        algorithm="RS256",
        headers={"kid": security.get_active_key_id()},
    )
    with pytest.raises(OAuthErrorException):
        security.decode_jwt(token)


def test_sdk_requires_iat_in_id_token(audit_settings):
    token = jwt.encode(
        {
            "iss": audit_settings.OIDC_ISSUER,
            "aud": "audit-rp",
            "sub": str(uuid.uuid4()),
            "exp": int(time.time()) + 60,
            "token_use": "id_token",
        },
        security.get_rsa_private_key(),
        algorithm="RS256",
        headers={"kid": security.get_active_key_id()},
    )
    with pytest.raises(InvalidTokenError):
        sdk().verify_id_token(token)


def test_sdk_rejects_wrong_azp_for_multiple_audiences(audit_settings):
    token = security.create_jwt(
        {
            "sub": str(uuid.uuid4()),
            "aud": ["audit-rp", "foreign-rp"],
            "azp": "foreign-rp",
            "token_use": "id_token",
        },
        60,
    )
    with pytest.raises(InvalidTokenError):
        sdk().verify_id_token(token)


def test_sdk_preserves_scope_for_resource_authorization(audit_settings):
    token = security.create_jwt(
        {
            "sub": str(uuid.uuid4()),
            "aud": "audit-rp",
            "scope": "openid",
            "token_use": "access_token",
        },
        60,
    )
    assert sdk().verify_access_token(token).model_dump().get("scope") == "openid"


async def request_with_db(db, method, path, **kwargs):
    async def dependency():
        yield db

    app.dependency_overrides[get_db] = dependency
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://auth.example.test",
    ) as client:
        return await client.request(method, path, **kwargs)


def test_untrusted_kid_type_returns_4xx(audit_settings):
    token = jwt.encode({}, None, algorithm="none", headers={"kid": ["invalid-type"]})
    response = asyncio.run(
        request_with_db(unit_db(), "GET", "/oauth/logout", params={"id_token_hint": token})
    )
    assert 400 <= response.status_code < 500


def test_oauth_missing_grant_uses_protocol_error(audit_settings):
    response = asyncio.run(
        request_with_db(unit_db(), "POST", "/oauth/token", data={"client_id": "audit-rp"})
    )
    assert response.status_code == 400
    assert response.json().get("error") == "invalid_request"


def test_token_response_disables_caching(audit_settings, monkeypatch):
    from app.schemas.oidc import TokenResponse

    monkeypatch.setattr(
        OIDCService,
        "exchange_code",
        AsyncMock(return_value=TokenResponse(access_token="audit-placeholder", expires_in=60)),
    )
    response = asyncio.run(
        request_with_db(
            unit_db(),
            "POST",
            "/oauth/token",
            data={
                "client_id": "audit-rp",
                "grant_type": "authorization_code",
                "code": "synthetic",
                "redirect_uri": "https://rp.example.test/callback",
                "code_verifier": "x" * 43,
            },
        )
    )
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Pragma") == "no-cache"


@pytest.mark.parametrize(
    "authenticated,prompt,expected", [(False, "none", "login_required"), (True, "login", "/login")]
)
def test_authorize_honors_prompt(audit_settings, monkeypatch, authenticated, prompt, expected):
    user = user_record()
    client = OIDCClient(
        id=uuid.uuid4(),
        client_id="audit-rp",
        is_active=True,
        client_type="public",
        redirect_uris=[OIDCRedirectUri(uri="https://rp.example.test/callback")],
    )
    session = Session(
        id=uuid.uuid4(),
        user_id=user.id,
        purpose="full",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        last_activity_at=datetime.now(timezone.utc),
    )
    db = unit_db()

    async def execute(statement, *args, **kwargs):
        query = str(statement)
        return result(
            client
            if "FROM oidc_clients" in query
            else session
            if "FROM sessions" in query
            else user
        )

    db.execute.side_effect = execute
    db.scalar.return_value = user
    monkeypatch.setattr(privacy_service, "has_current_acceptance", AsyncMock(return_value=True))
    response = asyncio.run(
        request_with_db(
            db,
            "GET",
            "/oauth/authorize",
            params={
                "client_id": "audit-rp",
                "redirect_uri": "https://rp.example.test/callback",
                "response_type": "code",
                "code_challenge": "A" * 43,
                "code_challenge_method": "S256",
                "scope": "openid",
                "prompt": prompt,
            },
            headers={"Cookie": "__Host-alx_session=synthetic-session"} if authenticated else {},
        )
    )
    assert expected in response.headers.get("Location", "")


def test_repeated_failed_login_is_throttled(audit_settings):
    db = unit_db()
    db.execute.return_value = result(None)

    async def exercise():
        for _ in range(20):
            try:
                await AuthService.authenticate_user(
                    db, "audit-absent", "not-a-credential", "192.0.2.1", settings=audit_settings
                )
            except AuthenticationException:
                pass
            except Exception as error:
                if getattr(error, "status_code", None) == 429:
                    return True
                raise
        return False

    assert asyncio.run(exercise()) is True


def test_totp_setup_does_not_disable_existing_factor(audit_settings):
    user = user_record()
    cred = TOTPCredential(
        user_id=user.id,
        encrypted_secret=security.encrypt_totp_secret("JBSWY3DPEHPK3PXP"),
        is_confirmed=True,
    )
    db = unit_db()
    db.execute.return_value = result(cred)
    asyncio.run(TOTPService.setup_totp(db, user))
    assert cred.is_confirmed is True


def test_password_change_revokes_refresh_and_authorization_codes(audit_settings):
    user = user_record()
    first = secrets.token_urlsafe(24)
    user.password_credential = PasswordCredential(password_hash=security.hash_password(first))
    db = unit_db()
    asyncio.run(AuthService.change_password(db, user, first, secrets.token_urlsafe(24)))
    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    assert any("refresh_tokens" in statement for statement in statements)
    assert any("authorization_codes" in statement for statement in statements)


def test_required_email_checked_before_mfa_step(audit_settings):
    audit_settings.FEATURE_TOTP_ENABLED = True
    audit_settings.REQUIRE_VERIFIED_EMAIL = True
    user = user_record()
    user.email_verified = False
    first = secrets.token_urlsafe(24)
    user.password_credential = PasswordCredential(password_hash=security.hash_password(first))
    user.totp_credential = TOTPCredential(is_confirmed=True)
    db = unit_db()
    db.execute.return_value = result(user)
    with pytest.raises(AuthenticationException):
        asyncio.run(
            AuthService.authenticate_user(db, user.username, first, settings=audit_settings)
        )


def test_admin_email_change_clears_verification(audit_settings, monkeypatch):
    user = user_record()
    db = unit_db()
    monkeypatch.setattr(AdminService, "get_user_by_id", AsyncMock(return_value=user))
    asyncio.run(AdminService.update_user(db, user.id, user, email="different@example.test"))
    assert user.email_verified is False


def test_mfa_step_invalidated_after_password_change(audit_settings):
    user = user_record()
    first = secrets.token_urlsafe(24)
    user.password_credential = PasswordCredential(password_hash=security.hash_password(first))
    step = security.create_jwt(
        {"sub": str(user.id), "purpose": "mfa_step", "methods": ["totp"]}, 300
    )
    db = unit_db()
    db.execute.return_value = result(user)
    asyncio.run(AuthService.change_password(db, user, first, secrets.token_urlsafe(24)))
    with pytest.raises(AuthenticationException):
        asyncio.run(AuthService.verify_mfa_step_token(step, db))


def test_revoke_does_not_delete_unbound_sso_session(audit_settings, monkeypatch):
    db = unit_db()
    client = OIDCClient(id=uuid.uuid4(), client_id="audit-rp", client_type="public", is_active=True)
    session = Session(id=uuid.uuid4(), user_id=uuid.uuid4())
    monkeypatch.setattr(OIDCService, "get_and_validate_client", AsyncMock(return_value=client))
    db.execute.side_effect = [result(None), result(session)]
    asyncio.run(OIDCService.revoke_token(db, client.client_id, None, "synthetic-session"))
    db.delete.assert_not_awaited()


def test_cors_production_does_not_trust_local_origins(audit_settings):
    audit_settings.ENVIRONMENT = "production"
    response = asyncio.run(
        request_with_db(
            unit_db(),
            "OPTIONS",
            "/api/v1/auth/me",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    )
    assert response.headers.get("Access-Control-Allow-Origin") is None


def test_missing_secret_cannot_survive_production_config():
    with pytest.raises(ValidationError):
        config.Settings(
            _env_file=None, ENVIRONMENT="production", SESSION_SECRET_KEY="", TOTP_ENCRYPTION_KEY=""
        )


def test_rp_logout_accepts_post(audit_settings):
    response = asyncio.run(
        request_with_db(unit_db(), "POST", "/oauth/logout", data={"id_token_hint": "synthetic"})
    )
    assert response.status_code != 405


def test_rp_logout_can_terminate_current_session_with_expired_hint(audit_settings, monkeypatch):
    user = user_record()
    token = security.create_jwt(
        {"sub": str(user.id), "aud": "audit-rp", "token_use": "id_token"}, -60
    )
    client = OIDCClient(id=uuid.uuid4(), client_id="audit-rp", client_type="public", is_active=True)
    monkeypatch.setattr(OIDCService, "get_and_validate_client", AsyncMock(return_value=client))
    db = unit_db()
    db.execute.return_value = result(Session(user_id=user.id))
    response = asyncio.run(
        request_with_db(
            db,
            "GET",
            "/oauth/logout",
            params={"id_token_hint": token},
            headers={"Cookie": "__Host-alx_session=synthetic-session"},
        )
    )
    assert response.status_code == 302
    db.delete.assert_awaited_once()


def test_production_missing_key_stays_stable_across_worker_restart(audit_settings, monkeypatch):
    audit_settings.ENVIRONMENT = "production"
    monkeypatch.setattr(security, "_cached_private_key", None)
    first = security.get_rsa_public_key().public_numbers()
    monkeypatch.setattr(security, "_cached_private_key", None)
    second = security.get_rsa_public_key().public_numbers()
    assert first == second


def test_refresh_after_password_change_is_rejected(audit_settings, monkeypatch):
    from app.models.oidc import RefreshToken

    user = user_record()
    old_password = secrets.token_urlsafe(24)
    user.password_credential = PasswordCredential(
        password_hash=security.hash_password(old_password)
    )
    raw_refresh = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    client = OIDCClient(id=uuid.uuid4(), client_id="audit-rp", client_type="public", is_active=True)
    refresh = RefreshToken(
        user_id=user.id,
        client_id=client.id,
        family_id=uuid.uuid4(),
        token_hash=security.hash_token(raw_refresh),
        scope="openid",
        is_revoked=False,
        expires_at=now + timedelta(days=1),
        created_at=now,
    )
    db = unit_db()

    async def scalar(statement, *args, **kwargs):
        return user.id if "SELECT refresh_tokens.user_id" in str(statement) else user

    db.scalar.side_effect = scalar

    async def execute(statement, *args, **kwargs):
        query = str(statement)
        if "SELECT refresh_tokens.created_at" in query:
            return result(now)
        if "FROM refresh_tokens" in query:
            return result(refresh)
        return result(user)

    db.execute.side_effect = execute
    monkeypatch.setattr(OIDCService, "get_and_validate_client", AsyncMock(return_value=client))
    monkeypatch.setattr(privacy_service, "has_current_acceptance", AsyncMock(return_value=True))

    async def exercise():
        await AuthService.change_password(db, user, old_password, secrets.token_urlsafe(24))
        await OIDCService.rotate_refresh_token(db, client.client_id, None, raw_refresh)

    with pytest.raises(OAuthErrorException):
        asyncio.run(exercise())


def test_smtp_starttls_checks_peer_certificate(audit_settings, monkeypatch):
    import ssl
    from email.message import EmailMessage

    from app.services import verification_email

    audit_settings.SMTP_USE_TLS = True
    server = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = server
    monkeypatch.setattr(verification_email.smtplib, "SMTP", factory)
    verification_email._send_smtp(EmailMessage(), audit_settings)
    context = server.starttls.call_args.kwargs.get("context")
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_required_email_applies_to_existing_grant_token_issue(audit_settings, monkeypatch):
    audit_settings.REQUIRE_VERIFIED_EMAIL = True
    user = user_record()
    user.email_verified = False
    client = OIDCClient(id=uuid.uuid4(), client_id="audit-rp", client_type="public", is_active=True)
    db = unit_db()
    db.scalar.return_value = user
    monkeypatch.setattr(privacy_service, "has_current_acceptance", AsyncMock(return_value=True))
    with pytest.raises(OAuthErrorException):
        asyncio.run(OIDCService._generate_tokens_for_user(db, user, client, "openid email"))
