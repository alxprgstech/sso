import base64
import json
import time
from unittest.mock import patch

import jwt
import pytest
from alxprgs_sso import InvalidTokenError, SSOClient
from alxprgs_sso.fastapi import SSOFastAPISecurity
from app.config import get_settings
from app.core.exceptions import OAuthErrorException
from app.core.security import (
    decode_jwt,
    get_active_key_id,
    get_jwks,
    get_rsa_private_key,
    verify_pkce,
)
from fastapi import HTTPException


def payload(use="access_token"):
    now = int(time.time())
    return {
        "iss": get_settings().OIDC_ISSUER,
        "aud": "profile_client",
        "sub": "opaque-subject",
        "iat": now,
        "exp": now + 300,
        "token_use": use,
        "scope": "openid profile",
        "auth_time": now,
        "nonce": "expected_nonce",
    }


def sign(value):
    return jwt.encode(
        value, get_rsa_private_key(), algorithm="RS256", headers={"kid": get_active_key_id()}
    )


@pytest.mark.parametrize("claim", ["iss", "sub", "aud", "iat", "exp", "token_use", "scope"])
def test_missing_access_claims_rejected_by_server_and_independent_sdk(claim):
    value = payload()
    value.pop(claim)
    token = sign(value)
    client = SSOClient(server_url=get_settings().OIDC_ISSUER, client_id="profile_client")
    with pytest.raises(OAuthErrorException):
        decode_jwt(token, audience="profile_client", expected_use="access_token")
    with (
        patch.object(client, "get_jwks", return_value=get_jwks()),
        pytest.raises(InvalidTokenError),
    ):
        client.verify_access_token(token)


@pytest.mark.parametrize(
    "claim,value",
    [
        ("exp", "9999999999"),
        ("iat", True),
        ("sub", []),
        ("aud", {"bad": "type"}),
        ("scope", []),
        ("roles", "admin"),
        ("email_verified", "true"),
        ("nonce", {}),
        ("auth_time", 9999999999),
    ],
)
def test_wrong_claim_types_rejected_with_real_signature(claim, value):
    claims = payload()
    claims[claim] = value
    token = sign(claims)
    client = SSOClient(server_url=get_settings().OIDC_ISSUER, client_id="profile_client")
    with pytest.raises(OAuthErrorException):
        decode_jwt(token, audience="profile_client", expected_use="access_token")
    with (
        patch.object(client, "get_jwks", return_value=get_jwks()),
        pytest.raises(InvalidTokenError),
    ):
        client.verify_access_token(token)


def test_id_azp_nonce_age_and_access_scope_guard():
    client = SSOClient(server_url=get_settings().OIDC_ISSUER, client_id="profile_client")
    with patch.object(client, "get_jwks", return_value=get_jwks()):
        claims = payload("id_token")
        claims["aud"] = ["profile_client", "other"]
        for azp in (None, "other"):
            invalid = {**claims, "azp": azp}
            with pytest.raises(InvalidTokenError):
                client.verify_id_token(sign(invalid), expected_nonce="expected_nonce")
        claims["azp"] = "profile_client"
        assert (
            client.verify_id_token(sign(claims), expected_nonce="expected_nonce")["azp"]
            == "profile_client"
        )
        with pytest.raises(InvalidTokenError):
            client.verify_id_token(sign(claims), expected_nonce="wrong_nonce")
        stale = {**claims, "auth_time": int(time.time()) - 1000}
        with pytest.raises(InvalidTokenError):
            client.verify_id_token(sign(stale), expected_nonce="expected_nonce", max_age=60)
        access = client.verify_access_token(sign(payload()))
        assert access.scopes == {"openid", "profile"}
        security = SSOFastAPISecurity(client)
        assert security.require_scope("profile")(access) is access
        with pytest.raises(HTTPException) as failure:
            security.require_scope("email")(access)
        assert failure.value.status_code == 403


@pytest.mark.parametrize("kid", [[], {}, None, "k" * 129])
def test_malformed_header_never_fetches_sdk_jwks(kid):
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "kid": kid}).encode())
        .decode()
        .rstrip("=")
    )
    token = header + ".e30.e30"
    client = SSOClient(server_url=get_settings().OIDC_ISSUER, client_id="profile_client")
    with patch.object(client, "get_jwks") as fetch, pytest.raises(InvalidTokenError):
        client.verify_access_token(token)
    fetch.assert_not_called()


@pytest.mark.parametrize(
    "verifier", ["a", "a" * 42, "a" * 129, "é" * 43, "a" * 42 + "=", "a" * 42 + " "]
)
def test_pkce_rejects_invalid_syntax_even_when_digest_matches(verifier):
    import hashlib

    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert not verify_pkce(verifier, challenge)


@pytest.mark.parametrize("length", [43, 128])
def test_pkce_accepts_boundary_s256(length):
    import hashlib

    verifier = "~" * length
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert verify_pkce(verifier, challenge)
    assert not verify_pkce(verifier, challenge + "=")
    assert not verify_pkce(verifier, challenge, "plain")
