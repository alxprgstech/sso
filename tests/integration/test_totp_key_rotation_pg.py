"""F-20 transactional drill on the guarded PostgreSQL fixture, never SQLite."""

import uuid

import pytest
from app.models.mfa import TOTPCredential
from app.models.user import User
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from scripts.migrate_totp_key import migrate


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_totp_key_migration_and_failed_batch_leave_consistent_ciphertext(pg_session):
    old, new = Fernet.generate_key(), Fernet.generate_key()
    users = [
        User(username=f"rotation-{uuid.uuid4()}", email=f"{uuid.uuid4()}@example.test")
        for _ in range(2)
    ]
    pg_session.add_all(users)
    await pg_session.flush()
    originals = [Fernet(old).encrypt(f"SYNTHETIC-{index}".encode()).decode() for index in range(2)]
    credentials = [
        TOTPCredential(user_id=user.id, encrypted_secret=value, is_confirmed=True)
        for user, value in zip(users, originals, strict=True)
    ]
    pg_session.add_all(credentials)
    await pg_session.commit()
    count = await pg_session.run_sync(lambda session: migrate(session, old, new))
    assert count == 2
    await pg_session.commit()
    rows = list(
        (
            await pg_session.execute(select(TOTPCredential).order_by(TOTPCredential.user_id))
        ).scalars()
    )
    assert sorted(Fernet(new).decrypt(row.encrypted_secret.encode()).decode() for row in rows) == [
        "SYNTHETIC-0",
        "SYNTHETIC-1",
    ]
    valid_after_rotation = rows[0].encrypted_secret
    rows[1].encrypted_secret = "corrupted-ciphertext"
    await pg_session.commit()
    with pytest.raises(InvalidToken):
        await pg_session.run_sync(lambda session: migrate(session, new, old))
    await pg_session.rollback()
    await pg_session.refresh(rows[0])
    assert rows[0].encrypted_secret == valid_after_rotation
    assert Fernet(new).decrypt(rows[0].encrypted_secret.encode()).startswith(b"SYNTHETIC-")
