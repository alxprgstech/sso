"""Real PostgreSQL transactions: security events cannot revive prior authorization."""

import asyncio
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from app.config import Settings
from app.core.exceptions import AuthenticationException, OAuthErrorException
from app.core.security import hash_password, hash_token
from app.models.authentication import AuthenticationStep
from app.models.mfa import TOTPCredential
from app.models.oidc import OIDCClient, RefreshToken
from app.models.session import Session
from app.models.user import PasswordCredential, User
from app.services.auth_service import AuthService
from app.services.mfa_service import TOTPService, encrypt_totp_secret
from app.services.oidc_service import OIDCService
from app.services.security_state import invalidate_security_state, lock_user
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.helpers.privacy import record_test_consent

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
PASSWORD = "RevisionRegressionPassword2026!"


async def seed(db):
    user = User(username="revision_user", email="revision@example.test")
    user.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    client = OIDCClient(client_id="revision_client", client_name="Revision", client_type="public")
    db.add_all([user, client])
    await record_test_consent(db, user)
    return user, client


async def test_password_change_revokes_refresh_and_userinfo_preserves_current_session(pg_session):
    user, client = await seed(pg_session)
    cfg = Settings(_env_file=None)
    _, keep, _ = await AuthService.create_user_session(pg_session, user.id, None, None, cfg)
    await AuthService.create_user_session(pg_session, user.id, None, None, cfg)
    tokens = await OIDCService._generate_tokens_for_user(
        pg_session, user, client, "openid profile email", expected_revision=0
    )
    await AuthService.change_password(
        pg_session, user, PASSWORD, "NewRevisionRegressionPassword2026!", keep.id
    )
    await pg_session.refresh(keep)
    assert keep.security_revision == user.security_revision == 1
    assert await pg_session.scalar(select(func.count()).select_from(Session)) == 1
    assert not await pg_session.scalar(select(RefreshToken).where(~RefreshToken.is_revoked))
    with pytest.raises(OAuthErrorException):
        await OIDCService.get_userinfo(pg_session, tokens.access_token)
    await pg_session.rollback()
    with pytest.raises(OAuthErrorException):
        await OIDCService.rotate_refresh_token(
            pg_session, "revision_client", None, tokens.refresh_token
        )


async def test_mfa_step_is_consumed_once_and_reset_invalidates_it(pg_session):
    user, _ = await seed(pg_session)
    secret = pyotp.random_base32()
    user.totp_credential = TOTPCredential(
        encrypted_secret=encrypt_totp_secret(secret), is_confirmed=True
    )
    await pg_session.commit()
    cfg = Settings(_env_file=None, FEATURE_TOTP_ENABLED=True)
    _, required, token, methods = await AuthService.authenticate_user(
        pg_session, "revision_user", PASSWORD, settings=cfg
    )
    assert required and token and methods == ["totp"]
    verified = await AuthService.verify_mfa_step_token(
        token, pg_session, method="totp", settings=cfg
    )
    assert await TOTPService.verify_totp(
        pg_session, verified, pyotp.TOTP(secret).now(), commit=False
    )
    await AuthService.create_user_session(
        pg_session, user.id, None, None, cfg, expected_revision=0, mfa_token=token
    )
    assert await pg_session.scalar(
        select(AuthenticationStep.consumed_at).where(
            AuthenticationStep.token_hash == hash_token(token)
        )
    )
    with pytest.raises(AuthenticationException):
        await AuthService.verify_mfa_step_token(token, pg_session, method="totp", settings=cfg)
    await pg_session.rollback()
    _, _, second, _ = await AuthService.authenticate_user(
        pg_session, "revision_user", PASSWORD, settings=cfg
    )
    locked = await lock_user(pg_session, verified.id)
    await invalidate_security_state(pg_session, locked)
    await pg_session.commit()
    with pytest.raises(AuthenticationException):
        await AuthService.verify_mfa_step_token(second, pg_session, method="totp", settings=cfg)


@pytest.mark.parametrize("issuer_first", [False, True])
async def test_security_event_and_session_issue_are_serialized(pg_session, pg_engine, issuer_first):
    user, _ = await seed(pg_session)
    user_id = user.id
    await pg_session.commit()
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    started = asyncio.Event()
    release = asyncio.Event()
    cfg = Settings(_env_file=None)

    async def first():
        async with factory() as db:
            locked = await lock_user(db, user_id)
            if issuer_first:
                db.add(
                    Session(
                        user_id=user_id,
                        security_revision=0,
                        session_token_hash=hash_token("race"),
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                        last_activity_at=datetime.now(timezone.utc),
                        purpose="full",
                    )
                )
                await db.flush()
            else:
                await invalidate_security_state(db, locked)
            started.set()
            await release.wait()
            await db.commit()

    async def second():
        async with factory() as db:
            if issuer_first:
                locked = await lock_user(db, user_id)
                await invalidate_security_state(db, locked)
                await db.commit()
            else:
                with pytest.raises(AuthenticationException):
                    await AuthService.create_user_session(
                        db, user_id, None, None, cfg, expected_revision=0
                    )
                await db.rollback()

    first_task = asyncio.create_task(first())
    await asyncio.wait_for(started.wait(), timeout=5)
    second_task = asyncio.create_task(second())
    await asyncio.sleep(0.05)
    assert not second_task.done(), "Competing transaction must wait for the account row lock"
    release.set()
    await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=10)
    assert await pg_session.scalar(select(User.security_revision).where(User.id == user_id)) == 1
    assert await pg_session.scalar(select(func.count()).select_from(Session)) == 0
