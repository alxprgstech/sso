"""Both real PostgreSQL lock orders for credential events versus grant issuance."""

import asyncio
import time
import uuid

import pyotp
import pytest
from app.config import Settings
from app.core.exceptions import AuthenticationException, OAuthErrorException
from app.core.security import hash_password
from app.models.mfa import TOTPCredential
from app.models.oidc import AuthorizationCode, OIDCRedirectUri, RefreshToken
from app.models.session import Session
from app.models.user import PasswordCredential, User
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService
from app.services.mfa_service import TOTPService, encrypt_totp_secret
from app.services.oidc_service import OIDCService
from sqlalchemy import event as sql_event
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.helpers.privacy import record_test_consent
from tests.integration.test_oidc_contract_remediation_pg import CALLBACK, CHALLENGE, VERIFIER
from tests.integration.test_security_revision_pg import PASSWORD, seed

pytestmark = [pytest.mark.postgres, pytest.mark.concurrency, pytest.mark.asyncio]
NEW_PASSWORD = "DistinctFreshRevisionPassword2026!"


@pytest.mark.parametrize(
    "scenario", ["reset_refresh", "change_code", "block_refresh", "revision_mfa"]
)
@pytest.mark.parametrize("grant_first", [False, True])
async def test_no_stale_grant_survives_security_event_in_either_order(
    pg_session, pg_engine, scenario, grant_first
):
    user, rp = await seed(pg_session)
    pg_session.add(OIDCRedirectUri(client_id=rp.id, uri=CALLBACK))
    admin = User(username="race_admin", email="raceadmin@example.test", is_superuser=True)
    admin.password_credential = PasswordCredential(password_hash=hash_password(PASSWORD))
    pg_session.add(admin)
    await record_test_consent(pg_session, admin)
    uid, aid = user.id, admin.id
    cfg = Settings(_env_file=None, FEATURE_TOTP_ENABLED=scenario == "revision_mfa")
    secret = pyotp.random_base32()
    if scenario == "revision_mfa":
        user.totp_credential = TOTPCredential(
            encrypted_secret=encrypt_totp_secret(secret), is_confirmed=True
        )
        await pg_session.commit()
        _, required, old_grant, _ = await AuthService.authenticate_user(
            pg_session, user.username, PASSWORD, settings=cfg
        )
        assert required and old_grant
    elif scenario == "change_code":
        old_grant = await OIDCService.create_authorization_code(
            pg_session, rp, user, CALLBACK, CHALLENGE, scope="openid"
        )
    else:
        old = await OIDCService._generate_tokens_for_user(
            pg_session, user, rp, "openid", expected_revision=0
        )
        old_grant = old.refresh_token
    await pg_session.commit()
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    first_locked, release = asyncio.Event(), asyncio.Event()
    granted = []
    label = "race-second-" + uuid.uuid4().hex
    first_engine = create_async_engine(pg_engine.url)
    second_engine = create_async_engine(pg_engine.url, connect_args={"application_name": label})
    paused = False

    async def pause_after_real_lock():
        first_locked.set()
        await release.wait()

    def after_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        nonlocal paused
        if not paused and "FROM users" in statement and "FOR UPDATE" in statement:
            paused = True
            # Scheduling only: the real SQL has executed and the row lock is held.
            connection.connection.dbapi_connection.run_async(lambda raw: pause_after_real_lock())

    sql_event.listen(first_engine.sync_engine, "after_cursor_execute", after_cursor_execute)

    async def grant(db):
        if scenario == "revision_mfa":
            authenticated = await AuthService.verify_mfa_step_token(
                old_grant, db, method="totp", settings=cfg
            )
            assert await TOTPService.verify_totp(
                db, authenticated, pyotp.TOTP(secret).now(), commit=False
            )
            value = await AuthService.create_user_session(
                db, uid, None, None, cfg, expected_revision=0, mfa_token=old_grant
            )
        elif scenario == "change_code":
            value = await OIDCService.exchange_code(
                db, rp.client_id, None, old_grant, VERIFIER, CALLBACK
            )
        else:
            value = await OIDCService.rotate_refresh_token(db, rp.client_id, None, old_grant)
        granted.append(value)

    async def event(db):
        if scenario in {"reset_refresh", "block_refresh"}:
            current_admin = await db.get(User, aid)
            await AdminService.update_user(
                db,
                uid,
                current_admin,
                **(
                    {"new_password": NEW_PASSWORD}
                    if scenario == "reset_refresh"
                    else {"is_active": False}
                ),
            )
        else:
            target = await db.get(User, uid)
            await AuthService.change_password(db, target, PASSWORD, NEW_PASSWORD)

    async def first():
        async with async_sessionmaker(first_engine, expire_on_commit=False)() as db:
            await (grant(db) if grant_first else event(db))

    async def second():
        async with async_sessionmaker(second_engine, expire_on_commit=False)() as db:
            if grant_first:
                await event(db)
            else:
                with pytest.raises((AuthenticationException, OAuthErrorException)):
                    await grant(db)
                await db.rollback()

    one = asyncio.create_task(first())
    two = None
    try:
        await asyncio.wait_for(first_locked.wait(), 5)
        two = asyncio.create_task(second())
        deadline = time.monotonic() + 5
        async with factory() as observer:
            while not await observer.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE application_name=:label AND wait_event_type='Lock')"
                ),
                {"label": label},
            ):
                # pg_stat snapshots are transaction-scoped; release each observation.
                await observer.rollback()
                assert not two.done(), "Competing real transaction must block on the account lock"
                assert time.monotonic() < deadline, "PostgreSQL did not observe a lock wait"
                await asyncio.sleep(0.02)
        release.set()
        await asyncio.wait_for(asyncio.gather(one, two), 15)
    finally:
        release.set()
        for task in (one, two):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (one, two) if task), return_exceptions=True)
        sql_event.remove(first_engine.sync_engine, "after_cursor_execute", after_cursor_execute)
        await first_engine.dispose()
        await second_engine.dispose()

    if scenario == "block_refresh":
        # Unblocking does not restore grants from either side of the block race.
        async with factory() as db:
            current_admin = await db.get(User, aid)
            await AdminService.update_user(db, uid, current_admin, is_active=True)
    async with factory() as db:
        expected = 2 if scenario == "block_refresh" else 1
        assert await db.scalar(select(User.security_revision).where(User.id == uid)) == expected
        assert (
            await db.scalar(select(func.count()).select_from(Session).where(Session.user_id == uid))
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuthorizationCode)
                .where(AuthorizationCode.user_id == uid)
            )
            == 0
        )
        assert not await db.scalar(
            select(RefreshToken).where(RefreshToken.user_id == uid, ~RefreshToken.is_revoked)
        )
        assert len(granted) == int(grant_first)
        if granted and scenario != "revision_mfa":
            with pytest.raises(OAuthErrorException):
                await OIDCService.get_userinfo(db, granted[0].access_token)
            await db.rollback()
            with pytest.raises(OAuthErrorException):
                await OIDCService.rotate_refresh_token(
                    db, rp.client_id, None, granted[0].refresh_token
                )
        if scenario == "revision_mfa":
            with pytest.raises(AuthenticationException):
                await AuthService.verify_mfa_step_token(old_grant, db, method="totp", settings=cfg)
