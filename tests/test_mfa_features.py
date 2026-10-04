import copy
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, os.path.abspath("backend"))

from app.api.mfa import passkey_register_verify
from app.config import Settings, get_settings
from app.core.exceptions import (
    AuthorizationException,
)
from app.database import get_db
from app.main import app
from app.models.user import User
from app.schemas.mfa import PasskeyRegistrationVerifyRequest
from app.services.mfa_service import (
    EmailVerificationService,
    RecoveryCodesService,
    TOTPService,
    WebAuthnService,
    sent_emails_sink,
)
from fastapi.testclient import TestClient

client = TestClient(app)


def test_enabled_local_profile_reads_flags_and_rejects_recovery_without_totp(monkeypatch):
    for name in (
        "FEATURE_TOTP_ENABLED",
        "FEATURE_PASSKEY_ENABLED",
        "FEATURE_RECOVERY_CODES_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("WEBAUTHN_RP_ID", "localhost")
    monkeypatch.setenv("WEBAUTHN_ORIGIN", "http://localhost:3000")
    enabled = Settings(_env_file=None)
    assert enabled.FEATURE_TOTP_ENABLED is True
    assert enabled.FEATURE_PASSKEY_ENABLED is True
    assert enabled.FEATURE_RECOVERY_CODES_ENABLED is True
    assert enabled.WEBAUTHN_RP_ID == "localhost"
    assert enabled.WEBAUTHN_ORIGIN == "http://localhost:3000"

    monkeypatch.setenv("FEATURE_TOTP_ENABLED", "false")
    with pytest.raises(ValueError, match="FEATURE_RECOVERY_CODES_ENABLED"):
        Settings(_env_file=None)


@pytest.mark.asyncio
async def test_passkey_registration_route_uses_exact_configured_origin(monkeypatch):
    verify = AsyncMock()
    monkeypatch.setattr(WebAuthnService, "verify_registration", verify)
    settings = Settings.model_construct(
        WEBAUTHN_RP_ID="localhost", WEBAUTHN_ORIGIN="http://localhost:3000"
    )
    await passkey_register_verify(
        payload=PasskeyRegistrationVerifyRequest(credential={"id": "synthetic"}),
        user=User(id=uuid.uuid4()),
        db=AsyncMock(),
        settings=settings,
        session=MagicMock(id=uuid.uuid4()),
    )
    assert verify.await_args.kwargs["rp_id"] == "localhost"
    assert verify.await_args.kwargs["origin"] == "http://localhost:3000"


def test_default_features_all_disabled_in_api():
    """
    Инвариант SEC-FLAG-01..03:
    Три отложенных фактора отключены; email подтверждение обязательно.
    Эндпоинты MFA при отключенных флагах возвращают 404 c error=feature_disabled.
    """
    sent_emails_sink.clear()

    # 1. Проверка объявленных значений по умолчанию в схеме Settings (SEC-FLAG-01)
    clean_settings = Settings.model_construct()
    assert clean_settings.FEATURE_TOTP_ENABLED is False
    assert clean_settings.FEATURE_PASSKEY_ENABLED is False
    assert clean_settings.FEATURE_RECOVERY_CODES_ENABLED is False
    assert clean_settings.FEATURE_EMAIL_VERIFICATION_ENABLED is True
    assert clean_settings.REQUIRE_VERIFIED_EMAIL is False

    # 2. Изоляция default-off профиля в API независима от окружения хоста
    def _get_default_off_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_TOTP_ENABLED = False
        overridden.FEATURE_PASSKEY_ENABLED = False
        overridden.FEATURE_RECOVERY_CODES_ENABLED = False
        overridden.FEATURE_EMAIL_VERIFICATION_ENABLED = True
        overridden.REQUIRE_VERIFIED_EMAIL = False
        return overridden

    app.dependency_overrides[get_settings] = _get_default_off_settings
    fake_db = AsyncMock(spec=AsyncSession)
    fake_db.execute.side_effect = [
        MagicMock(scalar_one=MagicMock(return_value=datetime.now(timezone.utc))),
        MagicMock(scalar_one=MagicMock(return_value=1)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
    ]
    fake_db.scalar.return_value = None

    async def _get_fake_db():
        yield fake_db

    app.dependency_overrides[get_db] = _get_fake_db
    try:
        # 1. TOTP endpoints return 404
        r1 = client.post("/api/v1/mfa/totp/setup")
        assert r1.status_code == 404
        assert r1.json()["error"] == "feature_disabled"
        assert r1.json()["feature"] == "FEATURE_TOTP_ENABLED"

        r2 = client.post("/api/v1/mfa/totp/confirm", json={"code": "123456"})
        assert r2.status_code == 404
        assert r2.json()["error"] == "feature_disabled"
        assert r2.json()["feature"] == "FEATURE_TOTP_ENABLED"

        # 2. Recovery codes endpoints return 404
        r3 = client.post("/api/v1/mfa/recovery-codes/generate")
        assert r3.status_code == 404
        assert r3.json()["error"] == "feature_disabled"
        assert r3.json()["feature"] == "FEATURE_RECOVERY_CODES_ENABLED"

        r4 = client.post("/api/v1/mfa/recovery-codes/verify", json={"code": "ABCD1-EFGH2"})
        assert r4.status_code == 404
        assert r4.json()["error"] == "feature_disabled"
        assert r4.json()["feature"] == "FEATURE_RECOVERY_CODES_ENABLED"

        # 3. Passkey endpoints return 404
        r5 = client.post("/api/v1/mfa/passkey/register/options")
        assert r5.status_code == 404
        assert r5.json()["error"] == "feature_disabled"
        assert r5.json()["feature"] == "FEATURE_PASSKEY_ENABLED"

        r6 = client.post("/api/v1/mfa/passkey/auth/options", json={"username": "user@example.com"})
        assert r6.status_code == 404
        assert r6.json()["error"] == "feature_disabled"
        assert r6.json()["feature"] == "FEATURE_PASSKEY_ENABLED"

        # 4. Email request remains available and neutral for an unknown address.
        r7 = client.post("/api/v1/mfa/email/request", json={"email": "user@example.com"})
        assert r7.status_code == 200
        assert r7.json()["status"] == "ok"

        # Проверка отсутствия отправки писем при disabled
        assert len(sent_emails_sink) == 0
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_totp_service_lifecycle(pg_session):
    """Real encrypted setup, confirmation and rejection of a reused time step."""
    import pyotp

    user = User(email="test_totp@example.test", username="totpuser")
    pg_session.add(user)
    await pg_session.commit()
    secret, uri = await TOTPService.setup_totp(pg_session, user)
    parsed = pyotp.parse_uri(uri)
    assert parsed.name == user.email and parsed.secret == secret
    assert parsed.issuer == "ALXPRGS SSO"
    totp = pyotp.TOTP(secret)
    step = int(datetime.now(timezone.utc).timestamp()) // 30
    valid_codes = {totp.at((step + offset) * 30) for offset in (-1, 0, 1)}
    wrong = next(f"{n:06}" for n in range(10) if f"{n:06}" not in valid_codes)
    assert not await TOTPService.confirm_totp(pg_session, user, wrong)
    await pg_session.rollback()
    await pg_session.refresh(user)
    assert await TOTPService.confirm_totp(pg_session, user, totp.now())
    assert not await TOTPService.verify_totp(pg_session, user, totp.now())
    await pg_session.rollback()
    await pg_session.refresh(user)
    next_code = totp.at(datetime.now(timezone.utc) + timedelta(seconds=30))
    assert await TOTPService.verify_totp(pg_session, user, next_code)
    assert not await TOTPService.verify_totp(pg_session, user, next_code)
    assert not await TOTPService.verify_totp(pg_session, user, wrong)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_recovery_codes_service(pg_session):
    """PostgreSQL stores hashes and atomically consumes each recovery code once."""
    import pyotp
    from app.models.mfa import RecoveryCode
    from sqlalchemy import select

    user = User(email="nomfa@example.test", username="nomfa")
    pg_session.add(user)
    await pg_session.commit()
    with pytest.raises(AuthorizationException):
        await RecoveryCodesService.generate_codes(pg_session, user)
    await pg_session.rollback()
    await pg_session.refresh(user)
    secret, _ = await TOTPService.setup_totp(pg_session, user)
    assert await TOTPService.confirm_totp(pg_session, user, pyotp.TOTP(secret).now())
    codes = await RecoveryCodesService.generate_codes(pg_session, user)
    assert len(codes) == len(set(codes)) == 10
    assert all(len(code.replace("-", "")) == 32 for code in codes)
    stored = (await pg_session.scalars(select(RecoveryCode))).all()
    assert len(stored) == 10 and all(len(row.code_hash) == 64 for row in stored)
    assert all(row.code_hash not in codes for row in stored)
    assert await RecoveryCodesService.consume_code(pg_session, user, codes[0])
    assert not await RecoveryCodesService.consume_code(pg_session, user, codes[0])
    assert not await RecoveryCodesService.consume_code(pg_session, user, "invalid")


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_email_verification_service(pg_session):
    """Real token persistence/consumption; local testing sink is not delivery evidence."""
    sent_emails_sink.clear()
    user = User(email="user_test@example.test", username="verifyuser", email_verified=False)
    pg_session.add(user)
    await pg_session.commit()
    mail_settings = Settings(
        _env_file=None, ENVIRONMENT="testing", EMAIL_PROVIDER="smtp", SMTP_HOST=""
    )
    raw = await EmailVerificationService.send_verification(
        pg_session, user, user.email, mail_settings
    )
    assert len(sent_emails_sink) == 1
    assert sent_emails_sink[0]["to"] == user.email
    assert raw == sent_emails_sink[0]["token"]
    assert sent_emails_sink[0]["code"].isdigit() and len(sent_emails_sink[0]["code"]) == 6
    assert not await EmailVerificationService.confirm_email(pg_session, "wrong-token")
    assert await EmailVerificationService.confirm_email(pg_session, raw)
    await pg_session.refresh(user)
    assert user.email_verified and user.security_revision == 1
    assert not await EmailVerificationService.confirm_email(pg_session, raw)


@pytest.mark.asyncio
async def test_webauthn_service_options():
    """Тестирование генерации WebAuthn опций для регистрации и логина."""
    user = User(
        id=uuid.uuid4(),
        email="passkey_user@alxprgs.tech",
        username="passkeyuser",
        is_active=True,
    )
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    )

    # 1. Генерация опций регистрации
    configured = Settings.model_construct(
        WEBAUTHN_RP_ID="auth.alxprgs.tech", WEBAUTHN_RP_NAME="ALXPRGS SSO"
    )
    reg_options_json = await WebAuthnService.get_registration_options(
        mock_db, user, settings=configured
    )
    assert "challenge" in reg_options_json
    assert reg_options_json["rp"]["id"] == "auth.alxprgs.tech"

    # 2. Генерация опций аутентификации
    auth_options_json = await WebAuthnService.get_authentication_options(
        mock_db, user, settings=configured
    )
    assert "challenge" in auth_options_json
    assert auth_options_json["rpId"] == "auth.alxprgs.tech"
