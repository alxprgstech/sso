import json
import logging
import uuid

import pytest
from app.core.diagnostics import correlation, diagnostic, request_id
from app.logging_config import SafeFormatter
from app.services.audit_service import scrub_detail


def test_allowlisted_operations_and_correlations_do_not_reflect_payload(caplog):
    marker = "private-email@example.test bearer-password-marker"
    valid = str(uuid.uuid4())
    assert correlation(valid) == valid
    assert correlation(marker) != marker
    token = request_id.set(valid)
    try:
        with caplog.at_level(logging.INFO):
            diagnostic("email_delivery", "smtp_connection_failed", failed=True)
            diagnostic("database_readiness", "database_unavailable", failed=True)
            diagnostic("privacy_maintenance", "database_unavailable", failed=True)
            diagnostic(marker, marker, failed=True)
        records = [json.loads(SafeFormatter().format(record)) for record in caplog.records]
        assert {item["operation"] for item in records} == {
            "email_delivery",
            "database_readiness",
            "privacy_maintenance",
        }
        assert all(item["request_id"] == valid for item in records)
        assert marker not in json.dumps(records)
    finally:
        request_id.reset(token)
    assert scrub_detail({"nested": {"password": marker, "email": marker}, "value": marker}) == {
        "nested": {"password": "[REDACTED]", "email": "[REDACTED]"},
        "value": "[REDACTED]",
    }


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_http_request_id_is_validated_and_linked_to_audit(pg_session, pg_client):
    from app.cli.bootstrap_admin import execute_bootstrap
    from app.models.audit import AuditEvent
    from sqlalchemy import select

    password = "CorrelationRegression2026!"
    assert (
        await execute_bootstrap(
            pg_session, "correlation_user", "correlation@example.test", password, "closed"
        )
    )[0] == 0
    identity = str(uuid.uuid4())
    response = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "correlation_user", "password": password},
        headers={"X-Request-ID": identity},
    )
    assert response.status_code == 200 and response.headers["X-Request-ID"] == identity
    event = await pg_session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "login_success")
    )
    assert event.details["request_id"] == identity
    tainted = "authorization-private-token"
    bad = await pg_client.get("/health/live", headers={"X-Request-ID": tainted})
    assert bad.headers["X-Request-ID"] != tainted
    uuid.UUID(bad.headers["X-Request-ID"])
