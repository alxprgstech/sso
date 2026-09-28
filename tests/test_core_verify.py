import os
import sys

import jwt
import pytest

sys.path.insert(0, os.path.abspath("backend"))

from app.config import get_settings
from app.core.exceptions import OAuthErrorException
from app.core.security import (
    create_jwt,
    decode_jwt,
    get_jwks,
    hash_password,
    verify_password,
    verify_pkce,
)


def test_core_security() -> None:
    s = get_settings()
    assert s.FEATURE_TOTP_ENABLED is False
    assert s.FEATURE_PASSKEY_ENABLED is False
    assert s.FEATURE_RECOVERY_CODES_ENABLED is False
    assert s.FEATURE_EMAIL_VERIFICATION_ENABLED is False
    assert s.REQUIRE_VERIFIED_EMAIL is False

    h = hash_password("TestPassword123!")
    assert verify_password("TestPassword123!", h)
    assert not verify_password("WrongPassword!", h)

    jwks = get_jwks()
    assert len(jwks["keys"]) >= 1
    assert jwks["keys"][0]["alg"] == "RS256"

    token = create_jwt({"sub": "test-uuid-123", "roles": ["admin"]}, expires_in_seconds=300)
    payload = decode_jwt(token)
    assert payload["sub"] == "test-uuid-123"
    assert payload["roles"] == ["admin"]

    # Test PKCE S256 verification (RFC 7636 Appendix B)
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert verify_pkce(verifier, challenge, "S256")
    assert not verify_pkce("wrong_verifier", challenge, "S256")


def test_jwt_failure_does_not_echo_attacker_kid() -> None:
    tainted = "untrusted-sensitive-marker"
    token = jwt.encode(
        {"sub": "synthetic", "iss": "https://auth.alxprgs.tech"},
        b"s" * 32,
        algorithm="HS256",
        headers={"kid": tainted},
    )
    with pytest.raises(OAuthErrorException) as failure:
        decode_jwt(token)
    assert failure.value.status_code == 401
    assert tainted not in str(failure.value.detail)


if __name__ == "__main__":
    test_core_security()
    print("ALL CORE SECURITY TESTS PASSED SUCCESSFULLY!")
