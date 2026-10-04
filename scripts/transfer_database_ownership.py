"""Offline, database-scoped handoff of application objects to the migration role."""

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def require_offline_owner_and_roles(conn, expected_database: str, expected_owner: str) -> None:
    database, login = conn.execute("SELECT current_database(), current_user").fetchone()
    if database != expected_database or login != expected_owner:
        raise ValueError("Database/owner confirmation does not match the connection")
    if conn.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"
    ).fetchone()[0]:
        raise ValueError("Database must be offline with no other connections")
    conn.execute("SELECT pg_advisory_xact_lock(741239813)")
    require_dedicated_roles(conn)


def privileged_role_exists(roles) -> bool:
    for role in roles:
        if any(role[1:]):
            return True
    return False


def require_dedicated_roles(conn) -> None:
    roles = conn.execute(
        "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname IN ('sso_runtime','sso_migrator')"
    ).fetchall()
    if len(roles) != 2 or privileged_role_exists(roles):
        raise ValueError("Both dedicated least-privilege roles must already exist")
    if conn.execute(
        "SELECT count(*) FROM pg_auth_members WHERE member IN (SELECT oid FROM pg_roles WHERE rolname IN ('sso_runtime','sso_migrator'))"
    ).fetchone()[0]:
        raise ValueError("Dedicated roles must not inherit other roles")


def has_migration_version(tables) -> bool:
    return any(name == "alembic_version" for name, _ in tables)


def application_tables(conn, expected_owner: str):
    from app.migration_metadata import target_metadata

    names = sorted({*target_metadata.tables, "alembic_version"})
    tables = conn.execute(
        "SELECT c.relname,pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname=ANY(%s) ORDER BY c.relname",
        (names,),
    ).fetchall()
    if not tables or not has_migration_version(tables):
        raise ValueError("Selected database has no migrated application schema")
    if any(owner != expected_owner for _, owner in tables):
        raise ValueError("Application objects have an unexpected owner; refusing partial handoff")
    return tables


def attached_sequences(conn, tables):
    # Only sequences attached to these exact application tables are transferred.
    sequences = conn.execute(
        "SELECT DISTINCT s.relname FROM pg_class s JOIN pg_namespace n ON n.oid=s.relnamespace JOIN pg_depend d ON d.objid=s.oid JOIN pg_class t ON t.oid=d.refobjid WHERE n.nspname='public' AND s.relkind='S' AND t.relname=ANY(%s) AND d.deptype IN ('a','i')",
        ([name for name, _ in tables],),
    ).fetchall()
    return sequences


def handoff_objects(conn, tables, sequences) -> None:
    for name, _ in tables:
        conn.execute(
            sql.SQL("ALTER TABLE public.{} OWNER TO sso_migrator").format(sql.Identifier(name))
        )
    for (name,) in sequences:
        conn.execute(
            sql.SQL("ALTER SEQUENCE public.{} OWNER TO sso_migrator").format(sql.Identifier(name))
        )


def grant_application_access(conn, tables, sequences) -> None:
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    conn.execute("ALTER SCHEMA public OWNER TO sso_migrator")
    conn.execute("GRANT USAGE ON SCHEMA public TO sso_runtime")
    for name, _ in tables:
        conn.execute(
            sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON public.{} TO sso_runtime").format(
                sql.Identifier(name)
            )
        )
    for (name,) in sequences:
        conn.execute(
            sql.SQL("GRANT USAGE,SELECT ON SEQUENCE public.{} TO sso_runtime").format(
                sql.Identifier(name)
            )
        )
    conn.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE sso_migrator IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO sso_runtime"
    )
    conn.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE sso_migrator IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO sso_runtime"
    )


def transfer_application_ownership(conn, expected_database: str, expected_owner: str) -> int:
    require_offline_owner_and_roles(conn, expected_database, expected_owner)
    tables = application_tables(conn, expected_owner)
    sequences = attached_sequences(conn, tables)
    handoff_objects(conn, tables, sequences)
    grant_application_access(conn, tables, sequences)
    return len(tables)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-owner", required=True)
    parser.add_argument("--offline-maintenance", action="store_true", required=True)
    parser.add_argument("--confirm", action="store_true", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.config import get_settings

    try:
        url = make_url(get_settings().DATABASE_URL_SYNC).set(drivername="postgresql")
        with psycopg.connect(url.render_as_string(hide_password=False), connect_timeout=5) as conn:
            count = transfer_application_ownership(
                conn, args.expected_database, args.expected_owner
            )
    except Exception:
        print(
            "Ownership handoff failed; transaction rolled back; sensitive details withheld.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Transferred {count} application tables. Configure migrator/runtime DSNs before restart."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
