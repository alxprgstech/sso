import pytest
from app.models.oidc import AuthorizationCode, OIDCClient, OIDCRedirectUri
from app.models.session import Session
from sqlalchemy import func, select

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]


async def test_public_client_context_validates_exact_redirect_without_grant(pg_session, pg_client):
    rp = OIDCClient(client_id="context_rp", client_name="Trusted application", client_type="public")
    rp.redirect_uris = [OIDCRedirectUri(uri="https://rp.example.test/callback?fixed=1")]
    pg_session.add(rp)
    await pg_session.commit()
    params = {"client_id": rp.client_id, "redirect_uri": rp.redirect_uris[0].uri}
    response = await pg_client.get("/oauth/client-context", params=params)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "client_name": "Trusted application",
        "redirect_origin": "https://rp.example.test",
    }
    assert not pg_client.cookies
    assert await pg_session.scalar(select(func.count()).select_from(Session)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(AuthorizationCode)) == 0
    for redirect in (
        "https://rp.example.test/callback",
        "https://rp.example.test/callback?fixed=2",
        "https://rp.example.test.evil.test/callback?fixed=1",
    ):
        rejected = await pg_client.get(
            "/oauth/client-context", params=params | {"redirect_uri": redirect}
        )
        assert rejected.status_code == 400
        assert "client_name" not in rejected.json()
    duplicate = await pg_client.get(
        "/oauth/client-context",
        params=[*params.items(), ("client_id", "another")],
    )
    assert duplicate.status_code == 400
    rp.is_active = False
    await pg_session.commit()
    assert (await pg_client.get("/oauth/client-context", params=params)).status_code == 401
    assert (
        await pg_client.get("/oauth/client-context", params=params | {"client_id": "unknown"})
    ).status_code == 401
