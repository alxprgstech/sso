"""Real RSA verification through a fixture HTTP transport, not a Google live check."""

import json
import time

import httpx
import jwt
import pytest
from app.config import Settings
from app.services.registration_service import verify_gmail_bearer
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [None, "iss", "aud", "azp", "exp", "iat", "kid", "signature", "missing_exp"]
)
async def test_google_style_real_rsa_profiles(monkeypatch, change):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="google-fixture", use="sig", alg="RS256")
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "https://alxprgs.tech",
        "azp": "gmail@system.gserviceaccount.com",
        "iat": int(time.time()) - 60,
        "exp": int(time.time()) + 300,
    }
    headers = {"kid": "google-fixture"}
    if change in {"iss", "aud", "azp"}:
        claims[change] = "untrusted-sensitive-marker"
    elif change == "exp":
        claims["exp"] = int(time.time()) - 1
    elif change == "iat":
        claims["iat"] = True
    elif change == "missing_exp":
        del claims["exp"]
    signing_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if change == "signature"
        else key
    )
    encoded = jwt.encode(claims, signing_key, algorithm="RS256", headers=headers)
    if change == "kid":
        from jwt.utils import base64url_encode

        headers["kid"] = {"invalid": "untrusted-sensitive-marker"}
        headers["alg"] = "RS256"
        encoded = (
            base64url_encode(json.dumps(headers).encode()).decode() + "." + encoded.split(".", 1)[1]
        )
    calls = []

    def transport(request):
        calls.append(request)
        assert str(request.url) == "https://www.googleapis.com/oauth2/v3/certs"
        return httpx.Response(200, json={"keys": [jwk]})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs),
    )
    if change is None:
        await verify_gmail_bearer("Bearer " + encoded, Settings(_env_file=None))
    else:
        with pytest.raises(HTTPException) as exc:
            await verify_gmail_bearer("Bearer " + encoded, Settings(_env_file=None))
        assert exc.value.status_code == 401 and exc.value.detail == {"error": "gmail_auth_invalid"}
        assert "untrusted-sensitive-marker" not in str(exc.value)
    assert len(calls) == (0 if change == "kid" else 1)
