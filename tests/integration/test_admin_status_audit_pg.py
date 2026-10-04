import csv
import io
import json
import secrets

import httpx
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.models.audit import AuditEvent
from app.models.user import Role, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.privacy import accept_current_documents
from tests.helpers.reauthentication import authorized_request


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_status_counts_and_audit_export_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    password = secrets.token_urlsafe(24)
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="status_admin",
        email="status_admin@example.test",
        password=password,
        registration_mode="closed",
    )
    assert code == 0
    admin_role = (await pg_session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    pg_session.add_all(
        [
            User(
                username="role_admin",
                email="role_admin@example.test",
                is_active=True,
                roles=[admin_role],
            ),
            User(
                username="both_admin",
                email="both_admin@example.test",
                is_active=True,
                is_superuser=True,
                roles=[admin_role],
            ),
            User(
                username="inactive_admin",
                email="inactive_admin@example.test",
                is_active=False,
                is_superuser=True,
            ),
            User(username="regular_user", email="regular_user@example.test", is_active=True),
        ]
    )
    pg_session.add_all(
        [
            AuditEvent(
                event_type="target_event",
                ip_address="203.0.113.5",
                details={"index": i, "nested": {"ok": True}},
            )
            for i in range(55)
        ]
        + [AuditEvent(event_type="other_event", ip_address="192.0.2.7", details={"index": 999})]
    )
    await pg_session.commit()

    denied = await pg_client.get("/api/v1/admin/audit/export?format=jsonl")
    assert denied.status_code == 401

    login = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "status_admin", "password": password},
    )
    await accept_current_documents(pg_client, login)
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    status = await pg_client.get("/api/v1/admin/system/status")
    assert status.status_code == 200
    assert status.json()["total_users"] == 5
    assert status.json()["total_active_admins"] == 3

    changed = await authorized_request(
        pg_client,
        "POST",
        "/api/v1/admin/system/registration-mode",
        password=password,
        headers={"X-CSRF-Token": csrf},
        json_body={"mode": "open", "current_admin_password": password},
    )
    assert changed.status_code == 200
    assert changed.json()["total_users"] == 5
    assert changed.json()["total_active_admins"] == 3

    first = await pg_client.get("/api/v1/admin/audit", params={"q": "target", "limit": 50})
    second = await pg_client.get("/api/v1/admin/audit", params={"q": "target", "offset": 50})
    assert first.status_code == second.status_code == 200
    assert len(first.json()) == 50
    assert len(second.json()) == 5

    jsonl = await pg_client.get(
        "/api/v1/admin/audit/export", params={"format": "jsonl", "q": "target"}
    )
    assert jsonl.status_code == 200
    assert jsonl.headers["cache-control"] == "no-store"
    json_rows = [json.loads(line) for line in jsonl.text.splitlines()]
    assert len(json_rows) == 55
    assert all(row["details"]["nested"]["ok"] is True for row in json_rows)

    csv_response = await pg_client.get(
        "/api/v1/admin/audit/export", params={"format": "csv", "q": "203.0.113"}
    )
    assert csv_response.status_code == 200
    csv_rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert len(csv_rows) == 55
    assert all(json.loads(row["details"])["nested"]["ok"] is True for row in csv_rows)

    bad_format = await pg_client.get("/api/v1/admin/audit/export", params={"format": "html"})
    assert bad_format.status_code == 422
