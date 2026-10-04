"""Fresh/previous upgrades and real least-privilege roles on owned databases only."""

import os
import secrets
import shutil
import sys
import uuid

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.core.database_policy import SCHEMA_REVISION, require_runtime_database_role
from app.migration_metadata import include_object, target_metadata
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from scripts.transfer_database_ownership import transfer_application_ownership
from tests.test_ops_backup_restore_totp import (
    BACKEND,
    ROOT,
    OpsSafetyError,
    cli_env,
    create_owned,
    db_url,
    drop_owned,
    parse_test_url,
    pg_uri,
    run_checked,
    verify_base,
)

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]
MARKER = "migration_drill_owner"


def migrate(url, revision):
    env = cli_env(url)
    env["DATABASE_URL_SYNC"] = url.render_as_string(hide_password=False)
    env["DATABASE_URL"] = env["DATABASE_URL_SYNC"]
    run_checked(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        env=env,
        cwd=BACKEND,
    )


def assert_head(url):
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == SCHEMA_REVISION
            context = MigrationContext.configure(
                conn,
                opts={
                    "include_object": lambda obj, name, *args: (
                        name != MARKER and include_object(obj, name, *args)
                    )
                },
            )
            assert compare_metadata(context, target_metadata) == []
            assert conn.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_sessions_ck_sessions_purpose'"
                )
            )
    finally:
        engine.dispose()


async def test_fresh_previous_upgrade_and_runtime_role_cannot_ddl():
    base = parse_test_url(os.environ.get("TEST_DATABASE_URL"))
    identity = verify_base(base)
    assert shutil.which("psql"), "A PostgreSQL client is mandatory for the role bootstrap drill"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_current_head() == SCHEMA_REVISION
    run_id = uuid.uuid4().hex
    names = [f"alxprgs_migrate_test_{kind}_{run_id}" for kind in ("fresh", "previous")]
    created = set()
    roles = ("sso_runtime", "sso_migrator")
    runtime_password, migrator_password = secrets.token_hex(32), secrets.token_hex(32)
    owned_roles = []
    errors = []
    with psycopg.connect(pg_uri(db_url(base, "postgres")), autocommit=True) as admin:
        try:
            assert not admin.execute(
                "SELECT rolname FROM pg_roles WHERE rolname=ANY(%s)", (list(roles),)
            ).fetchall(), "Role names already exist; refusing to alter unrelated roles"
            for name in names:
                create_owned(admin, base, name, MARKER, run_id, created, identity)
            env = cli_env(base)
            env.update(
                PGPASSWORD=base.password or "",
                SSO_RUNTIME_PASSWORD=runtime_password,
                SSO_MIGRATOR_PASSWORD=migrator_password,
            )
            run_checked(
                [
                    "psql",
                    "--no-psqlrc",
                    "--set",
                    "ON_ERROR_STOP=1",
                    "--host",
                    base.host,
                    "--port",
                    str(base.port),
                    "--username",
                    base.username,
                    "--dbname",
                    names[0],
                    "--file",
                    str(ROOT / "deploy/postgres/init-roles.sql"),
                ],
                env=env,
            )
            for role in roles:
                admin.execute(
                    sql.SQL("COMMENT ON ROLE {} IS {}").format(
                        sql.Identifier(role), sql.Literal(run_id)
                    )
                )
                owned_roles.append(role)
            fresh = db_url(base, names[0])
            migrator = fresh.set(username="sso_migrator", password=migrator_password)
            runtime = fresh.set(username="sso_runtime", password=runtime_password)
            migrate(migrator, "head")
            assert_head(fresh)
            with psycopg.connect(pg_uri(runtime)) as conn:
                attributes = conn.execute(
                    "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
                assert attributes == (False,) * 5
                user_id = uuid.uuid4()
                conn.execute(
                    "INSERT INTO users(id,username,email,is_active,is_superuser,email_verified) VALUES(%s,'role_drill','role@example.test',true,false,false)",
                    (user_id,),
                )
                assert (
                    conn.execute("SELECT username FROM users WHERE id=%s", (user_id,)).fetchone()[0]
                    == "role_drill"
                )
                conn.execute("UPDATE users SET email_verified=true WHERE id=%s", (user_id,))
                conn.execute("DELETE FROM users WHERE id=%s", (user_id,))
                conn.commit()
                for statement in (
                    "CREATE TABLE forbidden(id int)",
                    "ALTER TABLE users ADD forbidden int",
                    "DROP TABLE users",
                    "CREATE ROLE forbidden",
                ):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        conn.execute(statement)
                    conn.rollback()
            engine = create_async_engine(runtime)
            try:
                async with AsyncSession(engine) as db:
                    await require_runtime_database_role(db)
            finally:
                await engine.dispose()
            engine = create_async_engine(fresh)
            try:
                async with AsyncSession(engine) as db:
                    with pytest.raises(RuntimeError, match="forbidden"):
                        await require_runtime_database_role(db)
            finally:
                await engine.dispose()
            previous = db_url(base, names[1])
            migrate(previous, "0004_privacy")
            user_id, session_id = uuid.uuid4(), uuid.uuid4()
            with psycopg.connect(pg_uri(previous)) as conn:
                conn.execute(
                    "INSERT INTO users(id,username,email,is_active,is_superuser,email_verified) VALUES(%s,'previous_user','previous@example.test',true,false,false)",
                    (user_id,),
                )
                conn.execute(
                    "INSERT INTO sessions(id,user_id,session_token_hash,expires_at,last_activity_at,created_at) VALUES(%s,%s,%s,now()+interval '1 hour',now(),now()-interval '1 day')",
                    (session_id, user_id, secrets.token_hex(32)),
                )
            # An existing volume does not rerun entrypoint initialization. The
            # owner explicitly transfers only application objects before upgrade.
            with psycopg.connect(pg_uri(previous)) as conn:
                with pytest.raises(ValueError, match="confirmation"):
                    transfer_application_ownership(conn, "wrong_database", base.username)
                conn.rollback()
                with pytest.raises(ValueError, match="confirmation"):
                    transfer_application_ownership(conn, names[1], "wrong_owner")
                conn.rollback()
                assert transfer_application_ownership(conn, names[1], base.username) > 0
                assert conn.execute(
                    "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname=%s", (MARKER,)
                ).fetchone() == (base.username,)
            migrate(previous.set(username="sso_migrator", password=migrator_password), "head")
            assert_head(previous)
            with psycopg.connect(pg_uri(previous)) as conn:
                assert conn.execute(
                    "SELECT security_revision FROM users WHERE id=%s", (user_id,)
                ).fetchone() == (0,)
                assert conn.execute(
                    "SELECT auth_time=created_at FROM sessions WHERE id=%s", (session_id,)
                ).fetchone() == (True,)
        except BaseException as exc:
            errors.append(exc)
        finally:
            for name in reversed(names):
                if name in created:
                    try:
                        drop_owned(admin, base, name, MARKER, run_id, identity)
                    except BaseException as exc:
                        errors.append(exc)
            for role in reversed(owned_roles):
                try:
                    comment = admin.execute(
                        "SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s",
                        (role,),
                    ).fetchone()
                    if comment != (run_id,):
                        raise OpsSafetyError("Role ownership marker mismatch; preserving role")
                    admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
                except BaseException as exc:
                    errors.append(exc)
    if errors:
        raise BaseExceptionGroup("Migration/role drill or guarded cleanup failed", errors)
