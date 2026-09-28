"""Mark an empty dedicated PostgreSQL test database before destructive tests."""

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from psycopg import sql

from tests.db_guard import EXPECTED_ENVIRONMENT, MARKER_ID
from tests.test_ops_backup_restore_totp import OpsSafetyError, parse_test_url, pg_uri


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-fresh", action="store_true")
    args = parser.parse_args(argv)
    url = parse_test_url(os.environ.get("TEST_DATABASE_URL"))
    ci_profile = (
        os.environ.get("CI") == "true"
        and os.environ.get("GITHUB_ACTIONS") == "true"
        and (url.host, url.port, url.username, url.database)
        == ("localhost", 5432, "sso_user", "alxprgs_sso_test")
    )
    local_profile = args.local_fresh and (
        url.host,
        url.port,
        url.username,
        url.database,
    ) in {
        ("localhost", 5433, "sso_test_user", "alxprgs_sso_test"),
        ("127.0.0.1", 5433, "sso_test_user", "alxprgs_sso_test"),
    }
    if not (ci_profile or local_profile):
        raise OpsSafetyError("Marker provisioning requires an exact dedicated local test service")
    with psycopg.connect(pg_uri(url), connect_timeout=5) as conn:
        if conn.execute("SELECT current_database()").fetchone()[0] != url.database:
            raise OpsSafetyError("Connected database differs from TEST_DATABASE_URL")
        if conn.execute("SELECT to_regclass('public.test_database_marker')").fetchone()[0]:
            raise OpsSafetyError("Database already has a marker; refusing to reinitialize it")
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        if (
            not {"users", "sessions", "oidc_clients", "system_configuration", "alembic_version"}
            <= tables
        ):
            raise OpsSafetyError("Expected migrated schema is missing; refusing marker creation")
        config = conn.execute(
            "SELECT bootstrap_completed, registration_mode FROM public.system_configuration WHERE id = 1"
        ).fetchone()
        if config != (False, "closed"):
            raise OpsSafetyError("Fresh system configuration is missing; refusing marker creation")
        for table in tables - {"alembic_version", "system_configuration"}:
            query = sql.SQL("SELECT EXISTS (SELECT 1 FROM public.{} LIMIT 1)").format(
                sql.Identifier(table)
            )
            if conn.execute(query).fetchone()[0]:
                raise OpsSafetyError("Database is not empty; refusing to mark it as fresh")
        conn.execute(
            "CREATE TABLE public.test_database_marker ("
            "marker_id varchar(64) PRIMARY KEY, environment varchar(64) NOT NULL, "
            "is_safe_to_truncate boolean NOT NULL, created_at timestamptz DEFAULT CURRENT_TIMESTAMP, "
            "updated_at timestamptz DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO public.test_database_marker "
            "(marker_id, environment, is_safe_to_truncate) VALUES (%s, %s, true)",
            (MARKER_ID, EXPECTED_ENVIRONMENT),
        )
    print("Fresh dedicated test database marker created")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OpsSafetyError, psycopg.Error) as exc:
        print(f"Test database marker rejected: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc
