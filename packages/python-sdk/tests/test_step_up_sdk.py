"""SDK contract tests for transaction step-up (no backend imports)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from alxprgs_sso import (
    SSOClient,
    StepUpBindingError,
    StepUpReplayError,
)
from alxprgs_sso.models import StepUpRequest
from cryptography.hazmat.primitives.asymmetric import rsa


def _int_to_base64url(value: int) -> str:
    return (
        base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big"))
        .decode("ascii")
        .rstrip("=")
    )


def _jwks_and_key():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    return (
        {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": "step-up-sdk-key",
                    "use": "sig",
                    "alg": "RS256",
                    "n": _int_to_base64url(numbers.n),
                    "e": _int_to_base64url(numbers.e),
                }
            ]
        },
        private_key,
        "step-up-sdk-key",
    )


def _request(**overrides) -> StepUpRequest:
    values = {
        "request_token": "synthetic-request-token",
        "authorization_url": "https://auth.alxprgs.tech/step-up/synthetic-request-token",
        "client_name": "Synthetic RP",
        "action": "critical_settings_change",
        "description": "Изменить критические настройки",
        "payload_hash": hashlib.sha256(b"payload").hexdigest(),
        "assurance": "reauth_mfa",
        "assurance_label": "Многофакторная проверка",
        "plans": [
            {
                "id": "password_totp",
                "label": "Пароль и код",
                "methods": ["password", "totp"],
            }
        ],
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=2),
        "redirect_uri": "https://rp.example.test/step-up/callback",
        "state": "state-value-1234567890",
        "nonce": "nonce-value-1234567890",
        "code_verifier": "a" * 64,
    }
    values.update(overrides)
    return StepUpRequest(**values)


def _proof(request: StepUpRequest, private_key, kid: str, **overrides) -> str:
    now = int(time.time())
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": "client_synthetic",
        "iss": "https://auth.alxprgs.tech",
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "auth_time": now,
        "token_use": "external_step_up_proof",
        "jti": str(uuid.uuid4()),
        "transaction_id": str(uuid.uuid4()),
        "action": request.action,
        "payload_hash": request.payload_hash,
        "acr": request.assurance,
        "amr": ["pwd", "otp"],
        "nonce": request.nonce,
        "security_revision": 3,
    }
    payload.update(overrides)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


class FakeResponse:
    def __init__(self, status_code: int, data: dict):
        self.status_code = status_code
        self._data = data
        self.content = json.dumps(data).encode()

    def json(self):
        return self._data


class FakeAsyncClient:
    calls: list[dict] = []
    response: FakeResponse | None = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, auth=None, json=None):
        self.calls.append({"url": url, "auth": auth, "json": json})
        assert self.response is not None
        return self.response


def test_create_step_up_request_builds_pkce_and_binds_state():
    response = {
        "request_token": "server-request-token",
        "authorization_url": "https://auth.alxprgs.tech/step-up/server-request-token",
        "client_name": "Synthetic RP",
        "action": "critical_settings_change",
        "description": "Изменить критические настройки",
        "payload_hash": hashlib.sha256(b"payload").hexdigest(),
        "assurance": "reauth_mfa",
        "assurance_label": "Многофакторная проверка",
        "plans": [
            {"id": "password_totp", "label": "Пароль и код", "methods": ["password", "totp"]}
        ],
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
    }
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse(201, response)
    client = SSOClient(
        server_url="https://auth.alxprgs.tech",
        client_id="client_synthetic",
        client_secret="secret",  # pragma: allowlist secret
        expected_issuer="https://auth.alxprgs.tech",
    )
    with patch("alxprgs_sso.client.httpx.AsyncClient", FakeAsyncClient):
        request = asyncio.run(
            client.create_step_up_request(
                action="critical_settings_change",
                payload_hash=hashlib.sha256(b"payload").hexdigest(),
                subject=str(uuid.uuid4()),
                assurance="reauth_mfa",
                redirect_uri="https://rp.example.test/step-up/callback",
                description="Изменить критические настройки",
                ttl_seconds=120,
            )
        )
    assert request.request_token == "server-request-token"
    assert request.state
    assert request.nonce
    assert 43 <= len(request.code_verifier) <= 128
    call = FakeAsyncClient.calls[0]
    assert call["auth"] == ("client_synthetic", "secret")
    assert call["json"]["code_challenge_method"] == "S256"
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(request.code_verifier.encode("ascii")).digest())
        .decode()
        .rstrip("=")
    )
    assert call["json"]["code_challenge"] == expected
    assert client.build_step_up_url(request) == request.authorization_url


def test_consume_step_up_proof_verifies_transaction_and_one_time_error():
    jwks, private_key, kid = _jwks_and_key()
    request = _request()
    proof = _proof(request, private_key, kid)
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = FakeResponse(200, {"proof": proof, "claims": {}})
    client = SSOClient(
        server_url="https://auth.alxprgs.tech",
        client_id="client_synthetic",
        client_secret="secret",  # pragma: allowlist secret
        expected_issuer="https://auth.alxprgs.tech",
    )

    async def fake_jwks(*args, **kwargs):
        return jwks

    with (
        patch("alxprgs_sso.client.httpx.AsyncClient", FakeAsyncClient),
        patch.object(client, "get_jwks_async", fake_jwks),
    ):
        result = asyncio.run(
            client.consume_step_up_proof(
                code="one-use-code",
                request=request,
                state=request.state,
                expected_subject=_payload_subject(proof),
            )
        )
    assert result.claims.action == request.action
    assert result.claims.acr == request.assurance
    assert result.claims.amr == ["pwd", "otp"]

    FakeAsyncClient.response = FakeResponse(409, {"error": "proof_replayed", "detail": "used"})
    with (
        patch("alxprgs_sso.client.httpx.AsyncClient", FakeAsyncClient),
        patch.object(client, "get_jwks_async", fake_jwks),
    ):
        with pytest.raises(StepUpReplayError):
            asyncio.run(
                client.consume_step_up_proof(
                    code="one-use-code",
                    request=request,
                    state=request.state,
                    expected_subject=_payload_subject(proof),
                )
            )


def test_consume_rejects_wrong_state_payload_and_token_type():
    jwks, private_key, kid = _jwks_and_key()
    request = _request()
    proof = _proof(request, private_key, kid)
    client = SSOClient(
        server_url="https://auth.alxprgs.tech",
        client_id="client_synthetic",
        client_secret="secret",  # pragma: allowlist secret
        expected_issuer="https://auth.alxprgs.tech",
    )
    with pytest.raises(StepUpBindingError):
        asyncio.run(
            client.consume_step_up_proof(
                code="code",
                request=request,
                state="wrong-state-value",
                expected_subject=_payload_subject(proof),
            )
        )
    wrong_payload = "0" * 64

    async def fake_jwks(*args, **kwargs):
        return jwks

    with (
        patch("alxprgs_sso.client.httpx.AsyncClient", FakeAsyncClient),
        patch.object(client, "get_jwks_async", fake_jwks),
    ):
        FakeAsyncClient.response = FakeResponse(200, {"proof": proof, "claims": {}})
        with pytest.raises(StepUpBindingError):
            asyncio.run(
                client.consume_step_up_proof(
                    code="code",
                    request=request,
                    state=request.state,
                    expected_subject=_payload_subject(proof),
                    expected_payload_hash=wrong_payload,
                )
            )
    bad_type = _proof(request, private_key, kid, token_use="id_token")
    with (
        patch("alxprgs_sso.client.httpx.AsyncClient", FakeAsyncClient),
        patch.object(client, "get_jwks_async", fake_jwks),
    ):
        FakeAsyncClient.response = FakeResponse(200, {"proof": bad_type, "claims": {}})
        with pytest.raises(StepUpBindingError):
            asyncio.run(
                client.consume_step_up_proof(
                    code="code",
                    request=request,
                    state=request.state,
                    expected_subject=_payload_subject(bad_type),
                )
            )


def _payload_subject(token: str) -> str:
    return jwt.decode(token, options={"verify_signature": False})["sub"]
