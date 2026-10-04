"""Fail closed if the production application can act as a database owner."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SCHEMA_REVISION = "0010_registration_session"


async def require_runtime_database_role(db: AsyncSession) -> None:
    unsafe = await db.scalar(
        text("""
        SELECT EXISTS (
          SELECT 1 FROM pg_roles r
          WHERE pg_has_role(current_user, r.oid, 'MEMBER')
            AND (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
                 OR r.rolreplication OR r.rolbypassrls)
        ) OR has_schema_privilege(current_user, 'public', 'CREATE')
          OR EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
              AND pg_has_role(current_user, c.relowner, 'MEMBER')
          )
    """)
    )
    if unsafe:
        raise RuntimeError("Production database role has forbidden ownership or privileges")
    revision = await db.scalar(text("SELECT version_num FROM alembic_version"))
    if revision != SCHEMA_REVISION:
        raise RuntimeError("Database migration is required before production startup")
