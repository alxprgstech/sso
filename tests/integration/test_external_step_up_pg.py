"""PostgreSQL integration coverage for external transaction step-up."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import httpx
import pyotp
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.config import Settings, get_settings
from app.core.security import async_hash_password, hash_password, hash_token
from app.main import app
from app.models.oidc import OIDCClient, OIDCRedirectUri
from app.models.session import Session
from app.models.step_up import ExternalStepUpRequest
from app.models.user import PasswordCredential, User
from app.services.mfa_service import (
    PasskeyRegistration,
    WebAuthnContext,
    WebAuthnService,
)
from app.services.totp_service import TOTPService
from sqlalchemy import select

from tests.helpers.privacy import accept_current_documents, record_test_consent
from tests.helpers.webauthn_authenticator import Authenticator

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
PASSWORD = "ExternalStepUpRegression2026!"  # pragma: allowlist secret
REDIRECT_URI = "https://rp.example.test/step-up/callback"
ACTION = "critical_settings_change"
CLIENT_SECRET = "sec_ExternalStepUpSyntheticSecret2026"  # pragma: allowlist secret


@pytest.fixture
def step_up_profile():
    cfg = Settings(
        _env_file=None,
        ENVIRONMENT="testing",
        FEATURE_EXTERNAL_STEP_UP_ENABLED=True,
        FEATURE_TOTP_ENABLED=True,
        FEATURE_PASSKEY_ENABLED=True,
        REQUIRE_ADMIN_MFA=False,
        WEBAUTHN_RP_ID="localhost",
        WEBAUTHN_ORIGIN="http://localhost:5173",
        REDIRECT_TRANSPORT_PROFILE="local",
    )
    app.dependency_overrides[get_settings] = lambda: cfg
    yield cfg
    app.dependency_overrides.pop(get_settings, None)


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    return verifier, challenge


async def create_rp(
    db,
    *,
    name: str,
    secret: str = CLIENT_SECRET,
    enabled: bool = True,
    assurance: str = "reauth_basic",
    action: str = ACTION,
    redirect_uri: str = REDIRECT_URI,
) -> OIDCClient:
    client = OIDCClient(
        id=uuid.uuid4(),
        client_id=f"client_{secrets.token_urlsafe(16)}",
        client_name=name,
        client_type="confidential",
        client_secret_hash=await async_hash_password(secret),
        is_active=True,
        allowed_scopes="openid profile email",
        step_up_enabled=enabled,
        step_up_assurance_levels=assurance,
        step_up_actions=action,
        step_up_max_ttl_seconds=120,
    )
    db.add(client)
    await db.flush()
    db.add(OIDCRedirectUri(client_id=client.id, uri=redirect_uri))
    await db.commit()
    await db.refresh(client, ["redirect_uris"])
    return client


async def login_user(client, db, *, username="step_up_user", email="step-up@example.test"):
    code, _ = await execute_bootstrap(db, username, email, PASSWORD, "closed")
    assert code == 0
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.json()
    await accept_current_documents(client, response)
    user = await db.scalar(select(User).where(User.username == username))
    assert user is not None
    session = await db.scalar(
        select(Session)
        .where(Session.user_id == user.id)
        .order_by(Session.created_at.desc())
        .limit(1)
    )
    assert session is not None
    return user, session, {"X-CSRF-Token": response.json()["csrf_token"]}


async def seed_totp(db, user, session) -> str:
    secret, _ = await TOTPService.setup_totp(db, user, session.id)
    assert await TOTPService.confirm_totp(db, user, pyotp.TOTP(secret).now(), session.id)
    await db.commit()
    await db.refresh(user)
    return secret


async def seed_passkey(db, user, session, cfg) -> Authenticator:
    authenticator = Authenticator()
    options = await WebAuthnService.get_registration_options(
        db, user, WebAuthnContext(settings=cfg, session_id=session.id)
    )
    credential = authenticator.registration(options, cfg.WEBAUTHN_ORIGIN)
    assert await WebAuthnService.verify_registration(
        db,
        user,
        PasskeyRegistration(credential, "Synthetic Passkey"),
        WebAuthnContext(settings=cfg, session_id=session.id),
    )
    await db.commit()
    await db.refresh(user)
    return authenticator


async def create_step_up(
    client,
    rp: OIDCClient,
    *,
    subject: uuid.UUID,
    assurance: str = "reauth_basic",
    action: str = ACTION,
    secret: str = CLIENT_SECRET,
    redirect_uri: str = REDIRECT_URI,
    verifier: str | None = None,
    challenge: str | None = None,
    state: str | None = None,
    nonce: str | None = None,
    payload_hash: str | None = None,
) -> tuple[httpx.Response, dict, str, str]:
    if verifier is None or challenge is None:
        verifier, challenge = pkce_pair()
    body = {
        "subject": str(subject),
        "action": action,
        "payload_hash": payload_hash or hashlib.sha256(b'{"enabled":true}').hexdigest(),
        "description": "Изменение критических настроек приложения",
        "assurance": assurance,
        "redirect_uri": redirect_uri,
        "state": state or secrets.token_urlsafe(24),
        "nonce": nonce or secrets.token_urlsafe(24),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "ttl_seconds": 120,
    }
    response = await client.post("/api/v1/step-up/requests", auth=(rp.client_id, secret), json=body)
    return response, body, verifier, challenge


def response_code(redirect_to: str) -> tuple[str, str]:
    parsed = urlsplit(redirect_to)
    values = dict(parse_qsl(parsed.query))
    return values["code"], values["state"]


async def verify_factor(
    client, token: str, headers: dict[str, str], plan: str, method: str, **values
):
    return await client.post(
        f"/api/v1/step-up/requests/{token}/verify",
        headers=headers,
        json={"plan": plan, "method": method, **values},
    )


async def redeem(
    client,
    rp,
    code: str,
    verifier: str,
    *,
    secret: str | None = None,
    redirect_uri: str = REDIRECT_URI,
):
    return await client.post(
        "/api/v1/step-up/redeem",
        auth=(rp.client_id, secret or CLIENT_SECRET),
        json={
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        },
    )


@pytest.mark.asyncio
async def test_password_basic_one_use_cross_client_and_pkce(pg_session, pg_client, step_up_profile):
    user, _, headers = await login_user(pg_client, pg_session)
    rp = await create_rp(pg_session, name="Synthetic RP")
    other = await create_rp(pg_session, name="Other RP")
    created, body, verifier, _ = await create_step_up(pg_client, rp, subject=user.id)
    assert created.status_code == 201, created.json()
    token = created.json()["request_token"]
    assert created.json()["plans"][0]["id"] == "password"

    details = await pg_client.get(f"/api/v1/step-up/requests/{token}")
    assert details.status_code == 200, details.json()
    assert details.json()["client_name"] == "Synthetic RP"
    assert details.json()["description"] == body["description"]

    assert (
        await verify_factor(pg_client, token, {}, "password", "password", password=PASSWORD)
    ).status_code == 403
    assert (
        await verify_factor(
            pg_client,
            token,
            headers,
            "password",
            "password",
            password="wrong-password",  # pragma: allowlist secret
        )
    ).status_code == 401
    result = await verify_factor(
        pg_client, token, headers, "password", "password", password=PASSWORD
    )
    assert result.status_code == 200, result.json()
    assert result.json()["completed"] is True
    redirect_to = result.json()["redirect_to"]
    code, returned_state = response_code(redirect_to)
    assert returned_state == body["state"]
    assert "iss=" in redirect_to

    cross_client = await redeem(pg_client, other, code, verifier)
    assert cross_client.status_code == 400
    wrong_redirect = await redeem(
        pg_client, rp, code, verifier, redirect_uri="https://evil.example.test/callback"
    )
    assert wrong_redirect.status_code == 400
    wrong_pkce = await redeem(pg_client, rp, code, "x" * 43)
    assert wrong_pkce.status_code == 400

    redeemed = await redeem(pg_client, rp, code, verifier)
    assert redeemed.status_code == 200, redeemed.json()
    from app.core.security import decode_jwt

    payload = decode_jwt(
        redeemed.json()["proof"],
        audience=rp.client_id,
        expected_use="external_step_up_proof",
    )
    assert payload["sub"] == str(user.id)
    assert payload["action"] == ACTION
    assert payload["payload_hash"] == body["payload_hash"]
    assert payload["acr"] == "reauth_basic"
    assert payload["amr"] == ["pwd"]
    assert payload["nonce"] == body["nonce"]
    assert payload["transaction_id"]

    replay = await redeem(pg_client, rp, code, verifier)
    assert replay.status_code == 409
    assert replay.json()["error"] == "proof_replayed"

    row = await pg_session.scalar(select(ExternalStepUpRequest))
    assert row is not None and row.consumed_at is not None
    assert row.status == "consumed"


@pytest.mark.asyncio
async def test_password_and_passkey_strict_flow(pg_session, pg_client, step_up_profile):
    user, session, headers = await login_user(
        pg_client, pg_session, username="step_up_strict", email="strict@example.test"
    )
    authenticator = await seed_passkey(pg_session, user, session, step_up_profile)
    rp = await create_rp(pg_session, name="Strict RP", assurance="reauth_strict")
    created, _, verifier, _ = await create_step_up(
        pg_client, rp, subject=user.id, assurance="reauth_strict"
    )
    assert created.status_code == 201, created.json()
    token = created.json()["request_token"]
    plan = "password_passkey"
    details = await pg_client.get(f"/api/v1/step-up/requests/{token}")
    assert details.status_code == 200
    assert details.json()["plans"][0]["id"] == plan

    early = await pg_client.post(
        f"/api/v1/step-up/requests/{token}/passkey/options",
        headers=headers,
        json={"plan": plan},
    )
    assert early.status_code == 200
    early_assertion = authenticator.assertion(early.json(), step_up_profile.WEBAUTHN_ORIGIN)
    denied = await verify_factor(
        pg_client, token, headers, plan, "passkey", credential=early_assertion
    )
    assert denied.status_code == 409
    assert denied.json()["error"] == "step_up_factor_order"

    password = await verify_factor(pg_client, token, headers, plan, "password", password=PASSWORD)
    assert password.status_code == 200 and password.json()["completed"] is False
    options = await pg_client.post(
        f"/api/v1/step-up/requests/{token}/passkey/options",
        headers=headers,
        json={"plan": plan},
    )
    assert options.status_code == 200, options.json()
    assertion = authenticator.assertion(options.json(), step_up_profile.WEBAUTHN_ORIGIN)
    completed = await verify_factor(
        pg_client, token, headers, plan, "passkey", credential=assertion
    )
    assert completed.status_code == 200, completed.json()
    code, _ = response_code(completed.json()["redirect_to"])
    redeemed = await redeem(pg_client, rp, code, verifier)
    assert redeemed.status_code == 200, redeemed.json()
    from app.core.security import decode_jwt

    payload = decode_jwt(
        redeemed.json()["proof"],
        audience=rp.client_id,
        expected_use="external_step_up_proof",
    )
    assert payload["acr"] == "reauth_strict"
    assert payload["amr"] == ["pwd", "hwk"]


@pytest.mark.asyncio
async def test_passkey_only_satisfies_mfa_policy(pg_session, pg_client, step_up_profile):
    user, session, headers = await login_user(
        pg_client, pg_session, username="step_up_passkey_mfa", email="passkey-mfa@example.test"
    )
    authenticator = await seed_passkey(pg_session, user, session, step_up_profile)
    rp = await create_rp(pg_session, name="Passkey MFA RP", assurance="reauth_mfa")
    created, _, verifier, _ = await create_step_up(
        pg_client, rp, subject=user.id, assurance="reauth_mfa"
    )
    assert created.status_code == 201, created.json()
    token = created.json()["request_token"]
    details = await pg_client.get(f"/api/v1/step-up/requests/{token}")
    assert details.status_code == 200
    plan = details.json()["plans"][0]["id"]
    assert plan == "passkey"
    options = await pg_client.post(
        f"/api/v1/step-up/requests/{token}/passkey/options",
        headers=headers,
        json={"plan": plan},
    )
    assert options.status_code == 200, options.json()
    assertion = authenticator.assertion(options.json(), step_up_profile.WEBAUTHN_ORIGIN)
    completed = await verify_factor(
        pg_client, token, headers, plan, "passkey", credential=assertion
    )
    assert completed.status_code == 200 and completed.json()["completed"] is True
    code, _ = response_code(completed.json()["redirect_to"])
    redeemed = await redeem(pg_client, rp, code, verifier)
    assert redeemed.status_code == 200, redeemed.json()
    from app.core.security import decode_jwt

    payload = decode_jwt(
        redeemed.json()["proof"],
        audience=rp.client_id,
        expected_use="external_step_up_proof",
    )
    assert payload["acr"] == "reauth_mfa"
    assert payload["amr"] == ["hwk"]


@pytest.mark.asyncio
async def test_password_and_totp_order_and_totp_replay(pg_session, pg_client, step_up_profile):
    user, session, headers = await login_user(
        pg_client, pg_session, username="step_up_totp", email="totp@example.test"
    )
    secret = await seed_totp(pg_session, user, session)
    rp = await create_rp(pg_session, name="TOTP RP", assurance="reauth_password_mfa")
    created, _, verifier, _ = await create_step_up(
        pg_client, rp, subject=user.id, assurance="reauth_password_mfa"
    )
    assert created.status_code == 201, created.json()
    token = created.json()["request_token"]
    plan = "password_totp"
    # Enrollment already consumed the current step; use the next valid step
    # rather than weakening replay protection in the test.
    code_now = pyotp.TOTP(secret).at(datetime.now(timezone.utc) + timedelta(seconds=30))

    assert (
        await verify_factor(pg_client, token, headers, plan, "totp", code=code_now)
    ).status_code == 409
    assert (
        await verify_factor(pg_client, token, headers, plan, "password", password=PASSWORD)
    ).json()["completed"] is False
    completed = await verify_factor(pg_client, token, headers, plan, "totp", code=code_now)
    assert completed.status_code == 200, completed.json()
    assert completed.json()["completed"] is True
    code, _ = response_code(completed.json()["redirect_to"])
    assert (await redeem(pg_client, rp, code, verifier)).status_code == 200

    second, _, _, _ = await create_step_up(
        pg_client, rp, subject=user.id, assurance="reauth_password_mfa"
    )
    assert second.status_code == 201
    second_token = second.json()["request_token"]
    assert (
        await verify_factor(pg_client, second_token, headers, plan, "password", password=PASSWORD)
    ).status_code == 200
    replay = await verify_factor(pg_client, second_token, headers, plan, "totp", code=code_now)
    assert replay.status_code == 401
    assert replay.json()["error"] == "step_up_factor_rejected"


@pytest.mark.asyncio
async def test_subject_session_expiry_denial_and_policy_failures(
    pg_session, pg_client, step_up_profile
):
    user, _, headers = await login_user(
        pg_client, pg_session, username="step_up_binding", email="binding@example.test"
    )
    rp = await create_rp(pg_session, name="Binding RP")
    created, _, _, _ = await create_step_up(pg_client, rp, subject=user.id)
    assert created.status_code == 201
    token = created.json()["request_token"]
    assert (await pg_client.get(f"/api/v1/step-up/requests/{token}")).status_code == 200

    # Same account, a second browser session: the challenge is already bound.
    second_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )
    try:
        second_login = await second_client.post(
            "/api/v1/auth/login",
            json={"username": "step_up_binding", "password": PASSWORD},
        )
        await accept_current_documents(second_client, second_login)
        cross_session = await second_client.get(f"/api/v1/step-up/requests/{token}")
        assert cross_session.status_code == 409
        assert cross_session.json()["error"] == "step_up_session_mismatch"
    finally:
        await second_client.aclose()

    # A different account cannot view the request.
    other = User(
        id=uuid.uuid4(),
        username="step_up_other",
        email="other@example.test",
        is_active=True,
        email_verified=True,
    )
    other.password_credential = PasswordCredential(
        user_id=other.id, password_hash=hash_password(PASSWORD)
    )
    pg_session.add(other)
    await record_test_consent(pg_session, other)
    await pg_session.commit()
    other_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )
    try:
        login_other = await other_client.post(
            "/api/v1/auth/login",
            json={"username": "step_up_other", "password": PASSWORD},
        )
        await accept_current_documents(other_client, login_other)
        mismatch = await other_client.get(f"/api/v1/step-up/requests/{token}")
        assert mismatch.status_code == 403
        assert mismatch.json()["error"] == "step_up_subject_mismatch"
    finally:
        await other_client.aclose()

    # The original session can still explicitly deny; no proof is created.
    denied = await pg_client.post(f"/api/v1/step-up/requests/{token}/deny", headers=headers)
    assert denied.status_code == 200
    after_deny = await pg_client.get(f"/api/v1/step-up/requests/{token}")
    assert after_deny.status_code == 410

    # High assurance without a suitable factor is rejected before a proof exists.
    mfa_rp = await create_rp(pg_session, name="MFA RP", assurance="reauth_mfa")
    unavailable = await create_step_up(pg_client, mfa_rp, subject=user.id, assurance="reauth_mfa")
    assert unavailable[0].status_code == 403
    assert unavailable[0].json()["error"] == "assurance_unavailable"

    # A client without the opt-in flag cannot create a challenge.
    disabled = await create_rp(pg_session, name="Disabled RP", enabled=False)
    denied_create, _, _, _ = await create_step_up(pg_client, disabled, subject=user.id)
    assert denied_create.status_code == 403
    assert denied_create.json()["error"] == "step_up_not_enabled"


@pytest.mark.asyncio
async def test_expiry_revision_and_session_revocation_invalidate(
    pg_session, pg_client, step_up_profile
):
    user, session, headers = await login_user(
        pg_client, pg_session, username="step_up_lifecycle", email="lifecycle@example.test"
    )
    rp = await create_rp(pg_session, name="Lifecycle RP")

    expired, _, _, _ = await create_step_up(pg_client, rp, subject=user.id)
    assert expired.status_code == 201
    expired_token = expired.json()["request_token"]
    assert (await pg_client.get(f"/api/v1/step-up/requests/{expired_token}")).status_code == 200
    expired_row = await pg_session.scalar(
        select(ExternalStepUpRequest).where(
            ExternalStepUpRequest.request_token_hash == hash_token(expired_token)
        )
    )
    assert expired_row is not None
    expired_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await pg_session.commit()
    expired_view = await pg_client.get(f"/api/v1/step-up/requests/{expired_token}")
    assert expired_view.status_code == 410
    assert expired_view.json()["error"] == "step_up_expired"

    revision, _, _, _ = await create_step_up(pg_client, rp, subject=user.id)
    assert revision.status_code == 201
    revision_token = revision.json()["request_token"]
    assert (await pg_client.get(f"/api/v1/step-up/requests/{revision_token}")).status_code == 200
    user.security_revision += 1
    session.security_revision = user.security_revision
    await pg_session.commit()
    changed = await pg_client.get(f"/api/v1/step-up/requests/{revision_token}")
    assert changed.status_code == 409
    assert changed.json()["error"] == "step_up_invalidated"

    # A fresh login starts a new security-revision session.
    relogin = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "step_up_lifecycle", "password": PASSWORD},
    )
    assert relogin.status_code == 200
    await accept_current_documents(pg_client, relogin)
    fresh_headers = {"X-CSRF-Token": relogin.json()["csrf_token"]}
    current_session = await pg_session.scalar(
        select(Session)
        .where(Session.user_id == user.id)
        .order_by(Session.created_at.desc())
        .limit(1)
    )
    assert current_session is not None

    proof_expiry, _, proof_verifier, _ = await create_step_up(pg_client, rp, subject=user.id)
    assert proof_expiry.status_code == 201
    proof_token = proof_expiry.json()["request_token"]
    approved = await verify_factor(
        pg_client, proof_token, fresh_headers, "password", "password", password=PASSWORD
    )
    assert approved.status_code == 200 and approved.json()["completed"] is True
    proof_code, _ = response_code(approved.json()["redirect_to"])
    proof_row = await pg_session.scalar(
        select(ExternalStepUpRequest).where(
            ExternalStepUpRequest.request_token_hash == hash_token(proof_token)
        )
    )
    assert proof_row is not None and proof_row.proof_token_hash
    proof_row.proof_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await pg_session.commit()
    expired_proof = await redeem(pg_client, rp, proof_code, proof_verifier)
    assert expired_proof.status_code == 410
    assert expired_proof.json()["error"] == "proof_expired"

    revoked, _, _, _ = await create_step_up(pg_client, rp, subject=user.id)
    assert revoked.status_code == 201
    revoked_token = revoked.json()["request_token"]
    assert (await pg_client.get(f"/api/v1/step-up/requests/{revoked_token}")).status_code == 200
    await pg_session.delete(current_session)
    await pg_session.commit()
    revoked_view = await pg_client.get(f"/api/v1/step-up/requests/{revoked_token}")
    assert revoked_view.status_code == 401


@pytest.mark.asyncio
async def test_installed_sdk_creates_and_redeems_real_step_up(
    pg_session, pg_client, step_up_profile, monkeypatch
):
    """The public SDK must speak the real protocol, not a local mock."""
    from alxprgs_sso import SSOClient, StepUpReplayError

    real_async_client = httpx.AsyncClient

    def asgi_client(*args, **kwargs):
        kwargs.pop("verify", None)
        return real_async_client(
            *args,
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            **kwargs,
        )

    monkeypatch.setattr("alxprgs_sso.client.httpx.AsyncClient", asgi_client)
    user, _, headers = await login_user(
        pg_client, pg_session, username="step_up_sdk", email="sdk@example.test"
    )
    rp = await create_rp(pg_session, name="SDK RP")
    sdk = SSOClient(
        server_url="https://auth.alxprgs.tech",
        client_id=rp.client_id,
        client_secret=CLIENT_SECRET,
        expected_issuer="https://auth.alxprgs.tech",
    )
    request = await sdk.create_step_up_request(
        action=ACTION,
        payload_hash=hashlib.sha256(b'{"enabled":true}').hexdigest(),
        subject=str(user.id),
        assurance="reauth_basic",
        redirect_uri=REDIRECT_URI,
        description="Изменить критические настройки",
        ttl_seconds=120,
    )
    details = await pg_client.get(f"/api/v1/step-up/requests/{request.request_token}")
    assert details.status_code == 200
    approved = await verify_factor(
        pg_client,
        request.request_token,
        headers,
        "password",
        "password",
        password=PASSWORD,
    )
    assert approved.status_code == 200 and approved.json()["completed"] is True
    code, _ = response_code(approved.json()["redirect_to"])
    proof = await sdk.consume_step_up_proof(
        code=code,
        request=request,
        state=request.state,
        expected_subject=str(user.id),
    )
    assert proof.claims.sub == str(user.id)
    assert proof.claims.action == ACTION
    with pytest.raises(StepUpReplayError):
        await sdk.consume_step_up_proof(
            code=code,
            request=request,
            state=request.state,
            expected_subject=str(user.id),
        )


@pytest.mark.asyncio
async def test_redirect_removal_rejects_redeem(pg_session, pg_client, step_up_profile):
    user, _, headers = await login_user(
        pg_client, pg_session, username="step_up_redirect", email="redirect@example.test"
    )
    rp = await create_rp(pg_session, name="Redirect RP")
    created, _, verifier, _ = await create_step_up(pg_client, rp, subject=user.id)
    token = created.json()["request_token"]
    approved = await verify_factor(
        pg_client, token, headers, "password", "password", password=PASSWORD
    )
    assert approved.status_code == 200 and approved.json()["completed"] is True
    code, _ = response_code(approved.json()["redirect_to"])
    redirect = await pg_session.scalar(
        select(OIDCRedirectUri).where(OIDCRedirectUri.client_id == rp.id)
    )
    assert redirect is not None
    await pg_session.delete(redirect)
    await pg_session.commit()
    rejected = await redeem(pg_client, rp, code, verifier)
    assert rejected.status_code == 400
    assert rejected.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_client_policy_is_opt_in_and_confidential_only(pg_session):
    from app.core.exceptions import AuthorizationException
    from app.services.admin_service import AdminService

    client, secret = await AdminService.create_client(
        pg_session,
        client_name="Default Off RP",
        client_type="confidential",
        redirect_uris=[REDIRECT_URI],
        allowed_scopes=["openid"],
    )
    assert secret
    assert client.step_up_enabled is False
    assert client.step_up_assurance_levels == ""
    assert client.step_up_actions == ""

    with pytest.raises(AuthorizationException):
        await AdminService.create_client(
            pg_session,
            client_name="Public Step-up",
            client_type="public",
            redirect_uris=[REDIRECT_URI],
            allowed_scopes=["openid"],
            step_up_enabled=True,
            step_up_assurance_levels=["reauth_basic"],
            step_up_actions=[ACTION],
        )
    with pytest.raises(AuthorizationException):
        await AdminService.create_client(
            pg_session,
            client_name="Incomplete Policy",
            client_type="confidential",
            redirect_uris=[REDIRECT_URI],
            allowed_scopes=["openid"],
            step_up_enabled=True,
            step_up_assurance_levels=[],
            step_up_actions=[],
        )

    updated = await AdminService.update_client_step_up(
        pg_session,
        client.client_id,
        enabled=True,
        assurance_levels=["reauth_mfa"],
        actions=[ACTION],
        max_ttl_seconds=90,
    )
    assert updated.step_up_enabled is True
    assert updated.step_up_assurance_levels == "reauth_mfa"
    assert updated.step_up_actions == ACTION
    assert updated.step_up_max_ttl_seconds == 90


@pytest.mark.asyncio
async def test_feature_flag_disabled_has_no_endpoint(pg_session, pg_client):
    user, _, _ = await login_user(
        pg_client, pg_session, username="step_up_disabled", email="disabled@example.test"
    )
    cfg = Settings(
        _env_file=None,
        ENVIRONMENT="testing",
        FEATURE_EXTERNAL_STEP_UP_ENABLED=False,
        REDIRECT_TRANSPORT_PROFILE="local",
    )
    app.dependency_overrides[get_settings] = lambda: cfg
    try:
        rp = await create_rp(pg_session, name="Disabled Feature RP")
        response = await pg_client.post(
            "/api/v1/step-up/requests",
            auth=(rp.client_id, CLIENT_SECRET),
            json={
                "subject": str(user.id),
                "action": ACTION,
                "payload_hash": hashlib.sha256(b"{}").hexdigest(),
                "description": "Synthetic action",
                "assurance": "reauth_basic",
                "redirect_uri": REDIRECT_URI,
                "state": secrets.token_urlsafe(24),
                "nonce": secrets.token_urlsafe(24),
                "code_challenge": pkce_pair()[1],
                "ttl_seconds": 60,
            },
        )
        assert response.status_code == 404
        assert response.json()["error"] == "feature_disabled"
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_concurrent_redemption_has_exactly_one_winner(pg_session, pg_client, step_up_profile):
    user, _, headers = await login_user(
        pg_client, pg_session, username="step_up_race", email="race@example.test"
    )
    rp = await create_rp(pg_session, name="Race RP")
    created, _, verifier, _ = await create_step_up(pg_client, rp, subject=user.id)
    token = created.json()["request_token"]
    result = await verify_factor(
        pg_client, token, headers, "password", "password", password=PASSWORD
    )
    assert result.status_code == 200 and result.json()["completed"] is True
    code, _ = response_code(result.json()["redirect_to"])
    outcomes = await asyncio.gather(
        redeem(pg_client, rp, code, verifier),
        redeem(pg_client, rp, code, verifier),
    )
    statuses = sorted(response.status_code for response in outcomes)
    assert statuses == [200, 409]
    assert any(response.json().get("error") == "proof_replayed" for response in outcomes)
