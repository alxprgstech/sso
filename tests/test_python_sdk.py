import base64
import hashlib
import time
import uuid
from unittest.mock import patch

import jwt
import pytest
from alxprgs_sso import InvalidTokenError, SSOClient, TokenExpiredError, UserClaims
from alxprgs_sso.fastapi import SSOFastAPISecurity
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _int_to_base64url(val: int) -> str:
    byte_length = (val.bit_length() + 7) // 8
    val_bytes = val.to_bytes(byte_length, "big")
    return base64.urlsafe_b64encode(val_bytes).decode("ascii").rstrip("=")


def _generate_test_jwks_and_key():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    kid = "sdk-test-key-01"

    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _int_to_base64url(public_numbers.n),
                "e": _int_to_base64url(public_numbers.e),
            }
        ]
    }
    return private_key, jwks, kid


def _create_signed_jwt(
    payload: dict,
    private_key: rsa.RSAPrivateKey,
    kid: str,
    expires_in_seconds: int = 300,
) -> str:
    now = int(time.time())
    p = payload.copy()
    p["iat"] = now
    p["exp"] = now + expires_in_seconds
    p["iss"] = "https://auth.alxprgs.tech"
    return jwt.encode(p, private_key, algorithm="RS256", headers={"kid": kid})


def test_sdk_errors_do_not_echo_untrusted_kid_or_claims() -> None:
    private_key, server_jwks, kid = _generate_test_jwks_and_key()
    client = SSOClient(server_url="https://auth.alxprgs.tech", client_id="test_client_id")
    tainted = "untrusted-sensitive-marker"
    unknown_kid = _create_signed_jwt(
        {"sub": "subject", "aud": "test_client_id", "token_use": "access_token"},
        private_key,
        tainted,
    )
    wrong_use = _create_signed_jwt(
        {"sub": "subject", "aud": "test_client_id", "token_use": tainted},
        private_key,
        kid,
    )
    with patch.object(client, "get_jwks", return_value=server_jwks):
        with pytest.raises(InvalidTokenError) as unknown:
            client.verify_access_token(unknown_kid)
        with pytest.raises(InvalidTokenError) as use:
            client.verify_access_token(wrong_use)
    assert tainted not in str(unknown.value)
    assert tainted not in str(use.value)


def test_sdk_pkce_authorization_url_generation():
    """
    Тестирование хелпера авторизации (SDK-04, PKCE S256).
    """
    client = SSOClient(server_url="https://auth.alxprgs.tech", client_id="test_client_id")
    redirect_uri = "https://app.alxprgs.tech/callback"

    auth_url, code_verifier, state = client.generate_authorization_url(
        redirect_uri=redirect_uri,
        scope="openid profile email",
    )

    assert "https://auth.alxprgs.tech/oauth/authorize?" in auth_url
    assert "response_type=code" in auth_url
    assert "client_id=test_client_id" in auth_url
    assert "code_challenge_method=S256" in auth_url
    assert f"state={state}" in auth_url

    # Математическая проверка RFC 7636 S256: BASE64URL(SHA256(ASCII(code_verifier)))
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert f"code_challenge={expected_challenge}" in auth_url


def test_sdk_token_validation_with_jwks():
    """
    Тестирование валидации Access Token по JWKS (SDK-02, SSO-03).
    """
    private_key, server_jwks, kid = _generate_test_jwks_and_key()
    client = SSOClient(server_url="https://auth.alxprgs.tech", client_id="test_client_id")

    with patch.object(client, "get_jwks", return_value=server_jwks):
        user_id = str(uuid.uuid4())

        # 1. Корректный Access Token
        access_token = _create_signed_jwt(
            {
                "sub": user_id,
                "preferred_username": "sdk_user",
                "email": "sdk@alxprgs.tech",
                "email_verified": True,
                "roles": ["user", "analytics"],
                "token_use": "access_token",
                "aud": "test_client_id",
            },
            private_key=private_key,
            kid=kid,
            expires_in_seconds=300,
        )

        claims = client.verify_access_token(access_token)
        assert isinstance(claims, UserClaims)
        assert claims.sub == user_id
        assert claims.preferred_username == "sdk_user"
        assert claims.email == "sdk@alxprgs.tech"
        assert claims.email_verified is True
        assert "analytics" in claims.roles

        # 2. Истёкший токен (TokenExpiredError)
        expired_token = _create_signed_jwt(
            {
                "sub": user_id,
                "preferred_username": "sdk_user",
                "token_use": "access_token",
                "aud": "test_client_id",
            },
            private_key=private_key,
            kid=kid,
            expires_in_seconds=-60,
        )
        with pytest.raises(TokenExpiredError):
            client.verify_access_token(expired_token)

        # 3. Инвариант SSO-03: ID Token отклоняется при попытке использовать его как Access Token
        id_token = _create_signed_jwt(
            {
                "sub": user_id,
                "preferred_username": "sdk_user",
                "token_use": "id_token",
                "aud": "test_client_id",
            },
            private_key=private_key,
            kid=kid,
            expires_in_seconds=300,
        )
        with pytest.raises(InvalidTokenError) as exc_info:
            client.verify_access_token(id_token)
        assert "ID Token" in str(exc_info.value)


def test_sdk_fastapi_security_dependency():
    """
    Тестирование FastAPI зависимости verify_token / require_role (SDK-03).
    """
    client = SSOClient(server_url="https://auth.alxprgs.tech", client_id="test_service")
    security = SSOFastAPISecurity(client)

    test_app = FastAPI()

    @test_app.get("/protected")
    async def protected_route(user: UserClaims = Depends(security.get_current_user)):
        return {"sub": user.sub, "username": user.preferred_username}

    @test_app.get("/admin-only")
    async def admin_route(user: UserClaims = Depends(security.require_role("admin"))):
        return {"status": "ok", "admin": user.preferred_username}

    http_client = TestClient(test_app)

    # 1. Запрос без токена -> 401
    r_no_auth = http_client.get("/protected")
    assert r_no_auth.status_code == 401

    # Мокаем валидацию токенов
    user_claims = UserClaims(
        sub="user-123",
        preferred_username="developer",
        email="dev@alxprgs.tech",
        email_verified=True,
        roles=["user"],
    )
    admin_claims = UserClaims(
        sub="admin-456",
        preferred_username="sysadmin",
        email="admin@alxprgs.tech",
        email_verified=True,
        roles=["admin", "user"],
    )

    with patch.object(client, "verify_access_token") as mock_verify:
        mock_verify.return_value = user_claims

        # 2. Обычный пользователь на защищенном эндпоинте -> 200
        r_user = http_client.get("/protected", headers={"Authorization": "Bearer mock_valid_token"})
        assert r_user.status_code == 200
        assert r_user.json()["username"] == "developer"

        # 3. Обычный пользователь на admin-only эндпоинте -> 403 Forbidden
        r_forbidden = http_client.get(
            "/admin-only", headers={"Authorization": "Bearer mock_valid_token"}
        )
        assert r_forbidden.status_code == 403

        # 4. Администратор на admin-only эндпоинте -> 200 OK
        mock_verify.return_value = admin_claims
        r_admin = http_client.get(
            "/admin-only", headers={"Authorization": "Bearer mock_admin_token"}
        )
        assert r_admin.status_code == 200
        assert r_admin.json()["admin"] == "sysadmin"


def test_sdk_web_flow_and_id_token_verification():
    """
    Тестирование веб-потока SDK (SDK-03/06):
    start_authorization, verify_id_token (nonce match/mismatch), handle_web_callback, create_logout_url.
    """

    client = SSOClient(
        server_url="https://auth.alxprgs.tech",
        client_id="test_web_client",
        expected_issuer="https://auth.alxprgs.tech",
        expected_audience="test_web_client",
    )
    redirect_uri = "https://app.alxprgs.tech/callback"

    # 1. start_authorization
    auth_url, verifier, state, nonce = client.start_authorization(redirect_uri)
    assert "client_id=test_web_client" in auth_url
    assert f"state={state}" in auth_url
    assert f"nonce={nonce}" in auth_url
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url

    # 2. create_logout_url
    logout_url = client.create_logout_url(
        "synthetic_id_token", post_logout_redirect_uri="https://app.alxprgs.tech/"
    )
    assert logout_url.startswith("https://auth.alxprgs.tech/oauth/logout")
    assert "post_logout_redirect_uri=https%3A%2F%2Fapp.alxprgs.tech%2F" in logout_url

    # 3. verify_id_token
    private_key, server_jwks, kid = _generate_test_jwks_and_key()
    with patch.object(client, "get_jwks", return_value=server_jwks):
        valid_id_token = _create_signed_jwt(
            {
                "sub": "user-uuid-1",
                "aud": "test_web_client",
                "iss": "https://auth.alxprgs.tech",
                "nonce": nonce,
                "token_use": "id_token",
            },
            private_key=private_key,
            kid=kid,
            expires_in_seconds=300,
        )

        # Успешная валидация с правильным nonce
        id_payload = client.verify_id_token(valid_id_token, expected_nonce=nonce)
        assert id_payload["sub"] == "user-uuid-1"
        assert id_payload["nonce"] == nonce

        # Неверный nonce -> отказ InvalidTokenError
        with pytest.raises(InvalidTokenError) as exc_nonce:
            client.verify_id_token(valid_id_token, expected_nonce="wrong-nonce-value")
        assert "nonce" in str(exc_nonce.value)

        # Неверный token_use -> отказ
        wrong_token_use = _create_signed_jwt(
            {
                "sub": "user-uuid-1",
                "aud": "test_web_client",
                "iss": "https://auth.alxprgs.tech",
                "nonce": nonce,
                "token_use": "access_token",
            },
            private_key=private_key,
            kid=kid,
        )
        with pytest.raises(InvalidTokenError) as exc_tu:
            client.verify_id_token(wrong_token_use, expected_nonce=nonce)
        assert "id_token" in str(exc_tu.value).lower()


@pytest.mark.asyncio
async def test_sdk_handle_web_callback_csrf_and_success():
    """
    Тестирование handle_web_callback: защита от CSRF (state mismatch) и успешное завершение.
    """
    from unittest.mock import AsyncMock

    from alxprgs_sso.models import TokenResponse

    client = SSOClient(
        server_url="https://auth.alxprgs.tech",
        client_id="test_web_client",
        expected_issuer="https://auth.alxprgs.tech",
        expected_audience="test_web_client",
    )
    redirect_uri = "https://app.alxprgs.tech/callback"

    # 1. State mismatch -> InvalidTokenError (защита от CSRF)
    with pytest.raises(InvalidTokenError) as exc_csrf:
        await client.handle_web_callback(
            code="some_code",
            state="attacker_state",
            expected_state="legitimate_state",
            code_verifier="verifier",
            redirect_uri=redirect_uri,
            expected_nonce="legitimate_nonce",
        )
    assert "state" in str(exc_csrf.value).lower()

    # 2. Успешный callback с валидацией ID токена
    private_key, server_jwks, kid = _generate_test_jwks_and_key()
    test_nonce = "safe_nonce_987"
    valid_id_token = _create_signed_jwt(
        {
            "sub": "user-uuid-2",
            "aud": "test_web_client",
            "iss": "https://auth.alxprgs.tech",
            "nonce": test_nonce,
            "token_use": "id_token",
        },
        private_key=private_key,
        kid=kid,
        expires_in_seconds=300,
    )
    valid_access_token = _create_signed_jwt(
        {
            "sub": "user-uuid-2",
            "aud": "test_web_client",
            "iss": "https://auth.alxprgs.tech",
            "preferred_username": "web_user",
            "email": "web@alxprgs.tech",
            "email_verified": True,
            "roles": ["user"],
            "token_use": "access_token",
        },
        private_key=private_key,
        kid=kid,
        expires_in_seconds=300,
    )

    mock_token_resp = TokenResponse(
        access_token=valid_access_token,
        id_token=valid_id_token,
        expires_in=300,
        token_type="Bearer",
    )

    with patch.object(client, "get_jwks", return_value=server_jwks):
        with patch.object(
            client, "exchange_code_for_tokens", new_callable=AsyncMock
        ) as mock_exchange:
            mock_exchange.return_value = mock_token_resp

            session_info = await client.handle_web_callback(
                code="auth_code_123",
                state="legit_state",
                expected_state="legit_state",
                code_verifier="verifier_123",
                redirect_uri=redirect_uri,
                expected_nonce=test_nonce,
            )

            assert session_info.user.sub == "user-uuid-2"
            assert session_info.user.preferred_username == "web_user"
            assert session_info.user.email == "web@alxprgs.tech"
            assert session_info.id_token_claims is not None
            assert session_info.id_token_claims["nonce"] == test_nonce


@pytest.mark.asyncio
async def test_callback_rejects_missing_nonce_or_id_token_before_session():
    from unittest.mock import AsyncMock

    from alxprgs_sso.models import TokenResponse

    client = SSOClient(
        "http://localhost:8000", "test_web_client", expected_issuer="https://auth.alxprgs.tech"
    )
    with patch.object(client, "exchange_code_for_tokens", new_callable=AsyncMock) as exchange:
        with pytest.raises(InvalidTokenError, match="nonce"):
            await client.handle_web_callback(
                "code", "state", "state", "verifier", "http://localhost:8001/callback"
            )
        exchange.assert_not_awaited()
        exchange.return_value = TokenResponse(
            access_token="invalid", expires_in=300, token_type="Bearer"
        )
        with pytest.raises(InvalidTokenError, match="ID Token"):
            await client.handle_web_callback(
                "code", "state", "state", "verifier", "http://localhost:8001/callback", "nonce"
            )


def test_http_transport_does_not_disable_id_token_issuer_check():
    private_key, jwks, kid = _generate_test_jwks_and_key()
    token = _create_signed_jwt(
        {"sub": "subject", "aud": "test_web_client", "nonce": "nonce", "token_use": "id_token"},
        private_key,
        kid,
    )
    client = SSOClient("http://localhost:8000", "test_web_client")
    with patch.object(client, "get_jwks", return_value=jwks):
        with pytest.raises(InvalidTokenError):
            client.verify_id_token(token, expected_nonce="nonce")
