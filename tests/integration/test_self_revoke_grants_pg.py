"""SSO-SEC-0002: self-service revocation terminates refresh/code authority."""

import uuid

import pytest
from app.config import get_settings
from app.core.exceptions import OAuthErrorException
from app.core.security import decode_jwt
from app.models.oidc import AuthorizationCode, RefreshToken
from app.models.session import Session
from app.services.auth_service import AuthService, SessionRequest
from app.services.oidc_service import OIDCService
from sqlalchemy import func, select

from tests.integration.test_oidc_pg import make_pkce_pair
from tests.integration.test_security_event_races_pg import DatabaseLockRace
from tests.integration.test_security_revision_pg import seed

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]


@pytest.mark.parametrize("operation", ["one", "others", "logout", "oidc_logout"])
async def test_self_revoke_terminates_grants_preserves_other_sessions(
    pg_session, pg_client, operation
):
    user, client = await seed(pg_session)
    cfg = get_settings()
    raw, first, csrf = await AuthService.create_user_session(
        pg_session, SessionRequest(user.id, None, None), cfg
    )
    _, second, _ = await AuthService.create_user_session(
        pg_session, SessionRequest(user.id, None, None), cfg
    )
    tokens = await OIDCService._generate_tokens_for_user(
        pg_session, user, client, "openid profile email", expected_revision=0
    )
    verifier, challenge = make_pkce_pair()
    code = await OIDCService.create_authorization_code(
        pg_session, client, user, "http://localhost:9999/callback", challenge
    )
    if operation == "one":
        # A nonexistent/foreign session cannot be used to revoke an owner's grants.
        assert not await AuthService.revoke_session(pg_session, uuid.uuid4(), user.id)
        assert await pg_session.scalar(select(RefreshToken).where(~RefreshToken.is_revoked))
        assert await AuthService.revoke_session(pg_session, first.id, user.id)
        kept = second.id
    elif operation == "others":
        assert await AuthService.revoke_all_sessions(pg_session, user.id, first.id) == 1
        kept = first.id
    else:
        pg_client.cookies.set("alx_session", raw)
        if operation == "logout":
            response = await pg_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
            assert response.status_code == 200
        else:
            response = await pg_client.post("/oauth/logout", data={"csrf_token": csrf})
            assert response.status_code == 302
        assert (await pg_client.get("/api/v1/auth/me")).status_code == 401
        kept = second.id
    assert await pg_session.scalar(select(func.count()).select_from(Session)) == 1
    assert await pg_session.scalar(select(Session.id)) == kept
    assert not await pg_session.scalar(select(AuthorizationCode))
    assert not await pg_session.scalar(select(RefreshToken).where(~RefreshToken.is_revoked))
    # Autonomous validation of an already issued signed JWT remains valid until exp.
    assert decode_jwt(tokens.access_token, audience=client.client_id)["sub"] == str(user.id)
    with pytest.raises(OAuthErrorException):
        await OIDCService.rotate_refresh_token(
            pg_session, client.client_id, None, tokens.refresh_token
        )
    await pg_session.rollback()
    with pytest.raises(OAuthErrorException):
        await OIDCService.exchange_code(
            pg_session, client.client_id, None, code, verifier, "http://localhost:9999/callback"
        )


@pytest.mark.parametrize("grant_first", [False, True])
async def test_refresh_and_self_revoke_serialize_on_account(pg_session, pg_engine, grant_first):
    user, client = await seed(pg_session)
    old = await OIDCService._generate_tokens_for_user(
        pg_session, user, client, "openid", expected_revision=0
    )
    uid, cid = user.id, client.client_id
    granted = []

    async def grant(db):
        granted.append(await OIDCService.rotate_refresh_token(db, cid, None, old.refresh_token))

    async def revoke(db):
        await AuthService.revoke_all_sessions(db, uid)

    async def rejected(db):
        with pytest.raises(OAuthErrorException):
            await grant(db)
        await db.rollback()

    race = DatabaseLockRace(pg_engine)
    await race.run(grant if grant_first else revoke, revoke if grant_first else rejected)
    assert len(granted) == int(grant_first)
    async with race.factory() as db:
        assert not await db.scalar(select(RefreshToken).where(~RefreshToken.is_revoked))
        if granted:
            with pytest.raises(OAuthErrorException):
                await OIDCService.rotate_refresh_token(db, cid, None, granted[0].refresh_token)
