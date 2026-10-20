"""SSO-SEC-0004: twenty anonymous failures yield a counted batch, not twenty inserts."""

import pytest
from app.models.audit import AuditEvent
from app.services import denied_audit
from sqlalchemy import select


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_anonymous_denials_aggregate_without_losing_counts(
    pg_client, pg_session, monkeypatch
):
    buffer = denied_audit.DeniedAuditBuffer()
    monkeypatch.setattr(denied_audit, "anonymous_denials", buffer)
    for _ in range(20):
        assert (await pg_client.get("/api/v1/auth/me")).status_code == 401
    assert not await pg_session.scalar(select(AuditEvent))
    await buffer.flush(pg_session)
    rows = (await pg_session.scalars(select(AuditEvent))).all()
    assert len(rows) == 1
    assert rows[0].event_type == "action_denied"
    assert rows[0].user_id is None
    assert rows[0].details["count"] == 20
    assert rows[0].details["route"] == "get_me"
    assert rows[0].details["reason"] == "authentication_required"
    assert rows[0].details["aggregated"] is True
    assert rows[0].ip_address is None
    await buffer.flush(pg_session)
    assert len((await pg_session.scalars(select(AuditEvent))).all()) == 1
