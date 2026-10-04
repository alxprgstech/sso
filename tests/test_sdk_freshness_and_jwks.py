"""Real RSA verification; only HTTPS transport is replaced by an in-memory server."""

import json
import time
from unittest.mock import patch

import httpx
import pytest
from alxprgs_sso import InvalidTokenError, SSOClient
from alxprgs_sso.exceptions import ConfigurationError

from tests.test_python_sdk import _create_signed_jwt, _generate_test_jwks_and_key


@pytest.mark.parametrize("age,accepted", [(0, True), (5, True), (6, False), (300, False)])
def test_max_age_zero_accepts_only_bounded_fresh_signed_authentication(age, accepted):
    key, jwks, kid = _generate_test_jwks_and_key()
    now = int(time.time())
    token = _create_signed_jwt(
        {
            "sub": "synthetic",
            "aud": "rp",
            "token_use": "id_token",
            "auth_time": now - age,
            "nonce": "bound-nonce",
        },
        key,
        kid,
    )
    sdk = SSOClient("https://auth.alxprgs.tech", "rp")
    with (
        patch.object(sdk, "get_jwks", return_value=jwks),
        patch("time.time", return_value=now + 0.8),
    ):
        if accepted:
            assert sdk.verify_id_token(token, "bound-nonce", max_age=0)["auth_time"] == now - age
        else:
            with pytest.raises(InvalidTokenError):
                sdk.verify_id_token(token, "bound-nonce", max_age=0)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_jwks_response_limits_validation_and_cache_recovery(monkeypatch, asynchronous):
    _, jwks, _ = _generate_test_jwks_and_key()
    original = httpx.AsyncClient if asynchronous else httpx.Client
    payload = json.dumps(jwks).encode()
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=payload)

    monkeypatch.setattr(
        httpx,
        "AsyncClient" if asynchronous else "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)),
    )
    sdk = SSOClient(
        "https://auth.example.test", "rp", jwks_cache_ttl_seconds=0, max_stale_seconds=0
    )

    async def fetch():
        return await sdk.get_jwks_async() if asynchronous else sdk.get_jwks()

    for payload in (b"not JSON", b'{"keys": []}', b" " * 65537):
        with pytest.raises(ConfigurationError):
            await fetch()
        assert sdk._cached_jwks is None
    payload = json.dumps(jwks).encode()
    assert await fetch() == jwks
    assert len(calls) == 4
