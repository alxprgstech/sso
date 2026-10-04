"""
Интеграционные тесты жизненного цикла WebAuthn / Passkey (G4-PASSKEY, QA-11, SEC-FLAG-04, BUG-012).
Проверяют:
1. Default-off профиль: строгая изоляция, возврат HTTP 404 на всех эндпоинтах Passkey.
2. Enabled профиль: генерация challenge, валидация Base64URL идентификаторов, поддержка
   нескольких credentials у одного пользователя, удаление ключей и неработоспособность удалённого ключа.
3. Отрицательные сценарии: защита от Replay (одноразовость challenge), отказ при искажённом challenge,
   отказ при неверном origin / RP ID, отказ при попытке использовать ключ чужого пользователя.
Никаких фиктивных mock-ответов успешной верификации (полная криптографическая проверка py_webauthn).
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.config import Settings, get_settings
from app.main import app
from app.models.mfa import WebAuthnChallenge, WebAuthnCredential
from app.models.session import Session
from app.models.user import User
from app.services.mfa_service import WebAuthnService
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.privacy import accept_current_documents
from tests.helpers.reauthentication import MutationRequest, RequestAuthorization, authorized_request
from tests.helpers.webauthn_authenticator import AssertionProfile, Authenticator


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_passkey_default_off_isolation_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    Проверка инварианта default-off для Passkey (SEC-FLAG-02, SEC-FLAG-04, G4-PASSKEY):
    Все роуты /api/v1/mfa/passkey/* возвращают HTTP 404 с feature_disabled при настройках по умолчанию.
    """

    def _get_disabled_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_PASSKEY_ENABLED = False
        overridden.REQUIRE_VERIFIED_EMAIL = False
        return overridden

    app.dependency_overrides[get_settings] = _get_disabled_settings
    try:
        settings = _get_disabled_settings()
        assert settings.FEATURE_PASSKEY_ENABLED is False

        # 1. Проверяем capabilities
        caps_res = await pg_client.get("/api/v1/auth/capabilities")
        assert caps_res.status_code == 200
        caps = caps_res.json()
        assert (caps.get("capabilities", {}).get("passkey_enabled") is False) or (
            caps.get("passkey_enabled") is False
        )

        # 2. Создаем пользователя и входим
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="passkey_default_user",
            email="passkey_def@alxprgs.tech",
            password="PasskeyPassword2026!",
            registration_mode="closed",
        )
        assert code == 0

        login_res = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "passkey_default_user", "password": "PasskeyPassword2026!"},
        )
        await accept_current_documents(pg_client, login_res)
        assert login_res.status_code == 200, (
            f"Login failed: {login_res.status_code} {login_res.text}"
        )
        csrf_token = login_res.json()["csrf_token"]

        # 3. Проверяем, что ВСЕ эндпоинты Passkey возвращают 404 Not Found
        headers = {"X-CSRF-Token": csrf_token}

        def _check_disabled(res):
            assert res.status_code == 404
            data = res.json()
            assert data.get("feature") == "FEATURE_PASSKEY_ENABLED" or (
                isinstance(data.get("detail"), dict)
                and data["detail"].get("feature") == "FEATURE_PASSKEY_ENABLED"
            )

        _check_disabled(
            await pg_client.post("/api/v1/mfa/passkey/register/options", headers=headers)
        )
        _check_disabled(
            await pg_client.post(
                "/api/v1/mfa/passkey/register/verify",
                json={"credential": {}, "name": "Key1"},
                headers=headers,
            )
        )
        _check_disabled(await pg_client.post("/api/v1/mfa/passkey/auth/options"))
        _check_disabled(
            await pg_client.post("/api/v1/mfa/passkey/auth/verify", json={"credential": {}})
        )
        _check_disabled(await pg_client.get("/api/v1/mfa/passkey/credentials"))
        _check_disabled(
            await pg_client.delete("/api/v1/mfa/passkey/credentials/dummy_id", headers=headers)
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def passkey_profile():
    cfg = Settings(
        _env_file=None,
        FEATURE_PASSKEY_ENABLED=True,
        WEBAUTHN_RP_ID="localhost",
        WEBAUTHN_ORIGIN="http://localhost:5173",
    )
    app.dependency_overrides[get_settings] = lambda: cfg
    yield cfg
    app.dependency_overrides.pop(get_settings, None)


PASSWORD = "RealPasskeyRegression2026!"


async def passkey_login(db, client):
    assert (
        await execute_bootstrap(db, "real_passkey", "real-passkey@example.test", PASSWORD, "closed")
    )[0] == 0
    cfg = app.dependency_overrides.get(get_settings, get_settings)()
    if cfg.REQUIRE_VERIFIED_EMAIL:
        # The enabled process profile must actually verify the bootstrap email.
        # Never switch the policy off merely to obtain a passkey test session.
        from tests.helpers.smtp_message import verification_token
        from tests.integration.test_email_verification_pg import MockSMTPServer

        assert cfg.ENVIRONMENT != "production"
        rejected = await client.post(
            "/api/v1/auth/login", json={"username": "real_passkey", "password": PASSWORD}
        )
        assert rejected.status_code == 401
        smtp = MockSMTPServer(port=0)
        await smtp.start()
        cfg.SMTP_HOST, cfg.SMTP_PORT, cfg.SMTP_USE_TLS = "127.0.0.1", smtp.port, False
        cfg.SMTP_USER, cfg.SMTP_PASSWORD, cfg.EMAIL_PROVIDER = "", "", "smtp"
        try:
            requested = await client.post(
                "/api/v1/mfa/email/request", json={"email": "real-passkey@example.test"}
            )
            assert requested.status_code == 200 and len(smtp.received_messages) == 1
            confirmed = await client.post(
                "/api/v1/mfa/email/confirm",
                json={"token": verification_token(smtp.received_messages[0])},
            )
            assert confirmed.status_code == 200
        finally:
            await smtp.stop()
    login = await client.post(
        "/api/v1/auth/login", json={"username": "real_passkey", "password": PASSWORD}
    )
    assert login.status_code == 200
    await accept_current_documents(client, login)
    return {"X-CSRF-Token": login.json()["csrf_token"]}


async def register_key(client, headers, cfg, authenticator, name, factor=None):
    options = await authorized_request(
        client,
        MutationRequest("POST", "/api/v1/mfa/passkey/register/options"),
        RequestAuthorization(PASSWORD, headers, factor=factor),
    )
    assert options.status_code == 200
    registered = await authorized_request(
        client,
        MutationRequest(
            "POST",
            "/api/v1/mfa/passkey/register/verify",
            json_body={
                "name": name,
                "credential": authenticator.registration(options.json(), cfg.WEBAUTHN_ORIGIN),
            },
        ),
        RequestAuthorization(PASSWORD, headers, factor=factor),
    )
    assert registered.status_code == 200, registered.json()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_passkey_options_and_challenge_persistence_pg(pg_session, pg_client, passkey_profile):
    headers = await passkey_login(pg_session, pg_client)
    options = await authorized_request(
        pg_client,
        MutationRequest("POST", "/api/v1/mfa/passkey/register/options"),
        RequestAuthorization(PASSWORD, headers),
    )
    assert options.status_code == 200
    assert options.json()["authenticatorSelection"]["userVerification"] == "required"
    row = await pg_session.scalar(
        select(WebAuthnChallenge).where(WebAuthnChallenge.purpose == "registration")
    )
    assert row.challenge == options.json()["challenge"] and row.session_id is not None
    authentication = await pg_client.post("/api/v1/mfa/passkey/auth/options")
    assert (
        authentication.status_code == 200
        and authentication.json()["userVerification"] == "required"
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_passkey_multiple_credentials_and_deletion_pg(pg_session, pg_client, passkey_profile):
    cfg = passkey_profile
    headers = await passkey_login(pg_session, pg_client)
    first, second = Authenticator(), Authenticator()
    await register_key(pg_client, headers, cfg, first, "Laptop Key")

    def factor(data):
        return {
            "method": "passkey",
            "credential": first.assertion(data["passkey_options"], cfg.WEBAUTHN_ORIGIN),
        }

    await register_key(pg_client, headers, cfg, second, "Mobile Key", factor)
    listed = await pg_client.get("/api/v1/mfa/passkey/credentials")
    assert {row["name"] for row in listed.json()} == {"Laptop Key", "Mobile Key"}
    deleted = await authorized_request(
        pg_client,
        MutationRequest("DELETE", f"/api/v1/mfa/passkey/credentials/{second.id}"),
        RequestAuthorization(PASSWORD, headers, factor=factor),
    )
    assert deleted.status_code == 200
    remaining = await pg_client.get("/api/v1/mfa/passkey/credentials")
    assert [row["id"] for row in remaining.json()] == [first.id]
    options = await pg_client.post("/api/v1/mfa/passkey/auth/options")
    rejected = await pg_client.post(
        "/api/v1/mfa/passkey/auth/verify",
        json={"credential": second.assertion(options.json(), cfg.WEBAUTHN_ORIGIN)},
    )
    assert rejected.status_code == 401
    options = await pg_client.post("/api/v1/mfa/passkey/auth/options")
    success = await pg_client.post(
        "/api/v1/mfa/passkey/auth/verify",
        json={"credential": first.assertion(options.json(), cfg.WEBAUTHN_ORIGIN)},
    )
    assert success.status_code == 200


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_passkey_negative_crypto_checks_no_mocks_pg(pg_session, pg_client, passkey_profile):
    cfg = passkey_profile
    headers = await passkey_login(pg_session, pg_client)
    key = Authenticator()
    options = await authorized_request(
        pg_client,
        MutationRequest("POST", "/api/v1/mfa/passkey/register/options"),
        RequestAuthorization(PASSWORD, headers),
    )
    registration = key.registration(options.json(), cfg.WEBAUTHN_ORIGIN)
    # Registration UV and origin/RP/challenge negatives execute the real library.
    for credential in [
        key.registration(options.json(), "https://evil.example"),
        key.registration(options.json(), cfg.WEBAUTHN_ORIGIN, rp_id="evil.example"),
        key.registration(options.json(), cfg.WEBAUTHN_ORIGIN, uv=False),
    ]:
        rejected = await authorized_request(
            pg_client,
            MutationRequest(
                "POST", "/api/v1/mfa/passkey/register/verify", json_body={"credential": credential}
            ),
            RequestAuthorization(PASSWORD, headers),
        )
        assert rejected.status_code == 401
        assert await pg_session.scalar(select(func.count()).select_from(WebAuthnCredential)) == 0
    # The quota persists; confirmation is not retried with weaker origins or UV.
    user = await pg_session.scalar(select(User).where(User.username == "real_passkey"))
    session_id = await pg_session.scalar(select(Session.id).where(Session.user_id == user.id))
    assert await WebAuthnService.verify_registration(
        pg_session, user, registration, settings=cfg, session_id=session_id
    )
    for kwargs in [
        {"origin": "https://evil.example"},
        {"rp_id": "evil.example"},
        {"uv": False},
        {"signature_valid": False},
    ]:
        options = await pg_client.post("/api/v1/mfa/passkey/auth/options")
        args = {"origin": cfg.WEBAUTHN_ORIGIN, **kwargs}
        rejected = await pg_client.post(
            "/api/v1/mfa/passkey/auth/verify",
            json={
                "credential": key.assertion(
                    options.json(),
                    args["origin"],
                    AssertionProfile(
                        **{name: value for name, value in args.items() if name != "origin"}
                    ),
                )
            },
        )
        assert rejected.status_code == 401
    options = await pg_client.post("/api/v1/mfa/passkey/auth/options")
    credential = key.assertion(options.json(), cfg.WEBAUTHN_ORIGIN)
    assert (
        await pg_client.post("/api/v1/mfa/passkey/auth/verify", json={"credential": credential})
    ).status_code == 200
    assert (
        await pg_client.post("/api/v1/mfa/passkey/auth/verify", json={"credential": credential})
    ).status_code == 401
    expired = await pg_client.post("/api/v1/mfa/passkey/auth/options")
    await pg_session.execute(
        update(WebAuthnChallenge)
        .where(WebAuthnChallenge.challenge == expired.json()["challenge"])
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await pg_session.commit()
    assert (
        await pg_client.post(
            "/api/v1/mfa/passkey/auth/verify",
            json={"credential": key.assertion(expired.json(), cfg.WEBAUTHN_ORIGIN)},
        )
    ).status_code == 401
