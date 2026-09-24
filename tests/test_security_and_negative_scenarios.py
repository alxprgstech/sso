import sys
import os
import uuid
import hmac
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath("backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.config import get_settings
from app.core.security import hash_password, create_jwt, hash_token, generate_random_token
from app.core.exceptions import OAuthErrorException, AuthenticationException
from app.models.user import User
from app.models.session import Session
from app.models.oidc import OIDCClient, AuthorizationCode, RefreshToken
from app.services.oidc_service import OIDCService
from app.services.auth_service import AuthService
from app.api.deps import verify_csrf, generate_csrf_token

client = TestClient(app)
settings = get_settings()


@pytest.mark.asyncio
async def test_oidc_invalid_pkce_verifier_rejected():
    """Неверный PKCE code_verifier приводит к ошибке invalid_grant."""
    db = AsyncMock()
    client_uuid = uuid.uuid4()
    mock_client = OIDCClient(client_id="test_client", client_type="public", is_active=True)
    mock_client.id = client_uuid

    code_record = AuthorizationCode(
        code_hash=hash_token("test_auth_code_1"),
        client_id=client_uuid,
        user_id=uuid.uuid4(),
        redirect_uri="https://client.alxprgs.tech/callback",
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        code_challenge_method="S256",
        scope="openid profile email",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        is_used=False,
    )

    exec_mock = AsyncMock()
    mock_res_client = MagicMock()
    mock_res_client.scalar_one_or_none.return_value = mock_client

    mock_res_code = MagicMock()
    mock_res_code.scalar_one_or_none.return_value = code_record

    exec_mock.side_effect = [mock_res_client, mock_res_code]
    db.execute = exec_mock

    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.exchange_code(
            db=db,
            client_id="test_client",
            client_secret=None,
            code="test_auth_code_1",
            redirect_uri="https://client.alxprgs.tech/callback",
            code_verifier="wrong_verifier_1234567890123456789012345",
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "invalid_grant"
    assert "code_verifier" in exc_info.value.detail["error_description"]


@pytest.mark.asyncio
async def test_oidc_expired_auth_code_rejected():
    """Просроченный authorization code отклоняется с invalid_grant."""
    db = AsyncMock()
    client_uuid = uuid.uuid4()
    mock_client = OIDCClient(client_id="test_client", client_type="public", is_active=True)
    mock_client.id = client_uuid

    code_record = AuthorizationCode(
        code_hash=hash_token("expired_code"),
        client_id=client_uuid,
        user_id=uuid.uuid4(),
        redirect_uri="https://client.alxprgs.tech/callback",
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        code_challenge_method="S256",
        scope="openid profile email",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),  # Expired
        is_used=False,
    )

    exec_mock = AsyncMock()
    mock_res_client = MagicMock()
    mock_res_client.scalar_one_or_none.return_value = mock_client

    mock_res_code = MagicMock()
    mock_res_code.scalar_one_or_none.return_value = code_record

    exec_mock.side_effect = [mock_res_client, mock_res_code]
    db.execute = exec_mock

    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.exchange_code(
            db=db,
            client_id="test_client",
            client_secret=None,
            code="expired_code",
            redirect_uri="https://client.alxprgs.tech/callback",
            code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "invalid_grant"
    assert "истёк" in exc_info.value.detail["error_description"]


@pytest.mark.asyncio
async def test_oidc_reused_auth_code_rejected():
    """Повторное использование authorization code (Replay Attack) отклоняется."""
    db = AsyncMock()
    client_uuid = uuid.uuid4()
    mock_client = OIDCClient(client_id="test_client", client_type="public", is_active=True)
    mock_client.id = client_uuid

    code_record = AuthorizationCode(
        code_hash=hash_token("reused_code"),
        client_id=client_uuid,
        user_id=uuid.uuid4(),
        redirect_uri="https://client.alxprgs.tech/callback",
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        code_challenge_method="S256",
        scope="openid profile email",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        is_used=True,  # Already used!
    )

    exec_mock = AsyncMock()
    mock_res_client = MagicMock()
    mock_res_client.scalar_one_or_none.return_value = mock_client

    mock_res_code = MagicMock()
    mock_res_code.scalar_one_or_none.return_value = code_record

    exec_mock.side_effect = [mock_res_client, mock_res_code]
    db.execute = exec_mock

    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.exchange_code(
            db=db,
            client_id="test_client",
            client_secret=None,
            code="reused_code",
            redirect_uri="https://client.alxprgs.tech/callback",
            code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "invalid_grant"
    assert "уже был использован" in exc_info.value.detail["error_description"]


@pytest.mark.asyncio
async def test_oidc_refresh_token_replay_revokes_family():
    """Повторное использование refresh token аннулирует всю семью токенов (SSO-05)."""
    db = AsyncMock()
    client_uuid = uuid.uuid4()
    mock_client = OIDCClient(client_id="test_client", client_type="public", is_active=True)
    mock_client.id = client_uuid

    family_id = uuid.uuid4()
    old_rt = RefreshToken(
        token_hash=hash_token("compromised_refresh_token"),
        client_id=client_uuid,
        user_id=uuid.uuid4(),
        family_id=family_id,
        scope="openid profile",
        is_revoked=True,  # Already rotated and revoked!
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )

    exec_mock = AsyncMock()
    mock_res_client = MagicMock()
    mock_res_client.scalar_one_or_none.return_value = mock_client

    mock_res_rt = MagicMock()
    mock_res_rt.scalar_one_or_none.return_value = old_rt

    mock_res_update = MagicMock()

    exec_mock.side_effect = [mock_res_client, mock_res_rt, mock_res_update]
    db.execute = exec_mock

    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.rotate_refresh_token(
            db=db,
            client_id="test_client",
            client_secret=None,
            raw_refresh_token="compromised_refresh_token",
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "invalid_grant"
    assert "Всё семейство токенов отозвано" in exc_info.value.detail["error_description"]


@pytest.mark.asyncio
async def test_oidc_client_authentication_failure():
    """Конфиденциальный клиент с неверным секретом получает 401 invalid_client."""
    db = AsyncMock()
    hashed_secret = hash_token("correct_secret")
    confidential_client = OIDCClient(
        client_id="conf_client",
        client_type="confidential",
        client_secret_hash=hashed_secret,
        is_active=True,
    )
    confidential_client.id = uuid.uuid4()

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = confidential_client
    db.execute.return_value = mock_res

    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.get_and_validate_client(
            db=db,
            client_id="conf_client",
            client_secret="wrong_secret",
            require_secret=True,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_blocked_user_cannot_authenticate():
    """Заблокированный пользователь (is_active=False) не может войти (возвращается 401)."""
    db = AsyncMock()
    blocked_user = User(
        username="blocked_guy",
        email="blocked@alxprgs.tech",
        is_active=False,  # Blocked
    )

    mock_res_user = MagicMock()
    mock_res_user.scalar_one_or_none.return_value = blocked_user

    mock_res_pwd = MagicMock()
    mock_res_pwd.scalar_one_or_none.return_value = MagicMock(password_hash=hash_password("password123"))

    exec_mock = AsyncMock()
    exec_mock.side_effect = [mock_res_user, mock_res_pwd]
    db.execute = exec_mock

    with pytest.raises(AuthenticationException) as exc_info:
        await AuthService.authenticate_user(db, "blocked_guy", "password123")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"] == "invalid_credentials"


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
    endpoints = [
        ("POST", "/api/v1/mfa/totp/setup", None),
        ("POST", "/api/v1/mfa/passkey/register/options", None),
        ("POST", "/api/v1/mfa/recovery-codes/generate", None),
        ("POST", "/api/v1/mfa/email/request", {"email": "user@example.com"}),
    ]

    for method, path, payload in endpoints:
        res = client.post(path, json=payload or {})
        assert res.status_code == 404, f"Endpoint {path} did not return 404"
        assert res.json()["error"] == "feature_disabled", f"Endpoint {path} didn't return feature_disabled"


@pytest.mark.asyncio
async def test_atomic_code_redemption_race_condition():
    """Имитация конкурентного погашения одного и того же authorization code: ровно один завершается успешно."""
    db = AsyncMock()
    client_uuid = uuid.uuid4()
    mock_client = OIDCClient(client_id="race_client", client_type="public", is_active=True)
    mock_client.id = client_uuid

    code_state = {
        "used": False,
    }

    async def mock_execute(query, *args, **kwargs):
        query_str = str(query)
        mock_result = MagicMock()
        if "oidc_clients" in query_str:
            mock_result.scalar_one_or_none.return_value = mock_client
            return mock_result
        if "authorization_codes" in query_str:
            if code_state["used"]:
                used_record = AuthorizationCode(
                    code_hash=hash_token("race_code"),
                    client_id=client_uuid,
                    user_id=uuid.uuid4(),
                    redirect_uri="https://app.alxprgs.tech/callback",
                    code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                    code_challenge_method="S256",
                    scope="openid profile email",
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
                    is_used=True,  # Marked used!
                )
                mock_result.scalar_one_or_none.return_value = used_record
            else:
                code_state["used"] = True
                active_record = AuthorizationCode(
                    code_hash=hash_token("race_code"),
                    client_id=client_uuid,
                    user_id=uuid.uuid4(),
                    redirect_uri="https://app.alxprgs.tech/callback",
                    code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                    code_challenge_method="S256",
                    scope="openid profile email",
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
                    is_used=False,
                )
                mock_result.scalar_one_or_none.return_value = active_record
            return mock_result
        if "users" in query_str:
            user = User(username="race_user", email="race@alxprgs.tech", is_active=True)
            user.roles = []
            mock_result.scalar_one.return_value = user
            mock_result.scalar_one_or_none.return_value = user
            return mock_result
        return mock_result

    db.execute.side_effect = mock_execute

    # Attempt 1: succeeds
    res1 = await OIDCService.exchange_code(
        db=db,
        client_id="race_client",
        client_secret=None,
        code="race_code",
        redirect_uri="https://app.alxprgs.tech/callback",
        code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    )
    assert res1.access_token is not None

    # Attempt 2: strictly fails with replay detected
    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.exchange_code(
            db=db,
            client_id="race_client",
            client_secret=None,
            code="race_code",
            redirect_uri="https://app.alxprgs.tech/callback",
            code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "invalid_grant"
    assert "уже был использован" in exc_info.value.detail["error_description"]
