"""Original audit attacks with complete current claims and real server/SDK crypto."""

import secrets
import time
from unittest.mock import patch

import jwt
import pytest
from alxprgs_sso import InvalidTokenError, SSOClient
from app.config import get_settings
from app.core import security
from app.core.exceptions import OAuthErrorException
from cryptography.hazmat.primitives.asymmetric import rsa


def claims(use="access_token"):
    now = int(time.time())
    return {
        "iss": get_settings().OIDC_ISSUER,
        "aud": "audit-rp",
        "sub": "audit-synthetic-subject",
        "exp": now + 300,
        "iat": now,
        "token_use": use,
        "scope": "openid profile",
        "auth_time": now,
        "nonce": "audit-nonce",
    }


def attack_claims(kind):
    now = int(time.time())
    cases = {
        "wrong_issuer": {"iss": "https://other.example.test"},
        "wrong_audience": {"aud": "other-rp"},
        "expired": {"exp": now - 60, "iat": now - 120, "auth_time": now - 120},
        "id_as_access": {"token_use": "id_token"},
    }
    return cases.get(kind, {})


def attack_key(kind):
    if kind == "none":
        return None
    if kind == "HS256":
        return secrets.token_bytes(32)
    if kind == "bad_signature":
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return security.get_rsa_private_key()


@pytest.mark.parametrize(
    "kind",
    [
        "none",
        "HS256",
        "wrong_issuer",
        "wrong_audience",
        "expired",
        "unknown_kid",
        "id_as_access",
        "bad_signature",
    ],
)
def test_real_crypto_rejects_adversarial_access_token(kind):
    value = claims()
    headers = {"kid": security.get_active_key_id()}
    value.update(attack_claims(kind))
    algorithm = {"none": "none", "HS256": "HS256"}.get(kind, "RS256")
    key = attack_key(kind)
    headers["kid"] = "unregistered-key" if kind == "unknown_kid" else headers["kid"]
    token = jwt.encode(value, key, algorithm=algorithm, headers=headers)
    client = SSOClient(server_url=get_settings().OIDC_ISSUER, client_id="audit-rp")
    with pytest.raises(OAuthErrorException):
        security.decode_jwt(token, audience="audit-rp", expected_use="access_token")
    # Supply actual public keys locally; signature/claims verification is never mocked.
    with patch.object(client, "get_jwks", return_value=security.get_jwks()):
        with pytest.raises(InvalidTokenError):
            client.verify_access_token(token)


def test_real_crypto_accepts_valid_access_and_nonce_id():
    client = SSOClient(server_url=get_settings().OIDC_ISSUER, client_id="audit-rp")
    with patch.object(client, "get_jwks", return_value=security.get_jwks()):
        for use in ("access_token", "id_token"):
            token = jwt.encode(
                claims(use),
                security.get_rsa_private_key(),
                algorithm="RS256",
                headers={"kid": security.get_active_key_id()},
            )
            security.decode_jwt(token, audience="audit-rp", expected_use=use)
            if use == "access_token":
                assert client.verify_access_token(token).scope == "openid profile"
            else:
                assert client.verify_id_token(token, "audit-nonce")["nonce"] == "audit-nonce"
                with pytest.raises(InvalidTokenError):
                    client.verify_id_token(token, "wrong-nonce")


@pytest.mark.parametrize("claim", ["iat", "exp", "iss", "sub", "aud", "auth_time"])
def test_sdk_requires_complete_id_token_profile(claim):
    value = claims("id_token")
    value.pop(claim)
    token = jwt.encode(
        value,
        security.get_rsa_private_key(),
        algorithm="RS256",
        headers={"kid": security.get_active_key_id()},
    )
    client = SSOClient(server_url=get_settings().OIDC_ISSUER, client_id="audit-rp")
    with (
        patch.object(client, "get_jwks", return_value=security.get_jwks()),
        pytest.raises(InvalidTokenError),
    ):
        client.verify_id_token(token, "audit-nonce", max_age=300)
