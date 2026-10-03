import copy
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.abspath("backend"))

from app.api.mfa import passkey_register_verify
from app.config import Settings, get_settings
from app.core.exceptions import (
    AuthorizationException,
)
from app.core.security import encrypt_totp_secret, hash_token
from app.database import get_db
from app.main import app
from app.models.mfa import (
    EmailVerificationToken,
    TOTPCredential,
)
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
    fake_db = AsyncMock()
    fake_db.execute.side_effect = [MagicMock(scalar_one=MagicMock(return_value=datetime.now(timezone.utc))), MagicMock(scalar_one=MagicMock(return_value=1)), MagicMock(scalar_one_or_none=MagicMock(return_value=None))]
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


@pytest.mark.asyncio
async def test_totp_service_lifecycle():
    """Тестирование полного цикла TOTP при включенной функции."""
    user = User(
        id=uuid.uuid4(),
        email="test_totp@alxprgs.tech",
        username="totpuser",
        is_active=True,
    )
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    # 1. Генерация секрета
    raw_secret, uri = await TOTPService.setup_totp(mock_db, user)
    assert len(raw_secret) > 10
    assert "otpauth://" in uri
    assert "totpuser" in uri or "test_totp" in uri
    import pyotp

    parsed_totp = pyotp.parse_uri(uri)
    assert parsed_totp.name == user.email
    assert parsed_totp.secret == raw_secret
    assert parsed_totp.issuer == "ALXPRGS SSO"

    # 2. Подтверждение с верным кодом
    totp_calc = pyotp.TOTP(raw_secret)
    valid_code = totp_calc.now()

    # Мокаем запись TOTPCredential в БД
    encrypted_secret = encrypt_totp_secret(raw_secret)
    totp_record = TOTPCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        encrypted_secret=encrypted_secret,
        is_confirmed=False,
    )

    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=totp_record))

    # Неверный код должен отклоняться
    wrong = await TOTPService.confirm_totp(mock_db, user, "000000")
    assert wrong is False

    # Верный код подтверждает настройку
    success = await TOTPService.confirm_totp(mock_db, user, valid_code)
    assert success is True
    assert totp_record.is_confirmed is True

    # 3. Верификация TOTP при логине
    assert await TOTPService.verify_totp(mock_db, user, valid_code) is True
    assert await TOTPService.verify_totp(mock_db, user, "999999") is False


@pytest.mark.asyncio
async def test_recovery_codes_service():
    """
    Тестирование кодов восстановления:
    - Зависимость от включенного MFA (SEC-FLAG-05)
    - Одноразовое атомарное погашение
    - Защита от повторного использования (replay protection)
    """
    user_no_mfa = User(
        id=uuid.uuid4(),
        email="nomfa@alxprgs.tech",
        username="nomfa",
        is_active=True,
        totp_credential=None,
    )
    mock_db = AsyncMock()

    # Без активного TOTP генерация кодов запрещена (SEC-FLAG-05)
    with pytest.raises(AuthorizationException):
        await RecoveryCodesService.generate_codes(mock_db, user_no_mfa)

    # Добавляем подтвержденный TOTP
    active_totp = TOTPCredential(
        id=uuid.uuid4(),
        user_id=user_no_mfa.id,
        encrypted_secret="enc_mock",
        is_confirmed=True,
    )
    user_no_mfa.totp_credential = active_totp

    codes = await RecoveryCodesService.generate_codes(mock_db, user_no_mfa)
    assert len(codes) == 10
    test_code = codes[0]

    # Моделируем успешное погашение первого кода через atomic UPDATE returning
    code_id = uuid.uuid4()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=code_id))

    ok = await RecoveryCodesService.consume_code(mock_db, user_no_mfa, test_code)
    assert ok is True

    # Повторное использование (БД возвращает None, так как is_used уже True)
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    ok_replay = await RecoveryCodesService.consume_code(mock_db, user_no_mfa, test_code)
    assert ok_replay is False


@pytest.mark.asyncio
async def test_email_verification_service():
    """Тестирование выпуска и подтверждения токена email."""
    sent_emails_sink.clear()
    user = User(
        id=uuid.uuid4(),
        email="user_test@alxprgs.tech",
        username="verifyuser",
        is_active=True,
        email_verified=False,
    )
    mock_db = AsyncMock()

    # 1. Запрос подтверждения
    mail_settings = Settings(
        _env_file=None,
        ENVIRONMENT="testing",
        FEATURE_EMAIL_VERIFICATION_ENABLED=True,
        EMAIL_PROVIDER="smtp",
        SMTP_HOST="",
    )
    raw_token = await EmailVerificationService.send_verification(
        mock_db, user, user.email, mail_settings
    )
    assert len(sent_emails_sink) == 1
    assert sent_emails_sink[0]["to"] == user.email
    assert raw_token == sent_emails_sink[0]["token"]
    assert sent_emails_sink[0]["code"].isdigit()
    assert len(sent_emails_sink[0]["code"]) == 6

    # 2. Мокаем выборку токена из БД
    token_record = EmailVerificationToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_token(raw_token),
        email=user.email,
        is_used=False,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    mock_db.scalar.side_effect = [token_record, user]

    # 3. Подтверждение токена
    verified = await EmailVerificationService.confirm_email(mock_db, raw_token)
    assert verified is True
    assert token_record.is_used is True
    assert user.email_verified is True


@pytest.mark.asyncio
async def test_webauthn_service_options():
    """Тестирование генерации WebAuthn опций для регистрации и логина."""
    user = User(
        id=uuid.uuid4(),
        email="passkey_user@alxprgs.tech",
        username="passkeyuser",
        is_active=True,
    )
    mock_db = AsyncMock()
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
