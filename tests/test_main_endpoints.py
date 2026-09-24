import sys
import os
sys.path.insert(0, os.path.abspath("backend"))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_live():
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert "x-request-id" in res.headers
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"


def test_oidc_discovery():
    res = client.get("/.well-known/openid-configuration")
    assert res.status_code == 200
    data = res.json()
    assert data["issuer"] == "https://auth.alxprgs.tech"
    assert "authorization_endpoint" in data
    assert "token_endpoint" in data
    assert "jwks_uri" in data
    assert "S256" in data["code_challenge_methods_supported"]
    assert "RS256" in data["id_token_signing_alg_values_supported"]


def test_oidc_jwks():
    res = client.get("/.well-known/jwks.json")
    assert res.status_code == 200
    data = res.json()
    assert "keys" in data
    assert len(data["keys"]) >= 1
    key = data["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert "kid" in key
    assert "n" in key
    assert "e" in key


if __name__ == "__main__":
    test_health_live()
    test_oidc_discovery()
    test_oidc_jwks()
    print("ALL MAIN ENDPOINTS TESTS PASSED!")
