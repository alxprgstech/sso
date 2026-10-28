"""REG-02 without double data entry: the one-use proof is the confirmation.

The registration-mode change used to require the administrator password twice:
once in the form body (legacy REG-02 field) and again in the reauthentication
dialog, plus the configured MFA factor. The action-bound proof already proves a
fresh password plus MFA for this exact body, so new clients omit the body field
while older clients keep working.
"""

import json
import secrets

import httpx
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.services.reauthentication_service import payload_digest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.mfa import login_admin_with_mfa_direct
from tests.helpers.reauthentication import MutationRequest, RequestAuthorization, authorized_request

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]

PATH = "/api/v1/admin/system/registration-mode"


async def _mode(pg_session: AsyncSession) -> str:
    value = await pg_session.execute(
        text("SELECT registration_mode FROM system_configuration WHERE id = 1")
    )
    return value.scalar_one()


async def _start(client, headers, body: dict, password: str) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/reauthentication",
        headers=headers,
        json={
            "current_password": password,
            "action": f"POST {PATH}",
            "payload_hash": payload_digest(json.dumps(body).encode()),
        },
    )


async def test_mode_change_accepts_one_proof_and_legacy_body_password(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    password = secrets.token_urlsafe(24)
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="mode_contract_admin",
        email="mode_contract_admin@example.test",
        password=password,
        registration_mode="closed",
    )
    assert code == 0
    session = await login_admin_with_mfa_direct(
        pg_session, pg_client, "mode_contract_admin", password
    )

    # Without the action-bound proof nothing changes.
    unauthorized = await pg_client.post(PATH, headers=session.headers, json={"mode": "open"})
    assert unauthorized.status_code == 401
    assert await _mode(pg_session) == "closed"

    # New client: no second password in the body, proof carries freshness + MFA.
    opened = await authorized_request(
        pg_client,
        MutationRequest("POST", PATH, json_body={"mode": "open"}),
        RequestAuthorization(password, session.headers, factor=session.factor),
    )
    assert opened.status_code == 200, opened.json()
    assert opened.json()["registration_mode"] == "open"
    assert await _mode(pg_session) == "open"

    # Older clients may still send the legacy body password; it is verified.
    closed = await authorized_request(
        pg_client,
        MutationRequest(
            "POST", PATH, json_body={"mode": "closed", "current_admin_password": password}
        ),
        RequestAuthorization(password, session.headers, factor=session.factor),
    )
    assert closed.status_code == 200, closed.json()
    assert await _mode(pg_session) == "closed"

    # A proof for one body cannot authorise a different body.
    issued = await _start(pg_client, session.headers, {"mode": "open"}, password)
    assert issued.status_code == 200, issued.json()
    data = issued.json()
    if data["factor_required"]:
        confirmed = await pg_client.post(
            "/api/v1/auth/reauthentication/factor",
            headers=session.headers,
            json={"authorization": data["authorization"], **session.factor(data)},
        )
        assert confirmed.status_code == 200, confirmed.json()
        data = confirmed.json()
    swapped = await pg_client.post(
        PATH,
        headers={**session.headers, "X-Reauthentication": data["authorization"]},
        json={"mode": "closed"},
    )
    assert swapped.status_code == 401
    assert await _mode(pg_session) == "closed"

    # A wrong legacy body password is still refused even with a valid proof.
    wrong_password = secrets.token_urlsafe(12)
    wrong = await authorized_request(
        pg_client,
        MutationRequest(
            "POST", PATH, json_body={"mode": "open", "current_admin_password": wrong_password}
        ),
        RequestAuthorization(password, session.headers, factor=session.factor),
    )
    assert wrong.status_code == 401
    assert await _mode(pg_session) == "closed"
