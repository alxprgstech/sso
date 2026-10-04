"""Both real PostgreSQL lock orders for credential events versus grant issuance."""

import asyncio
import time
import uuid
from dataclasses import dataclass

import pyotp
import pytest
from app.config import Settings
from app.core.exceptions import AuthenticationException, OAuthErrorException
from app.core.security import hash_password
from app.models.mfa import TOTPCredential
from app.models.oidc import AuthorizationCode, OIDCClient, OIDCRedirectUri, RefreshToken
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


@dataclass(frozen=True)
class RaceScenario:
    scenario: str
    user_id: uuid.UUID
    admin_id: uuid.UUID
    client: OIDCClient
    settings: Settings
    secret: str
    grant: str


async def prepare_race(pg_session, scenario) -> RaceScenario:
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
    return RaceScenario(scenario, uid, aid, rp, cfg, secret, old_grant)


async def issue_grant(db, context: RaceScenario):
    if context.scenario == "revision_mfa":
        authenticated = await AuthService.verify_mfa_step_token(
            context.grant, db, method="totp", settings=context.settings
        )
        assert await TOTPService.verify_totp(
            db, authenticated, pyotp.TOTP(context.secret).now(), commit=False
        )
        value = await AuthService.create_user_session(
            db,
            context.user_id,
            None,
            None,
            context.settings,
            expected_revision=0,
            mfa_token=context.grant,
        )
    elif context.scenario == "change_code":
        value = await OIDCService.exchange_code(
            db, context.client.client_id, None, context.grant, VERIFIER, CALLBACK
        )
    else:
        value = await OIDCService.rotate_refresh_token(
            db, context.client.client_id, None, context.grant
        )
    return value


async def security_event(db, context: RaceScenario):
    if context.scenario in {"reset_refresh", "block_refresh"}:
        current_admin = await db.get(User, context.admin_id)
        await AdminService.update_user(
            db,
            context.user_id,
            current_admin,
            **(
                {"new_password": NEW_PASSWORD}
                if context.scenario == "reset_refresh"
                else {"is_active": False}
            ),
        )
    else:
        target = await db.get(User, context.user_id)
        await AuthService.change_password(db, target, PASSWORD, NEW_PASSWORD)


class DatabaseLockRace:
    def __init__(self, engine):
        self.factory = async_sessionmaker(engine, expire_on_commit=False)
        self.first_locked, self.release = asyncio.Event(), asyncio.Event()
        self.label = "race-second-" + uuid.uuid4().hex
        self.first_engine = create_async_engine(engine.url)
        self.second_engine = create_async_engine(
            engine.url, connect_args={"application_name": self.label}
        )
        paused = False

        async def pause_after_real_lock():
            self.first_locked.set()
            await self.release.wait()

        def after_cursor_execute(connection, cursor, statement, parameters, context, executemany):
            nonlocal paused
            if not paused and "FROM users" in statement and "FOR UPDATE" in statement:
                paused = True
                # Real SQL has executed; only scheduling waits while the row lock is held.
                connection.connection.dbapi_connection.run_async(
                    lambda raw: pause_after_real_lock()
                )

        self.after_cursor_execute = after_cursor_execute
        sql_event.listen(
            self.first_engine.sync_engine, "after_cursor_execute", after_cursor_execute
        )

    async def invoke(self, engine, operation):
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await operation(db)

    async def observe_lock_wait(self, two):
        deadline = time.monotonic() + 5
        async with self.factory() as observer:
            while not await observer.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE application_name=:label AND wait_event_type='Lock')"
                ),
                {"label": self.label},
            ):
                # pg_stat snapshots are transaction-scoped; release each observation.
                await observer.rollback()
                assert not two.done(), "Competing real transaction must block on the account lock"
                assert time.monotonic() < deadline, "PostgreSQL did not observe a lock wait"
                await asyncio.sleep(0.02)

    async def cleanup(self, tasks):
        self.release.set()
        for task in tasks:
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in tasks if task), return_exceptions=True)
        sql_event.remove(
            self.first_engine.sync_engine, "after_cursor_execute", self.after_cursor_execute
        )
        await self.first_engine.dispose()
        await self.second_engine.dispose()

    async def run(self, first_operation, second_operation):
        one = asyncio.create_task(self.invoke(self.first_engine, first_operation))
        two = None
        try:
            await asyncio.wait_for(self.first_locked.wait(), 5)
            two = asyncio.create_task(self.invoke(self.second_engine, second_operation))
            await self.observe_lock_wait(two)
            self.release.set()
            await asyncio.wait_for(asyncio.gather(one, two), 15)
        finally:
            await self.cleanup((one, two))


async def require_no_stale_grants(factory, context: RaceScenario, granted, grant_first):
    if context.scenario == "block_refresh":
        # Unblocking does not restore grants from either side of the block race.
        async with factory() as db:
            current_admin = await db.get(User, context.admin_id)
            await AdminService.update_user(db, context.user_id, current_admin, is_active=True)
    async with factory() as db:
        expected = 2 if context.scenario == "block_refresh" else 1
        assert (
            await db.scalar(select(User.security_revision).where(User.id == context.user_id))
            == expected
        )
        assert (
            await db.scalar(
                select(func.count()).select_from(Session).where(Session.user_id == context.user_id)
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuthorizationCode)
                .where(AuthorizationCode.user_id == context.user_id)
            )
            == 0
        )
        assert not await db.scalar(
            select(RefreshToken).where(
                RefreshToken.user_id == context.user_id, ~RefreshToken.is_revoked
            )
        )
        assert len(granted) == int(grant_first)
        if granted and context.scenario != "revision_mfa":
            with pytest.raises(OAuthErrorException):
                await OIDCService.get_userinfo(db, granted[0].access_token)
            await db.rollback()
            with pytest.raises(OAuthErrorException):
                await OIDCService.rotate_refresh_token(
                    db, context.client.client_id, None, granted[0].refresh_token
                )
        if context.scenario == "revision_mfa":
            with pytest.raises(AuthenticationException):
                await AuthService.verify_mfa_step_token(
                    context.grant, db, method="totp", settings=context.settings
                )


@pytest.mark.parametrize(
    "scenario", ["reset_refresh", "change_code", "block_refresh", "revision_mfa"]
)
@pytest.mark.parametrize("grant_first", [False, True])
async def test_no_stale_grant_survives_security_event_in_either_order(
    pg_session, pg_engine, scenario, grant_first
):
    context = await prepare_race(pg_session, scenario)
    granted = []

    async def grant(db):
        granted.append(await issue_grant(db, context))

    async def event(db):
        await security_event(db, context)

    async def rejected_grant(db):
        with pytest.raises((AuthenticationException, OAuthErrorException)):
            await grant(db)
        await db.rollback()

    race = DatabaseLockRace(pg_engine)
    await race.run(grant if grant_first else event, event if grant_first else rejected_grant)
    await require_no_stale_grants(race.factory, context, granted, grant_first)
