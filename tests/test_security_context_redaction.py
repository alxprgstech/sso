"""Security input representations must never embed passwords or factor secrets."""

import uuid

import pytest
from app.services.auth_service import LoginAttempt, SessionAuthorization, SessionRequest
from app.services.mfa_service import PasskeyAuthentication, PasskeyRegistration, WebAuthnContext
from app.services.reauthentication_service import FactorProof, MutationProof

from tests.helpers.reauthentication import MutationRequest, RequestAuthorization

MARKER = "sensitive-context-canary"


@pytest.mark.parametrize(
    "context",
    [
        LoginAttempt(MARKER, MARKER, MARKER, MARKER),
        SessionRequest(uuid.uuid4(), MARKER, MARKER),
        SessionAuthorization(mfa_token=MARKER),
        MutationProof(MARKER, MARKER, MARKER),
        FactorProof(MARKER, "totp", MARKER, {"credential": MARKER}),
        MutationRequest("POST", "/api/v1/auth/change-password", {"password": MARKER}),
        RequestAuthorization(MARKER, {"X-CSRF-Token": MARKER}, {"code": MARKER}),
        WebAuthnContext(rp_id=MARKER, origin=MARKER),
        PasskeyRegistration({"credential": MARKER}, name=MARKER),
        PasskeyAuthentication(expected_challenge=MARKER),
    ],
)
def test_sensitive_context_repr_excludes_input_values(context):
    representation = repr(context)
    assert type(context).__name__ in representation
    assert MARKER not in representation
