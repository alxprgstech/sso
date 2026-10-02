"""Actual PostgreSQL spans. Uses the mandatory dedicated database safety fixture."""

import json

import httpx
import pytest
import sentry_sdk
from app.config import Settings
from app.main import app
from app.telemetry import TelemetryFastAPI, initialize_sentry, register_routes
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_sentry import CANARIES, DSN, MemoryTransport


@pytest.mark.asyncio
async def test_postgresql_timing_survives_without_sql_or_parameters(pg_engine):
    transport = MemoryTransport()
    register_routes(app)
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="testing",
        SENTRY_ENABLED=True,
        SENTRY_DSN=DSN,
        SENTRY_TRACES_SAMPLE_RATE=1,
    )
    assert initialize_sentry(settings, transport=transport)
    try:
        with sentry_sdk.start_transaction(
            name="/api/v1/auth/login", op="http.server", sampled=True
        ):
            async with pg_engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT CAST(:secret AS TEXT)"), {"secret": CANARIES[0]}
                    )
                    == CANARIES[0]
                )
        transactions = []
        for envelope in transport.envelopes:
            lines = envelope.splitlines()
            for index, line in enumerate(lines):
                if index + 1 < len(lines) and json.loads(line).get("type") == "transaction":
                    transactions.append(json.loads(lines[index + 1]))
                    break
        assert transactions
        spans = transactions[0]["spans"]
        assert any(span["op"].startswith("db") for span in spans)
        assert all(span["timestamp"] >= span["start_timestamp"] for span in spans)
        assert "SELECT" not in "".join(transport.envelopes)
        assert all(secret not in "".join(transport.envelopes) for secret in CANARIES)
    finally:
        sentry_sdk.get_client().close(timeout=0)
        sentry_sdk.get_global_scope().set_client(None)


@pytest.mark.asyncio
async def test_actual_driver_error_keeps_fail_closed_503_and_hides_chain(pg_engine):
    test_app = TelemetryFastAPI()
    transport = MemoryTransport()

    @test_app.get("/api/database-failure")
    async def fail_closed():
        try:
            async with pg_engine.connect() as connection:
                await connection.execute(
                    text("SELECT CAST(:secret AS INTEGER)"), {"secret": CANARIES[0]}
                )
        except DBAPIError as error:
            raise HTTPException(503, "Infrastructure unavailable") from error
        raise AssertionError("PostgreSQL accepted an invalid integer")

    register_routes(test_app)
    assert initialize_sentry(
        Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            SENTRY_ENABLED=True,
            SENTRY_DSN=DSN,
            SENTRY_TRACES_SAMPLE_RATE=1,
        ),
        transport=transport,
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=test_app), base_url="https://sso.invalid"
        ) as client:
            response = await client.get("/api/database-failure")
        assert response.status_code == 503
        events = [
            body
            for body in transport.envelopes
            if '"type":"event"' in body or '"type": "event"' in body
        ]
        assert len(events) == 1
        assert "DataError" in events[0] and "HTTPException" in events[0]
        assert "SELECT" not in "".join(transport.envelopes)
        assert all(secret not in "".join(transport.envelopes) for secret in CANARIES)
    finally:
        sentry_sdk.get_client().close(timeout=0)
        sentry_sdk.get_global_scope().set_client(None)
        register_routes(app)
