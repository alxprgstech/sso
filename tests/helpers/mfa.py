"""Real MFA enrolment/elevation helpers for integration tests.

These helpers use the public HTTP API and real WebAuthn signatures; they never
write ``mfa_verified`` or credentials directly to the database.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.models.session import Session
from app.models.user import User
from app.services.mfa_service import (
    PasskeyRegistration,
    WebAuthnContext,
    WebAuthnService,
)
from sqlalchemy import select

from tests.helpers.privacy import accept_current_documents
from tests.helpers.reauthentication import (
    MutationRequest,
    RequestAuthorization,
    authorized_request,
)
from tests.helpers.webauthn_authenticator import Authenticator


@dataclass
class AdminMfaSession:
    headers: dict[str, str]
    authenticator: Authenticator
    origin: str
    user_id: str

    def factor(self, proof: dict) -> dict:
        """Reauthentication factor callable using a fresh assertion."""
        return {
            "method": "passkey",
            "credential": self.authenticator.assertion(proof["passkey_options"], self.origin),
        }


async def login_admin_with_mfa(
    client,
    username: str,
    password: str,
    *,
    origin: str | None = None,
) -> AdminMfaSession:
    """Password login -> real Passkey enrolment -> server elevation."""
    active_origin = origin or get_settings().WEBAUTHN_ORIGIN
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert login.status_code == 200, login.json()
    body = login.json()
    if body.get("mfa_required") is not True:
        assert body["user"]["session_purpose"] == "admin_mfa_enrollment"
        assert body["user"]["admin_mfa_required"] is True
    await accept_current_documents(client, login)
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}

    authenticator = Authenticator()
    options = await authorized_request(
        client,
        MutationRequest("POST", "/api/v1/mfa/passkey/register/options"),
        RequestAuthorization(password, headers),
    )
    assert options.status_code == 200, options.json()
    registered = await authorized_request(
        client,
        MutationRequest(
            "POST",
            "/api/v1/mfa/passkey/register/verify",
            json_body={
                "name": "Integration admin key",
                "credential": authenticator.registration(options.json(), active_origin),
            },
        ),
        RequestAuthorization(password, headers),
    )
    assert registered.status_code == 200, registered.json()

    elevate_options = await client.post(
        "/api/v1/auth/session/elevate/passkey/options", headers=headers
    )
    assert elevate_options.status_code == 200, elevate_options.json()
    elevated = await client.post(
        "/api/v1/auth/session/elevate",
        headers=headers,
        json={
            "method": "passkey",
            "credential": authenticator.assertion(elevate_options.json(), active_origin),
        },
    )
    assert elevated.status_code == 200, elevated.json()
    assert elevated.json()["mfa_verified"] is True
    assert elevated.json()["admin_mfa_required"] is False
    assert elevated.json()["session_purpose"] == "full"
    return AdminMfaSession(headers, authenticator, active_origin, str(elevated.json()["id"]))


async def login_admin_with_mfa_direct(
    db,
    client,
    username: str,
    password: str,
    *,
    origin: str | None = None,
) -> AdminMfaSession:
    """Fast fixture for tests whose subject is not MFA enrolment itself.

    The Passkey registration and signature verification still use the real
    production WebAuthn service and PostgreSQL state, but the two HTTP
    reauthentication proofs that enrolment would consume are skipped so the
    test's own sensitive actions stay inside the unchanged reauth rate limit.
    The dedicated admin-MFA tests exercise the full HTTP onboarding path.
    """
    active_origin = origin or get_settings().WEBAUTHN_ORIGIN
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert login.status_code == 200, login.json()
    assert login.json()["user"]["session_purpose"] == "admin_mfa_enrollment"
    await accept_current_documents(client, login)
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}

    user = (await db.execute(select(User).where(User.username == username))).scalar_one()
    session = (
        await db.execute(
            select(Session)
            .where(
                Session.user_id == user.id,
                Session.purpose == "admin_mfa_enrollment",
            )
            .order_by(Session.created_at.desc())
            .limit(1)
        )
    ).scalar_one()

    authenticator = Authenticator()
    context = WebAuthnContext(
        settings=get_settings(),
        origin=active_origin,
        session_id=session.id,
    )
    options = await WebAuthnService.get_registration_options(db, user, context=context)
    assert await WebAuthnService.verify_registration(
        db,
        user,
        PasskeyRegistration(
            authenticator.registration(options, active_origin), name="Fixture admin key"
        ),
        context=context,
    )

    elevate_options = await client.post(
        "/api/v1/auth/session/elevate/passkey/options", headers=headers
    )
    assert elevate_options.status_code == 200, elevate_options.json()
    elevated = await client.post(
        "/api/v1/auth/session/elevate",
        headers=headers,
        json={
            "method": "passkey",
            "credential": authenticator.assertion(elevate_options.json(), active_origin),
        },
    )
    assert elevated.status_code == 200, elevated.json()
    assert elevated.json()["admin_mfa_required"] is False
    return AdminMfaSession(headers, authenticator, active_origin, str(elevated.json()["id"]))
