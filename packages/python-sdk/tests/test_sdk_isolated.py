import base64
import hashlib
import time
import uuid
from unittest.mock import patch

import jwt
import pytest
from alxprgs_sso import (
    InvalidTokenError,
    SSOClient,
    TokenExpiredError,
    UserClaims,
)
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
    kid = "sdk-test-isolated-key-01"

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
    if p.get("token_use") == "access_token":
        p.setdefault("scope", "openid profile email")
    return jwt.encode(p, private_key, algorithm="RS256", headers={"kid": kid})


def test_sdk_pkce_authorization_url_generation():
    """
    QA-12, SDK-04: Тестирование генерации Authorization URL и параметров PKCE S256.
    Полная изоляция от сервера (AGENTS.md Section 3).
    """
    client = SSOClient(server_url="https://auth.alxprgs.tech", client_id="isolated_client_id")
    redirect_uri = "https://client.alxprgs.tech/callback"

    auth_url, code_verifier, state = client.generate_authorization_url(
        redirect_uri=redirect_uri,
        scope="openid profile email",
    )

    assert "https://auth.alxprgs.tech/oauth/authorize?" in auth_url
    assert "response_type=code" in auth_url
    assert "client_id=isolated_client_id" in auth_url
    assert "code_challenge_method=S256" in auth_url
    assert f"state={state}" in auth_url

    # Математическая валидация RFC 7636 S256: BASE64URL(SHA256(ASCII(code_verifier)))
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert f"code_challenge={expected_challenge}" in auth_url


def test_sdk_token_validation_with_jwks_isolated():
    """
    QA-12, SDK-02, SSO-03: Валидация Access Token по JWKS в чистой среде SDK.
    - Проверка подписи RSA256 и структуры claims (UserClaims).
    - Проверка срока действия (TokenExpiredError).
    - Инвариант SSO-03: отклонение ID Token при попытке использования в качестве Access Token.
    """
    private_key, jwks, kid = _generate_test_jwks_and_key()
    client = SSOClient(server_url="https://auth.alxprgs.tech", client_id="isolated_client_id")

    # Имитируем получение JWKS от удаленного сервера
    with patch.object(client, "get_jwks", return_value=jwks):
        user_id = str(uuid.uuid4())

        # 1. Валидный Access Token
        access_token = _create_signed_jwt(
            {
                "sub": user_id,
                "preferred_username": "pure_sdk_user",
                "email": "sdk_pure@alxprgs.tech",
                "email_verified": True,
                "roles": ["user", "researcher"],
                "token_use": "access_token",
                "aud": "isolated_client_id",
            },
            private_key=private_key,
            kid=kid,
            expires_in_seconds=300,
        )

        claims = client.verify_access_token(access_token)
        assert isinstance(claims, UserClaims)
        assert claims.sub == user_id
        assert claims.preferred_username == "pure_sdk_user"
        assert claims.email == "sdk_pure@alxprgs.tech"
        assert claims.email_verified is True
        assert "researcher" in claims.roles

        # 2. Истекший токен -> TokenExpiredError
        expired_token = _create_signed_jwt(
            {
                "sub": user_id,
                "preferred_username": "pure_sdk_user",
                "token_use": "access_token",
                "aud": "isolated_client_id",
            },
            private_key=private_key,
            kid=kid,
            expires_in_seconds=-60,
        )
        with pytest.raises(TokenExpiredError):
            client.verify_access_token(expired_token)

        # 3. Инвариант SSO-03: токен с token_use == "id_token" строго отклоняется
        id_token = _create_signed_jwt(
            {
                "sub": user_id,
                "preferred_username": "pure_sdk_user",
                "token_use": "id_token",
                "aud": "isolated_client_id",
            },
            private_key=private_key,
            kid=kid,
            expires_in_seconds=300,
        )
        with pytest.raises(InvalidTokenError) as exc_info:
            client.verify_access_token(id_token)
        assert "ID Token" in str(exc_info.value)


def test_sdk_fastapi_security_dependency_isolated():
    """
    QA-12, SDK-03: Тестирование интеграции с FastAPI (get_current_user, require_role).
    """
    client = SSOClient(server_url="https://auth.alxprgs.tech", client_id="service_api")
    security = SSOFastAPISecurity(client)

    test_app = FastAPI()

    @test_app.get("/api/profile")
    async def profile_route(user: UserClaims = Depends(security.get_current_user)):
        return {"sub": user.sub, "username": user.preferred_username}

    @test_app.get("/api/admin-section")
    async def admin_route(user: UserClaims = Depends(security.require_role("admin"))):
        return {"status": "ok", "admin": user.preferred_username}

    http_client = TestClient(test_app)

    # 1. Запрос без токена -> 401
    r_no_auth = http_client.get("/api/profile")
    assert r_no_auth.status_code == 401

    # Задаем claims
    user_claims = UserClaims(
        sub="user-777",
        preferred_username="ivan_dev",
        email="ivan@alxprgs.tech",
        email_verified=True,
        roles=["user"],
    )
    admin_claims = UserClaims(
        sub="admin-999",
        preferred_username="maria_admin",
        email="maria@alxprgs.tech",
        email_verified=True,
        roles=["admin", "user"],
    )

    with patch.object(client, "verify_access_token") as mock_verify:
        mock_verify.return_value = user_claims

        # 2. Обычный пользователь на защищенном эндпоинте -> 200 OK
        r_user = http_client.get(
            "/api/profile", headers={"Authorization": "Bearer mock_valid_access_token"}
        )
        assert r_user.status_code == 200
        assert r_user.json()["username"] == "ivan_dev"

        # 3. Обычный пользователь на admin-only эндпоинте -> 403 Forbidden
        r_forbidden = http_client.get(
            "/api/admin-section", headers={"Authorization": "Bearer mock_valid_access_token"}
        )
        assert r_forbidden.status_code == 403

        # 4. Администратор на admin-only эндпоинте -> 200 OK
        mock_verify.return_value = admin_claims
        r_admin = http_client.get(
            "/api/admin-section", headers={"Authorization": "Bearer mock_admin_access_token"}
        )
        assert r_admin.status_code == 200
        assert r_admin.json()["admin"] == "maria_admin"
