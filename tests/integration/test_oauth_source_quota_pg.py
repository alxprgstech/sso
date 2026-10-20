"""SSO-SEC-0001: an unauthenticated source cannot exhaust another source's grants."""

import httpx
import pytest
from app.main import app
from app.models.oidc import OIDCRedirectUri
from app.services.oidc_service import OIDCService

from tests.integration.test_oidc_pg import make_pkce_pair
from tests.integration.test_security_revision_pg import seed


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_invalid_token_burst_preserves_other_source_and_revoke(pg_client, pg_session):
    user, client = await seed(pg_session)
    redirect = "http://localhost:9999/callback"
    pg_session.add(OIDCRedirectUri(client_id=client.id, uri=redirect))
    await pg_session.commit()
    await pg_session.refresh(client, ["redirect_uris"])
    verifier, challenge = make_pkce_pair()
    code = await OIDCService.create_authorization_code(
        pg_session, client, user, redirect, challenge
    )
    payload = dict(
        grant_type="authorization_code",
        client_id=client.client_id,
        code="invalid",
        code_verifier=verifier,
        redirect_uri=redirect,
    )
    statuses = [(await pg_client.post("/oauth/token", data=payload)).status_code for _ in range(31)]
    assert statuses == [400] * 30 + [429]
    # Same source may still revoke: token traffic cannot consume its revoke quota.
    assert (
        await pg_client.post(
            "/oauth/revoke", data={"client_id": client.client_id, "token": "unknown"}
        )
    ).status_code == 200
    transport = httpx.ASGITransport(app=app, client=("198.51.100.8", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as other:
        result = await other.post("/oauth/token", data={**payload, "code": code})
        assert result.status_code == 200
        rotated = await other.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client.client_id,
                "refresh_token": result.json()["refresh_token"],
            },
        )
        assert rotated.status_code == 200
        assert (await other.post("/oauth/token", data={**payload, "code": code})).status_code == 400
