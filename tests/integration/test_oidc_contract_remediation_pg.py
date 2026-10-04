import base64
import hashlib
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from app.config import get_settings
from app.core.security import decode_jwt, get_active_key_id, get_rsa_private_key, hash_password
from app.models.oidc import OIDCClient, OIDCRedirectUri, RefreshToken
from app.models.session import Session
from app.models.user import PasswordCredential, User
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from tests.helpers.privacy import accept_current_documents, record_test_consent

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
PASSWORD = "ProtocolRegressionPassword2026!"
CALLBACK = "https://rp.example.test/callback"
VERIFIER = "v" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
)


async def seed(db, client, scopes="openid profile email", logged_in=True):
    user = User(username="protocol_user", email="protocol@example.test", is_superuser=False)
    user.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    rp = OIDCClient(
        client_id="protocol_rp", client_type="public", client_name="Protocol", allowed_scopes=scopes
    )
    rp.redirect_uris = [OIDCRedirectUri(uri=CALLBACK)]
    db.add_all([user, rp])
    await record_test_consent(db, user)
    if logged_in:
        login = await client.post(
            "/api/v1/auth/login", json={"username": user.username, "password": PASSWORD}
        )
        assert login.status_code == 200
    return user, rp


def parameters(**extra):
    return {
        "client_id": "protocol_rp",
        "redirect_uri": CALLBACK,
        "response_type": "code",
        "scope": "openid profile email",
        "state": "bound_state",
        "nonce": "bound_nonce",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        **extra,
    }


async def exchange(client, response):
    code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
    result = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "protocol_rp",
            "redirect_uri": CALLBACK,
            "code": code,
            "code_verifier": VERIFIER,
        },
    )
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    return result.json()


async def test_prompt_login_demands_new_password_authentication_once(pg_session, pg_client):
    await seed(pg_session, pg_client)
    first = await pg_client.get("/oauth/authorize", params=parameters(prompt="login"))
    assert "/login?force_login=1" in first.headers["location"]
    repeated = await pg_client.get("/oauth/authorize", params=parameters(prompt="login"))
    assert "/login?force_login=1" in repeated.headers["location"]
    login = await pg_client.post(
        "/api/v1/auth/login", json={"username": "protocol_user", "password": PASSWORD}
    )
    assert login.status_code == 200
    completed = await pg_client.get("/oauth/authorize", params=parameters(prompt="login"))
    tokens = await exchange(pg_client, completed)
    claims = decode_jwt(tokens["id_token"], audience="protocol_rp", expected_use="id_token")
    session = await pg_session.scalar(select(Session).order_by(Session.auth_time.desc()))
    assert claims["auth_time"] == int(session.auth_time.timestamp())
    assert claims["nonce"] == "bound_nonce"


async def test_prompt_none_and_client_scope_policy(pg_session, pg_client):
    await seed(pg_session, pg_client, scopes="openid", logged_in=False)
    silent = await pg_client.get(
        "/oauth/authorize", params=parameters(prompt="none", scope="openid")
    )
    assert parse_qs(urlsplit(silent.headers["location"]).query) == {
        "error": ["login_required"],
        "state": ["bound_state"],
    }
    assert "/login" not in silent.headers["location"]
    login = await pg_client.post(
        "/api/v1/auth/login", json={"username": "protocol_user", "password": PASSWORD}
    )
    assert login.status_code == 200
    excessive = await pg_client.get("/oauth/authorize", params=parameters())
    assert parse_qs(urlsplit(excessive.headers["location"]).query)["error"] == ["invalid_scope"]
    accepted = await pg_client.get(
        "/oauth/authorize", params=parameters(scope="openid", prompt="none")
    )
    tokens = await exchange(pg_client, accepted)
    claims = decode_jwt(tokens["access_token"], audience="protocol_rp", expected_use="access_token")
    assert claims["scope"] == "openid"
    assert not {"roles", "email", "preferred_username", "email_verified"} & claims.keys()


async def test_logout_post_with_expired_current_hint_and_hintless_confirmation(
    pg_session, pg_client
):
    user, _ = await seed(pg_session, pg_client)
    session = await pg_session.scalar(select(Session))
    now = int(time.time())
    session.auth_time -= timedelta(minutes=15)
    await pg_session.commit()
    hint = jwt.encode(
        {
            "iss": get_settings().OIDC_ISSUER,
            "sub": str(user.id),
            "aud": "protocol_rp",
            "token_use": "id_token",
            "iat": now - 600,
            "exp": now - 300,
            "auth_time": int(session.auth_time.timestamp()),
        },
        get_rsa_private_key(),
        algorithm="RS256",
        headers={"kid": get_active_key_id()},
    )
    result = await pg_client.post(
        "/oauth/logout",
        data={"id_token_hint": hint, "post_logout_redirect_uri": CALLBACK, "state": "logout_state"},
    )
    assert result.status_code == 302
    assert parse_qs(urlsplit(result.headers["location"]).query)["state"] == ["logout_state"]
    assert (await pg_client.get("/api/v1/auth/me")).status_code == 401
    login = await pg_client.post(
        "/api/v1/auth/login", json={"username": "protocol_user", "password": PASSWORD}
    )
    await accept_current_documents(pg_client, login)
    confirmation = await pg_client.get("/oauth/logout")
    assert confirmation.status_code == 200 and "Завершить текущую сессию" in confirmation.text
    assert (await pg_client.post("/oauth/logout", data={})).status_code == 403
    assert (await pg_client.get("/api/v1/auth/me")).status_code == 200
    assert (
        await pg_client.post("/oauth/logout", data={"csrf_token": login.json()["csrf_token"]})
    ).status_code == 302
    assert (await pg_client.get("/api/v1/auth/me")).status_code == 401


async def test_oauth_wire_errors_duplicates_and_session_cookie_revocation_rejection(
    pg_session, pg_client
):
    await seed(pg_session, pg_client)
    cookie = pg_client.cookies.get("alx_session")
    response = await pg_client.post(
        "/oauth/revoke", data={"client_id": "protocol_rp", "token": cookie}
    )
    assert response.status_code == 200
    assert (await pg_client.get("/api/v1/auth/me")).status_code == 200
    missing = await pg_client.post("/oauth/token", data={})
    assert (
        missing.status_code == 400
        and missing.json()["error"] == "invalid_request"
        and "detail" not in missing.json()
    )
    duplicate = await pg_client.post(
        "/oauth/token",
        content="grant_type=authorization_code&grant_type=refresh_token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert duplicate.status_code == 400 and duplicate.json()["error"] == "invalid_request"
    invalid_client = await pg_client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "client_id": "absent", "refresh_token": "synthetic"},
    )
    assert invalid_client.status_code == 401 and invalid_client.headers[
        "www-authenticate"
    ].startswith("Basic")
    invalid_bearer = await pg_client.get("/oauth/userinfo")
    assert invalid_bearer.status_code == 401 and invalid_bearer.headers[
        "www-authenticate"
    ].startswith("Bearer")
    unsafe = await pg_client.get(
        "/oauth/authorize", params=parameters(redirect_uri="https://evil.example.test/")
    )
    assert unsafe.status_code == 400 and "location" not in unsafe.headers


async def test_confidential_basic_scheme_is_case_insensitive(pg_session, pg_client):
    _, rp = await seed(pg_session, pg_client)
    secret = "ConfidentialSyntheticProtocol2026!"
    rp.client_type, rp.client_secret_hash = "confidential", hash_password(secret)
    await pg_session.commit()
    authorized = await pg_client.get("/oauth/authorize", params=parameters())
    code = parse_qs(urlsplit(authorized.headers["location"]).query)["code"][0]
    basic = base64.b64encode(f"protocol_rp:{secret}".encode()).decode()
    result = await pg_client.post(
        "/oauth/token",
        headers={"Authorization": f"bAsIc {basic}"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": VERIFIER,
            "redirect_uri": CALLBACK,
        },
    )
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store" and result.headers["pragma"] == "no-cache"
    decode_jwt(result.json()["access_token"], audience="protocol_rp", expected_use="access_token")


async def test_revocation_is_bound_to_client_and_only_oauth_grants(pg_session, pg_client):
    await seed(pg_session, pg_client)
    authorized = await pg_client.get("/oauth/authorize", params=parameters())
    tokens = await exchange(pg_client, authorized)
    other = OIDCClient(client_id="other_rp", client_name="Other RP", client_type="public")
    pg_session.add(other)
    await pg_session.commit()
    for token in (
        "unknown-synthetic-token",
        pg_client.cookies.get("alx_session"),
        tokens["refresh_token"],
    ):
        result = await pg_client.post(
            "/oauth/revoke", data={"client_id": "other_rp", "token": token}
        )
        assert result.status_code == 200
        assert (await pg_client.get("/api/v1/auth/me")).status_code == 200
    refreshed = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": "protocol_rp",
            "refresh_token": tokens["refresh_token"],
        },
    )
    assert refreshed.status_code == 200
    own = refreshed.json()["refresh_token"]
    assert (
        await pg_client.post("/oauth/revoke", data={"client_id": "protocol_rp", "token": own})
    ).status_code == 200
    rejected = await pg_client.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "client_id": "protocol_rp", "refresh_token": own},
    )
    assert rejected.status_code == 400 and rejected.json()["error"] == "invalid_grant"
    assert (await pg_client.get("/api/v1/auth/me")).status_code == 200
    assert all(token.is_revoked for token in (await pg_session.scalars(select(RefreshToken))).all())


@pytest.mark.parametrize(
    "case,status",
    [
        ("foreign_subject", 401),
        ("wrong_issuer", 401),
        ("bad_signature", 401),
        ("wrong_redirect", 400),
        ("expired_no_session", 401),
        ("mismatched_client", 400),
    ],
)
async def test_logout_rejects_unbound_or_invalid_hints_without_destroying_session(
    pg_session, pg_client, case, status
):
    user, _ = await seed(pg_session, pg_client)
    session = await pg_session.scalar(select(Session))
    now = int(time.time())
    value = {
        "iss": get_settings().OIDC_ISSUER,
        "sub": str(user.id),
        "aud": "protocol_rp",
        "token_use": "id_token",
        "iat": now,
        "exp": now + 300,
        "auth_time": int(session.auth_time.timestamp()),
    }
    signing_key = get_rsa_private_key()
    params = {"post_logout_redirect_uri": CALLBACK, "state": "safe_logout_state"}
    if case == "foreign_subject":
        value["sub"] = str(uuid.uuid4())
    elif case == "wrong_issuer":
        value["iss"] = "https://foreign.example.test"
    elif case == "bad_signature":
        signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif case == "wrong_redirect":
        params["post_logout_redirect_uri"] = "https://unregistered.example.test/"
    elif case == "mismatched_client":
        params["client_id"] = "other_rp"
    elif case == "expired_no_session":
        value["exp"], value["iat"], value["auth_time"] = now - 60, now - 120, now - 120
        pg_client.cookies.clear()
    params["id_token_hint"] = jwt.encode(
        value, signing_key, algorithm="RS256", headers={"kid": get_active_key_id()}
    )
    response = await pg_client.post("/oauth/logout", data=params)
    assert response.status_code == status and "location" not in response.headers
    if case != "expired_no_session":
        assert (await pg_client.get("/api/v1/auth/me")).status_code == 200
    assert (await pg_session.scalar(select(Session.id))) == session.id
