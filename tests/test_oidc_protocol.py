import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.abspath("backend"))

from app.core.exceptions import OAuthErrorException
from app.core.security import create_jwt, verify_pkce
from app.main import app
from app.models.oidc import OIDCClient, OIDCRedirectUri
from app.services.oidc_service import OIDCService
from fastapi.testclient import TestClient

client = TestClient(app)


def test_pkce_validation():
    # RFC 7636 Appendix B test vector
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert verify_pkce(verifier, challenge, "S256") is True
    assert verify_pkce("invalid_verifier_12345678901234567890", challenge, "S256") is False


def test_redirect_uri_strict_validation():
    dummy_client = OIDCClient(
        client_id="test-client-1",
        client_name="Test App",
        client_type="confidential",
    )
    dummy_client.redirect_uris = [
        OIDCRedirectUri(client_id=dummy_client.id, uri="https://app.alxprgs.tech/callback"),
        OIDCRedirectUri(client_id=dummy_client.id, uri="http://localhost:3000/callback"),
    ]

    # Exact match passes
    OIDCService.validate_redirect_uri(dummy_client, "https://app.alxprgs.tech/callback")
    OIDCService.validate_redirect_uri(dummy_client, "http://localhost:3000/callback")

    # Mismatch, subdomain traversal, or wildcards fail
    with pytest.raises(OAuthErrorException) as exc_info:
        OIDCService.validate_redirect_uri(dummy_client, "https://evil.com/callback")
    assert exc_info.value.status_code == 400

    with pytest.raises(OAuthErrorException):
        OIDCService.validate_redirect_uri(dummy_client, "https://app.alxprgs.tech/callback/extra")

    with pytest.raises(OAuthErrorException):
        OIDCService.validate_redirect_uri(dummy_client, "http://app.alxprgs.tech/callback")


def test_id_token_rejected_as_access_token():
    """Инвариант SSO-03: Не принимать ID token вместо access token на эндпоинтах API."""
    id_token = create_jwt(
        {
            "sub": str(uuid.uuid4()),
            "token_use": "id_token",
            "aud": "test-client",
        },
        expires_in_seconds=300,
    )
    res = client.get("/oauth/userinfo", headers={"Authorization": f"Bearer {id_token}"})
    assert res.status_code == 401
    assert res.json()["error"] == "invalid_token"
    assert "ID Token" in res.json()["error_description"]


def test_oauth_authorize_endpoint_redirects_unauthenticated():
    """Обращение к /oauth/authorize с неизвестным клиентом возвращает 401 invalid_client."""
    from unittest.mock import AsyncMock, MagicMock

    from app.database import get_db

    async def mock_get_db():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db
    try:
        params = {
            "client_id": "unknown-client",
            "redirect_uri": "https://client.alxprgs.tech/callback",
            "response_type": "code",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        }
        res = client.get("/oauth/authorize", params=params, follow_redirects=False)
        assert res.status_code == 401
        assert res.json()["error"] == "invalid_client"
    finally:
        app.dependency_overrides.pop(get_db, None)


if __name__ == "__main__":
    test_pkce_validation()
    test_redirect_uri_strict_validation()
    test_id_token_rejected_as_access_token()
    test_oauth_authorize_endpoint_redirects_unauthenticated()
    print("ALL OIDC PROTOCOL TESTS PASSED!")
