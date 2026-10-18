import importlib.util
import uuid
from pathlib import Path

import pytest
from app.models.mfa import WebAuthnCredential
from app.models.user import User
from sqlalchemy import select

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]


async def test_canonical_migration_preserves_credentials_and_refuses_collisions(
    pg_session, monkeypatch
):
    file = (
        Path(__file__).resolve().parents[2]
        / "backend/alembic/versions/0012_canonical_credential_ids.py"
    )
    spec = importlib.util.spec_from_file_location("credential_migration", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    user = User(username="canonical_owner", email="canonical@example.test", is_active=True)
    pg_session.add(user)
    await pg_session.flush()
    first = WebAuthnCredential(
        id=uuid.uuid4(), user_id=user.id, credential_id="YWJj==", public_key="0123", sign_count=7
    )
    second = WebAuthnCredential(
        id=uuid.uuid4(), user_id=user.id, credential_id="YWJj", public_key="4567", sign_count=9
    )
    pg_session.add_all([first, second])
    await pg_session.commit()
    first_id, second_id = first.id, second.id

    def upgrade(session):
        monkeypatch.setattr(module.op, "get_bind", lambda: session.connection())
        module.upgrade()

    with pytest.raises(RuntimeError, match="canonical collision"):
        await pg_session.run_sync(upgrade)
    await pg_session.rollback()
    rows = (
        await pg_session.scalars(
            select(WebAuthnCredential).order_by(WebAuthnCredential.credential_id)
        )
    ).all()
    assert len(rows) == 2 and {row.credential_id for row in rows} == {"YWJj", "YWJj=="}
    await pg_session.delete(await pg_session.get(WebAuthnCredential, second_id))
    await pg_session.flush()
    await pg_session.run_sync(upgrade)
    await pg_session.commit()
    row = await pg_session.get(WebAuthnCredential, first_id, populate_existing=True)
    assert row.credential_id == "YWJj" and row.public_key == "0123" and row.sign_count == 7
