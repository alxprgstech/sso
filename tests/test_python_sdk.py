import base64
import hashlib
import time
import uuid
from unittest.mock import patch

import jwt
import pytest

try:
    from alxprgs_sso import (
        InvalidTokenError,
        SSOClient,
        TokenExpiredError,
        UserClaims,
    )
    from alxprgs_sso.fastapi import SSOFastAPISecurity
except ImportError:
    pytest.skip(
        "Python SDK 'alxprgs_sso' is not installed in the current environment; "
        "SDK tests are executed in the isolated wheel environment (sdk-build-and-test).",
        allow_module_level=True,
    )
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
