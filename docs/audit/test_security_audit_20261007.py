"""Regression of the audit finding: mailbox binding must reject service-only proof.

Gmail trust uses a local RSA fixture and MockTransport, never live Google.
PostgreSQL is real and guarded by tests.conftest. Google is never contacted; the signature is cryptographically checked with a fixture key.
"""

import json
import time
import uuid
from secrets import token_urlsafe

import httpx
import jwt
import pytest
from app.config import Settings, get_settings
from app.core.security import hash_password
from app.legal import REQUIRED_DOCUMENTS
from app.main import app
from app.models.user import User
from app.services import registration_service
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select, text


@pytest.mark.postgres
async def test_gmail_bearer_reused_for_unrelated_mailboxes(pg_session, pg_client, monkeypatch):
    from app.services.google_keys import clear_cache

    clear_cache()
    messages = []
    test_password = token_urlsafe(32)
    cfg = Settings(_env_file=None, ENVIRONMENT="testing", BASE_URL="https://auth.alxprgs.tech")
    app.dependency_overrides[get_settings] = lambda: cfg

    async def delivery(*args, **kwargs):
        messages.append(args[0])

    monkeypatch.setattr(registration_service, "deliver_message", delivery)
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed=true, registration_mode='open' WHERE id=1"
        )
    )
    await pg_session.commit()
    challenges = []
    browser_proofs = []
    action_secrets = []
    original_send = registration_service.RegistrationService._send

    async def capture_action(db, pending, code, link, action, settings):
        action_secrets.append(action)
        await original_send(db, pending, code, link, action, settings)

    monkeypatch.setattr(registration_service.RegistrationService, "_send", capture_action)
    for index in range(2):
        reply = await pg_client.post(
            "/api/v1/auth/register",
            json={
                "username": f"audit_mail_{index}",
                "email": f"unowned{index}@example.test",
                "password": test_password,
                "confirm_password": test_password,
                "terms_accepted": True,
                "data_processing_consent": True,
                "legal_versions": REQUIRED_DOCUMENTS,
            },
        )
        assert reply.status_code == 202
        challenges.append(reply.json()["challenge_id"])
        browser_proofs.append(pg_client.cookies.get("alx_registration"))
    pg_client.cookies.clear()  # Model the Gmail service, which has no initiating-browser proof.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="audit-google-fixture", alg="RS256", use="sig")
    encoded = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": "https://alxprgs.tech",
            "azp": "gmail@system.gserviceaccount.com",
            "iat": int(time.time()) - 1,
            "exp": int(time.time()) + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": jwk["kid"]},
    )
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"keys": [jwk]})
            ),
            **kwargs,
        ),
    )
    try:
        for challenge in challenges:
            reply = await pg_client.post(
                "/api/v1/auth/register/confirm-gmail",
                params={"challenge_id": challenge},
                headers={"Authorization": "Bearer " + encoded},
            )
            assert reply.status_code == 422
        import re

        for message in messages:
            html = message.get_body(preferencelist=("html",)).get_content()
            schema = json.loads(
                re.search(r'<script type="application/ld\+json">(.*?)</script>', html).group(1)
            )
            assert schema["potentialAction"]["@type"] == "ViewAction"
            assert "/verify-email?mode=registration" in schema["potentialAction"]["target"]
        wrong = await pg_client.post(
            "/api/v1/auth/register/confirm-gmail",
            params={"challenge_id": challenges[1], "action_token": action_secrets[0]},
            headers={"Authorization": "Bearer " + encoded},
        )
        assert wrong.status_code == 401
        for challenge, secret, browser in zip(
            challenges, action_secrets, browser_proofs, strict=True
        ):
            no_browser = await pg_client.post(
                "/api/v1/auth/register/confirm-gmail",
                params={"challenge_id": challenge, "action_token": secret},
                headers={"Authorization": "Bearer " + encoded},
            )
            assert no_browser.status_code == 401
            result = await pg_client.post(
                "/api/v1/auth/register/confirm-gmail",
                params={"challenge_id": challenge, "action_token": secret},
                headers={
                    "Authorization": "Bearer " + encoded,
                    "Cookie": "alx_registration=" + browser,
                },
            )
            assert result.status_code == 200
            replay = await pg_client.post(
                "/api/v1/auth/register/confirm-gmail",
                params={"challenge_id": challenge, "action_token": secret},
                headers={"Authorization": "Bearer " + encoded},
            )
            assert replay.status_code == 401
        users = (
            await pg_session.scalars(select(User).where(User.username.like("audit_mail_%")))
        ).all()
        assert len(users) == 2 and all(user.email_verified for user in users)
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "media_type,expected_status", [(None, 422), ("text/plain", 422), ("application/json", 200)]
)
async def test_login_cross_origin_candidate(pg_session, pg_client, media_type, expected_status):
    from app.models.user import PasswordCredential

    test_password = token_urlsafe(32)
    user = User(
        id=uuid.uuid4(),
        username="audit_login",
        email="audit_login@example.test",
        is_active=True,
        email_verified=True,
    )
    pg_session.add(user)
    await pg_session.flush()
    pg_session.add(PasswordCredential(user_id=user.id, password_hash=hash_password(test_password)))
    await pg_session.commit()
    headers = {"Origin": "https://untrusted.alxprgs.tech"}
    if media_type:
        headers["Content-Type"] = media_type
    reply = await pg_client.post(
        "/api/v1/auth/login",
        content=json.dumps({"username": user.username, "password": test_password}),
        headers=headers,
    )
    # Record MIME acceptance without printing cookies or tokens.
    print(
        f"audit-login media={media_type!r} status={reply.status_code} cookie={'set-cookie' in reply.headers}"
    )
    assert reply.status_code == expected_status
    assert ("set-cookie" in reply.headers) == (expected_status == 200)
