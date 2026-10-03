"""Isolated PostgreSQL backup/restore with ownership checks before every DROP.

This test never changes TEST_DATABASE_URL. It creates two random databases on the
same verified server, and leaves a database in place if its ownership cannot be
proved at cleanup. A failed cleanup is a test failure requiring manual review.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import httpx
import psycopg
import pyotp
import pytest
from cryptography.fernet import Fernet
from psycopg import sql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.db_guard import EXPECTED_ENVIRONMENT, FORBIDDEN_DATABASES, MARKER_ID

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
SOURCE_MARKER = "ops_source_owner"
RESTORE_MARKER = "ops_restore_owner"


class OpsSafetyError(RuntimeError):
    pass


def parse_test_url(raw: str | None) -> URL:
    if not raw:
        raise OpsSafetyError("TEST_DATABASE_URL must be explicitly set")
    try:
        url = make_url(raw)
    except Exception:
        raise OpsSafetyError("Invalid TEST_DATABASE_URL") from None
    name = url.database or ""
    if (
        url.drivername != "postgresql+psycopg"
        or not url.host
        or not url.port
        or not url.username
        or not name
        or name.lower() in FORBIDDEN_DATABASES
        or "test" not in name.lower()
        or url.query
    ):
        raise OpsSafetyError(
            "TEST_DATABASE_URL must identify an explicit TCP PostgreSQL test database"
        )
    return url


def pg_uri(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def db_url(base: URL, name: str) -> URL:
    return base.set(database=name)


def server_identity(conn: psycopg.Connection) -> tuple[object, ...]:
    return conn.execute(
        "SELECT inet_server_addr()::text, inet_server_port(), pg_postmaster_start_time()"
    ).fetchone()


def verify_base(base: URL) -> tuple[object, ...]:
    """Read only: a preexisting marker is required; this test never creates it."""
    try:
        with psycopg.connect(pg_uri(base), connect_timeout=5) as conn:
            if conn.execute("SELECT current_database()").fetchone()[0] != base.database:
                raise OpsSafetyError("Connected database differs from TEST_DATABASE_URL")
            if (
                conn.execute("SELECT to_regclass('public.test_database_marker')").fetchone()[0]
                is None
            ):
                raise OpsSafetyError("TEST_DATABASE_URL has no test ownership marker")
            row = conn.execute(
                "SELECT environment, is_safe_to_truncate FROM public.test_database_marker "
                "WHERE marker_id = %s",
                (MARKER_ID,),
            ).fetchone()
            if row != (EXPECTED_ENVIRONMENT, True):
                raise OpsSafetyError("TEST_DATABASE_URL has an invalid test ownership marker")
            return server_identity(conn)
    except OpsSafetyError:
        raise
    except psycopg.Error:
        raise OpsSafetyError("Cannot verify TEST_DATABASE_URL marker") from None


def verify_admin(conn: psycopg.Connection, expected: tuple[object, ...]) -> None:
    if conn.execute("SELECT current_database()").fetchone()[0] != "postgres":
        raise OpsSafetyError("Administrative connection is not postgres database")
    if server_identity(conn) != expected:
        raise OpsSafetyError("Administrative connection reached a different PostgreSQL server")


def database_exists(conn: psycopg.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)", (name,)
    ).fetchone()[0]


def create_owned(
    admin: psycopg.Connection,
    base: URL,
    name: str,
    marker: str,
    run_id: str,
    created: set[str],
    expected_server: tuple[object, ...],
) -> None:
    verify_admin(admin, expected_server)
    if database_exists(admin, name):
        raise OpsSafetyError("Generated database already exists; refusing to overwrite it")
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    created.add(name)  # Track even if marker creation fails; cleanup will refuse an unmarked DB.
    with psycopg.connect(pg_uri(db_url(base, name)), connect_timeout=5) as conn:
        if server_identity(conn) != expected_server:
            raise OpsSafetyError("New database is on a different PostgreSQL server")
        conn.execute(
            sql.SQL("CREATE TABLE {} (run_id text PRIMARY KEY, db_name text NOT NULL)").format(
                sql.Identifier(marker)
            )
        )
        conn.execute(
            sql.SQL("INSERT INTO {} (run_id, db_name) VALUES (%s, %s)").format(
                sql.Identifier(marker)
            ),
            (run_id, name),
        )


def drop_owned(
    admin: psycopg.Connection,
    base: URL,
    name: str,
    marker: str,
    run_id: str,
    expected_server: tuple[object, ...],
) -> None:
    verify_admin(admin, expected_server)
    if not database_exists(admin, name):
        raise OpsSafetyError("Owned database disappeared before cleanup")
    with psycopg.connect(pg_uri(db_url(base, name)), connect_timeout=5) as conn:
        if conn.execute("SELECT current_database()").fetchone()[0] != name:
            raise OpsSafetyError("Cleanup connected to a different database")
        if server_identity(conn) != expected_server:
            raise OpsSafetyError("Cleanup reached a different PostgreSQL server")
        if conn.execute("SELECT to_regclass(%s)", (f"public.{marker}",)).fetchone()[0] is None:
            raise OpsSafetyError("Ownership marker missing; database preserved")
        row = conn.execute(
            sql.SQL("SELECT run_id, db_name FROM {}").format(sql.Identifier(marker))
        ).fetchone()
        if row != (run_id, name):
            raise OpsSafetyError("Ownership marker mismatch; database preserved")
    connections = admin.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (name,)
    ).fetchone()[0]
    if connections:
        raise OpsSafetyError("Other connections remain; database preserved")
    admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def run_checked(args: list[str], *, env: dict[str, str], cwd: Path | None = None) -> None:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, check=False)
    if result.returncode:
        raise OpsSafetyError(f"Command failed with exit {result.returncode}: {Path(args[0]).name}")


def cli_env(base: URL) -> dict[str, str]:
    env = os.environ.copy()
    env["POSTGRES_PASSWORD"] = base.password or ""
    return env


def seed_source(base: URL, source: str, password: str, key: bytes, secret: str) -> None:
    from app.core.security import hash_password

    with psycopg.connect(pg_uri(db_url(base, source))) as conn:
        user_id = uuid.uuid4()
        role_id = uuid.uuid4()
        conn.execute(
            "INSERT INTO users (id, username, email, is_active, is_superuser, email_verified) "
            "VALUES (%s, 'ops_restore_user', 'ops_restore@example.test', true, false, true)",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO password_credentials (id, user_id, password_hash, algorithm) "
            "VALUES (gen_random_uuid(), %s, %s, 'argon2id')",
            (user_id, hash_password(password)),
        )
        conn.execute("INSERT INTO roles (id, name) VALUES (%s, 'user')", (role_id,))
        conn.execute(
            "INSERT INTO user_roles (id, user_id, role_id) VALUES (gen_random_uuid(), %s, %s)",
            (user_id, role_id),
        )
        conn.execute(
            "INSERT INTO totp_credentials (id, user_id, encrypted_secret, is_confirmed, confirmed_at) "
            "VALUES (gen_random_uuid(), %s, %s, true, now())",
            (user_id, Fernet(key).encrypt(secret.encode()).decode()),
        )
        conn.execute(
            "INSERT INTO sessions (id, session_token_hash, user_id, ip_address, expires_at, last_activity_at) "
            "VALUES (gen_random_uuid(), %s, %s, '127.0.0.1', now() + interval '1 hour', now())",
            (uuid.uuid4().hex + uuid.uuid4().hex, user_id),
        )
        conn.execute(
            "INSERT INTO oidc_clients (id, client_id, client_secret_hash, client_name, client_type, is_active) "
            "VALUES (gen_random_uuid(), 'ops_restore_client', %s, 'Restore Client', 'confidential', true)",
            (uuid.uuid4().hex,),
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_backup_restore_and_totp_key_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    base = parse_test_url(os.environ.get("TEST_DATABASE_URL"))
    expected_server = verify_base(base)
    if not shutil.which("pg_dump") or not shutil.which("psql"):
        raise OpsSafetyError(
            "pg_dump and psql must both be available locally for the verified server"
        )

    run_id = uuid.uuid4().hex
    source = f"alxprgs_ops_test_src_{run_id}"
    restore = f"alxprgs_ops_test_dst_{run_id}"
    created: set[str] = set()
    admin_url = db_url(base, "postgres")
    key = Fernet.generate_key()
    wrong_key = Fernet.generate_key()
    password = uuid.uuid4().hex + "Aa1!"
    secret = pyotp.random_base32()
    primary_error: BaseException | None = None
    with tempfile.TemporaryDirectory(prefix="sso_ops_") as tmp:
        with psycopg.connect(pg_uri(admin_url), autocommit=True, connect_timeout=5) as admin:
            try:
                verify_admin(admin, expected_server)
                create_owned(admin, base, source, SOURCE_MARKER, run_id, created, expected_server)
                create_owned(admin, base, restore, RESTORE_MARKER, run_id, created, expected_server)

                source_url = db_url(base, source)
                env = cli_env(base)
                env["DATABASE_URL_SYNC"] = source_url.render_as_string(hide_password=False)
                env["DATABASE_URL"] = env["DATABASE_URL_SYNC"]
                run_checked(
                    [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                    env=env,
                    cwd=BACKEND,
                )
                seed_source(base, source, password, key, secret)
                erased_id = uuid.uuid4()
                with psycopg.connect(pg_uri(source_url)) as conn:
                    conn.execute("INSERT INTO users(id,username,email,is_active,is_superuser,email_verified) VALUES (%s,'erased_subject','erased@example.test',true,false,true)", (erased_id,))
                    conn.execute("INSERT INTO audit_events(id,event_type,user_id,ip_address,user_agent,details) VALUES (gen_random_uuid(),'synthetic_erasure',%s,'192.0.2.1','legacy UA',jsonb_build_object('target_user_id',%s::text,'email','erased@example.test'))", (erased_id, erased_id))

                common = ["--host", base.host, "--port", str(base.port), "--user", base.username]
                run_checked(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "backup_db.py"),
                        "--output-dir",
                        tmp,
                        *common,
                        "--db",
                        source,
                    ],
                    env=env,
                )
                backups = list(Path(tmp).glob("*.sql"))
                assert len(backups) == 1 and backups[0].stat().st_size > 0
                # Erasure AFTER the backup must survive restoration of that backup.
                with psycopg.connect(pg_uri(source_url)) as conn:
                    conn.execute("DELETE FROM users WHERE id=%s", (erased_id,))
                    conn.execute("INSERT INTO deleted_subjects(id,created_at,subject_id,deleted_at) VALUES(gen_random_uuid(),now(),%s,now())", (erased_id,))
                journal = Path(tmp) / "current-erasure-journal.json"
                run_checked([sys.executable, str(ROOT / "scripts" / "export_deletion_journal.py"), str(journal)], env=env)
                run_checked(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "restore_db.py"),
                        str(backups[0]),
                        "--confirm",
                        "--deletion-journal",
                        str(journal),
                        *common,
                        "--db",
                        restore,
                    ],
                    env=env,
                )

                with psycopg.connect(pg_uri(db_url(base, restore))) as conn:
                    assert server_identity(conn) == expected_server
                    assert conn.execute("SELECT count(*) FROM users WHERE id=%s", (erased_id,)).fetchone()[0] == 0
                    assert conn.execute("SELECT user_id,ip_address,user_agent,details FROM audit_events WHERE event_type='synthetic_erasure'").fetchone() == (None,None,None,{})
                    assert (
                        conn.execute(
                            "SELECT count(*) FROM users WHERE username = 'ops_restore_user'"
                        ).fetchone()[0]
                        == 1
                    )
                    assert conn.execute("SELECT count(*) FROM user_roles").fetchone()[0] == 1
                    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
                    assert (
                        conn.execute(
                            "SELECT count(*) FROM oidc_clients WHERE client_id = 'ops_restore_client'"
                        ).fetchone()[0]
                        == 1
                    )
                    assert (
                        conn.execute(
                            "SELECT count(*) FROM totp_credentials WHERE is_confirmed"
                        ).fetchone()[0]
                        == 1
                    )

                # Exercise the restored FastAPI login path, including its TOTP verifier.
                from app.api.deps import get_db
                from app.config import Settings, get_settings
                from app.core import security
                from app.main import app

                settings = Settings(
                    DATABASE_URL=db_url(base, restore).render_as_string(hide_password=False),
                    DATABASE_URL_SYNC=db_url(base, restore).render_as_string(hide_password=False),
                    FEATURE_TOTP_ENABLED=True,
                    TOTP_ENCRYPTION_KEY=key.decode(),
                    ENVIRONMENT="testing",
                )
                engine = create_async_engine(settings.DATABASE_URL)
                sessions = async_sessionmaker(engine, expire_on_commit=False)

                async def restored_db():
                    async with sessions() as session:
                        yield session

                app.dependency_overrides[get_db] = restored_db
                app.dependency_overrides[get_settings] = lambda: settings
                monkeypatch.setattr(security.settings, "TOTP_ENCRYPTION_KEY", wrong_key.decode())
                try:
                    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as client:
                        login = await client.post(
                            "/api/v1/auth/login",
                            json={"username": "ops_restore_user", "password": password},
                        )
                        assert login.status_code == 200 and login.json()["mfa_required"] is True
                        token = login.json()["mfa_token"]
                        rejected = await client.post(
                            "/api/v1/mfa/totp/verify",
                            json={"mfa_token": token, "code": pyotp.TOTP(secret).now()},
                        )
                        assert rejected.status_code != 200
                        assert not client.cookies
                        monkeypatch.setattr(security.settings, "TOTP_ENCRYPTION_KEY", key.decode())
                        retry_login = await client.post(
                            "/api/v1/auth/login",
                            json={"username": "ops_restore_user", "password": password},
                        )
                        assert retry_login.status_code == 200
                        assert retry_login.json()["mfa_required"] is True
                        accepted = await client.post(
                            "/api/v1/mfa/totp/verify",
                            json={
                                "mfa_token": retry_login.json()["mfa_token"],
                                "code": pyotp.TOTP(secret).now(),
                            },
                        )
                        assert accepted.status_code == 200
                        me = await client.get("/api/v1/auth/me")
                        assert me.status_code == 200 and me.json()["username"] == "ops_restore_user"
                finally:
                    app.dependency_overrides.pop(get_db, None)
                    app.dependency_overrides.pop(get_settings, None)
                    await engine.dispose()
            except BaseException as exc:
                primary_error = exc
            cleanup_errors: list[BaseException] = []
            for name, marker in ((restore, RESTORE_MARKER), (source, SOURCE_MARKER)):
                if name in created:
                    try:
                        drop_owned(admin, base, name, marker, run_id, expected_server)
                    except BaseException as exc:
                        cleanup_errors.append(exc)
            if primary_error or cleanup_errors:
                raise ExceptionGroup(
                    "Backup/restore or owned cleanup failed",
                    [e for e in [primary_error, *cleanup_errors] if e is not None],
                )
