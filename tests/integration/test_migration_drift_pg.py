"""Compare the migrated real PostgreSQL schema with every application table/index."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.migration_metadata import include_object, target_metadata


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_head_has_no_schema_drift(pg_session):
    connection = await pg_session.connection()

    def compare(sync_connection):
        context = MigrationContext.configure(
            sync_connection, opts={"include_object": include_object}
        )
        return compare_metadata(context, target_metadata)

    assert await connection.run_sync(compare) == []
