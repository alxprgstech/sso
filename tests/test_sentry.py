"""Real SDK envelopes, synthetic secrets and ASGI negative capture checks."""

import asyncio
import json
import logging
import socket
import threading

import httpx
import pytest
import sentry_sdk
from app.config import Settings
from app.logging_config import SafeFormatter
from app.main import app as production_app
from app.telemetry import (
    TelemetryFastAPI,
    initialize_sentry,
    register_routes,
    sanitize_event,
    traces_sampler,
)
from fastapi import HTTPException
from sentry_sdk.consts import DEFAULT_OPTIONS
from sentry_sdk.transport import HttpTransport, Transport
from urllib3.response import HTTPResponse

DSN = "https://public@o1.ingest.de.sentry.io/1"
CANARIES = [
    f"canary-{category}-never-export"
    for category in (
        "password",
        "otp",
        "pkce",
        "jwt",
        "refresh",
        "cookie",
        "csrf",
        "totp",
        "recovery",
        "webauthn",
        "aws",
        "smtp",
        "sentry-token",
        "email@example.invalid",
        "phone",
    )
]


class MemoryTransport(Transport):
    def __init__(self):
        super().__init__()
        self.envelopes = []

    def capture_envelope(self, envelope):
        # Test the actual serialized envelope, not only hook output.
        self.envelopes.append(envelope.serialize().decode("utf-8"))


def test_envelope_header_and_attachments_are_independently_filtered(telemetry_app):
    _, transport = telemetry_app
    with sentry_sdk.start_transaction(name=CANARIES[0], op="http.server"):
        with sentry_sdk.new_scope() as scope:
            scope.add_attachment(bytes=CANARIES[1].encode(), filename=CANARIES[2])
            sentry_sdk.capture_exception(RuntimeError(CANARIES[3]))
    assert len(transport.envelopes) == 1
    assert all(secret not in transport.envelopes[0] for secret in CANARIES)
    header = json.loads(transport.envelopes[0].splitlines()[0])
    assert "trace" not in header
    assert "attachment" not in transport.envelopes[0]


@pytest.fixture
def telemetry_app():
    transport = MemoryTransport()
    test_app = TelemetryFastAPI()

    @test_app.get("/api/unexpected")
    async def unexpected():
        try:
            raise ValueError(" ".join(CANARIES))
        except ValueError as error:
            raise RuntimeError(" ".join(CANARIES)) from error

    @test_app.get("/api/status/{code}")
    async def status_error(code: int):
        raise HTTPException(code, " ".join(CANARIES))

    @test_app.get("/health/ready")
    async def readiness():
        raise HTTPException(503, " ".join(CANARIES))

    @test_app.get("/api/v1/auth/telemetry-config")
    async def config():
        return {"ok": True}

    register_routes(test_app)
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="testing",
        SENTRY_ENABLED=True,
        SENTRY_DSN=DSN,
        SENTRY_TRACES_SAMPLE_RATE=1,
    )
    assert initialize_sentry(settings, transport=transport)
    yield test_app, transport
    sentry_sdk.get_client().close(timeout=0)
    sentry_sdk.get_global_scope().set_client(None)
    register_routes(production_app)


@pytest.mark.asyncio
async def test_unhandled_single_capture_and_whole_exception_chain(telemetry_app):
    app, transport = telemetry_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://sso.invalid",
    ) as client:
        response = await client.get(
            "/api/unexpected?token=" + CANARIES[0],
            headers={
                "Cookie": CANARIES[1],
                "Authorization": CANARIES[2],
                "X-Request-ID": CANARIES[3],
            },
        )
    assert response.status_code == 500
    events = [
        value
        for value in transport.envelopes
        if '"type":"event"' in value or '"type": "event"' in value
    ]
    assert len(events) == 1
    assert all(secret not in "".join(transport.envelopes) for secret in CANARIES)
    assert "RuntimeError" in events[0] and "ValueError" in events[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 422, 429, 503])
async def test_expected_http_failures_and_single_503(telemetry_app, code):
    app, transport = telemetry_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://sso.invalid"
    ) as client:
        assert (await client.get(f"/api/status/{code}")).status_code == code
    events = [
        value
        for value in transport.envelopes
        if '"type":"event"' in value or '"type": "event"' in value
    ]
    assert len(events) == (1 if code == 503 else 0)
    assert all(secret not in "".join(transport.envelopes) for secret in CANARIES)


@pytest.mark.asyncio
async def test_excluded_routes_even_with_sampled_parent(telemetry_app):
    app, transport = telemetry_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://sso.invalid"
    ) as client:
        for path in ("/health/ready", "/api/v1/auth/telemetry-config", "/scanner-unknown"):
            await client.get(
                path,
                headers={
                    "sentry-trace": "a" * 32 + "-" + "b" * 16 + "-1",
                    "baggage": "sentry-org_id=1,sentry-user_id=" + CANARIES[0],
                },
            )
    assert transport.envelopes == []


def test_disabled_and_ordinary_testing_have_no_network_transport():
    for values in (
        {},
        {"SENTRY_ENABLED": True},
        {"SENTRY_ENABLED": True, "SENTRY_DSN": DSN, "ENVIRONMENT": "testing"},
    ):
        assert not initialize_sentry(Settings(_env_file=None, **values))


def test_sdk_initialization_failure_does_not_abort(monkeypatch):
    def broken(**kwargs):
        raise OSError(CANARIES[0])

    monkeypatch.setattr(sentry_sdk, "init", broken)
    assert not initialize_sentry(Settings(_env_file=None, SENTRY_ENABLED=True, SENTRY_DSN=DSN))


def test_sampler_disabled_exclusions_and_parent():
    register_routes(production_app)
    for path, method in (
        ("/health/live", "GET"),
        ("/unknown", "GET"),
        ("/api/v1/auth/login", "OPTIONS"),
    ):
        assert (
            traces_sampler(
                {"asgi_scope": {"path": path, "method": method}, "parent_sampled": True}, 1
            )
            == 0
        )
    context = {
        "asgi_scope": {"path": "/api/v1/auth/login", "method": "POST"},
        "parent_sampled": True,
    }
    assert traces_sampler(context, 0) == 0
    assert traces_sampler(context, 0.01) == 1


def test_allowlist_drops_arbitrary_nested_payloads_and_spans():
    event = {
        "type": "transaction",
        "transaction": "/api/v1/auth/login",
        "extra": {"nested": CANARIES},
        "user": {"id": CANARIES[0]},
        "contexts": {
            "trace": {"trace_id": "a" * 32, "span_id": "b" * 16, "data": {"sql": CANARIES}}
        },
        "spans": [
            {
                "op": "db",
                "description": "SELECT " + CANARIES[0],
                "data": {"db.query.text": CANARIES, "db.system": "postgresql"},
            }
        ],
    }
    clean = sanitize_event(event, {})
    assert clean and clean["spans"][0]["data"] == {"db.system": "postgresql"}
    assert all(secret not in json.dumps(clean) for secret in CANARIES)


def test_malformed_reserved_fields_cannot_bypass_allowlist():
    clean = sanitize_event(
        {
            "timestamp": CANARIES[0],
            "exception": {
                "values": [
                    {
                        "type": "CanaryPasswordSecret",
                        "stacktrace": {
                            "frames": [
                                {"filename": "app/CanaryPasswordSecret.py", "lineno": CANARIES[0]}
                            ]
                        },
                    }
                ]
            },
        },
        {},
    )
    assert clean
    assert "CanaryPasswordSecret" not in json.dumps(clean)
    assert CANARIES[0] not in json.dumps(clean)


def test_baggage_filter_runs_before_sdk_continuation():
    observed = []

    async def inner(scope, receive, send):
        observed.extend(scope["headers"])

    from app.telemetry import TraceHeaderFilter

    asyncio.run(
        TraceHeaderFilter(inner)(
            {
                "type": "http",
                "headers": [
                    (
                        b"baggage",
                        b"sentry-org_id=1,sentry-trace_id="
                        + b"a" * 32
                        + b",sentry-user_id=secret,third-party=secret",
                    )
                ],
            },
            None,
            None,
        )
    )
    assert observed == [(b"baggage", b"sentry-org_id=1,sentry-trace_id=" + b"a" * 32)]


def test_real_transaction_preserves_sdk_serialized_span_timings(telemetry_app):
    _, transport = telemetry_app
    with sentry_sdk.start_transaction(name="/api/unexpected", op="http.server", sampled=True):
        with sentry_sdk.start_span(op="db", name="SELECT " + CANARIES[0]):
            pass
    payload = json.loads(transport.envelopes[-1].splitlines()[2])
    assert payload["spans"][0]["start_timestamp"] <= payload["spans"][0]["timestamp"]
    assert CANARIES[0] not in transport.envelopes[-1]


def test_logging_does_not_export_queries_sql_or_exception_values():
    formatter = SafeFormatter()
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        1,
        "%s",
        (CANARIES[0], "GET", "/api/v1/auth/login?secret=" + CANARIES[1], "1.1", 200),
        None,
    )
    value = formatter.format(record)
    assert "/api/v1/auth/login" in value and all(secret not in value for secret in CANARIES)
    secret_kind = type(CANARIES[0], (RuntimeError,), {})
    malformed = logging.LogRecord(
        "app." + CANARIES[1],
        logging.ERROR,
        "",
        1,
        CANARIES[2],
        (),
        (secret_kind, secret_kind(CANARIES[3]), None),
    )
    assert all(secret not in formatter.format(malformed) for secret in CANARIES)
    record.args = (CANARIES[0], "GET", "//[" + CANARIES[1], "1.1", 200)
    assert all(secret not in formatter.format(record) for secret in CANARIES)
    for name in ("app.mail", "sqlalchemy.engine.Engine", "uvicorn.error"):
        record = logging.LogRecord(
            name,
            logging.ERROR,
            "",
            1,
            " ".join(CANARIES),
            (),
            (ValueError, ValueError(CANARIES[0]), None),
        )
        assert all(secret not in formatter.format(record) for secret in CANARIES)


@pytest.mark.parametrize("value", [-1, 1.1, float("nan"), float("inf")])
def test_invalid_sampling_rate_rejected(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, SENTRY_TRACES_SAMPLE_RATE=value)


@pytest.mark.asyncio
async def test_public_config_has_no_db_and_production_replay_is_hard_off():
    from app.config import get_settings

    settings = Settings(
        _env_file=None,
        SENTRY_FRONTEND_ENABLED=True,
        SENTRY_FRONTEND_DSN=DSN,
        SENTRY_ENVIRONMENT="production",
        SENTRY_REPLAY_ENABLED=True,
        SENTRY_REPLAYS_SESSION_SAMPLE_RATE=1,
    )
    production_app.dependency_overrides[get_settings] = lambda: settings
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=production_app), base_url="https://sso.invalid"
        ) as client:
            response = await client.get("/api/v1/auth/telemetry-config")
        assert response.status_code == 200
        assert response.json()["replay_enabled"] is False
        assert response.json()["replays_session_sample_rate"] == 0
        assert "SENTRY_DSN" not in response.text and "DATABASE" not in response.text
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        production_app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_parallel_request_scopes_do_not_export_user_context(telemetry_app):
    app, transport = telemetry_app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://sso.invalid"
    ) as client:
        await asyncio.gather(
            *(
                client.get("/api/status/503", headers={"X-Request-ID": secret})
                for secret in CANARIES
            )
        )
    events = [
        value
        for value in transport.envelopes
        if '"type":"event"' in value or '"type": "event"' in value
    ]
    assert len(events) == len(CANARIES)
    assert all(secret not in "".join(events) for secret in CANARIES)


class FaultTransport(HttpTransport):
    """Unit fault injection at HTTP; SDK queue/worker/rate-limit logic stays real."""

    def __init__(self, failure):
        self.failure = failure
        self.entered = threading.Event()
        self.release = threading.Event()
        self.dropped = []
        super().__init__(
            {**DEFAULT_OPTIONS, "dsn": DSN, "transport_queue_size": 1, "send_client_reports": False}
        )

    def _request(self, *args, **kwargs):
        self.entered.set()
        if self.failure == "queue":
            self.release.wait(3)
            return HTTPResponse(status=200)
        if self.failure == "429":
            return HTTPResponse(status=429, headers={"Retry-After": "60"})
        if self.failure == "dns":
            raise socket.gaierror("synthetic ingestion DNS failure")
        raise TimeoutError("synthetic ingestion timeout")

    def on_dropped_event(self, reason):
        self.dropped.append(reason)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["dns", "timeout", "429", "queue"])
async def test_real_sdk_worker_outage_does_not_change_http_result(telemetry_app, failure):
    app, _ = telemetry_app
    transport = FaultTransport(failure)
    assert initialize_sentry(
        Settings(_env_file=None, ENVIRONMENT="testing", SENTRY_ENABLED=True, SENTRY_DSN=DSN),
        transport=transport,
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://sso.invalid"
        ) as client:
            # No request waits on the blocked ingestion worker, including overflow.
            for _ in range(10):
                response = await asyncio.wait_for(client.get("/api/status/503"), timeout=1)
                assert response.status_code == 503
        assert await asyncio.to_thread(transport.entered.wait, 1)
        transport.release.set()
        await asyncio.to_thread(sentry_sdk.flush, 1)
        if failure == "queue":
            assert "full_queue" in transport.dropped
        if failure == "429":
            assert "status_429" in transport.dropped
    finally:
        transport.release.set()
        sentry_sdk.get_client().close(timeout=1)


@pytest.mark.asyncio
async def test_mail_span_parent_survives_existing_to_thread_without_message_data(
    telemetry_app, monkeypatch
):
    from email.message import EmailMessage

    from app.services.verification_email import deliver_message

    _, transport = telemetry_app
    observed = []

    def smtp_stub(message, settings):
        observed.append(sentry_sdk.get_current_span().trace_id)

    monkeypatch.setattr("app.services.verification_email._send_smtp", smtp_stub)
    message = EmailMessage()
    message["To"] = "canary@example.invalid"
    message["Subject"] = CANARIES[0]
    message.set_content(" ".join(CANARIES))
    with sentry_sdk.start_transaction(
        name="/api/unexpected", op="http.server", sampled=True
    ) as parent:
        await deliver_message(
            message,
            Settings(_env_file=None, EMAIL_PROVIDER="smtp", SMTP_HOST="localhost", SMTP_PORT=2525),
        )
        assert observed == [parent.trace_id]
    event = json.loads(transport.envelopes[-1].splitlines()[2])
    mail = next(span for span in event["spans"] if span["op"] == "email.send")
    assert mail["data"] == {
        "provider": "smtp",
        "operation": "send_email",
        "template": "email_verification",
        "result": "success",
    }
    assert all(secret not in transport.envelopes[-1] for secret in CANARIES)


@pytest.mark.asyncio
async def test_httpx_never_propagates_to_external_provider(telemetry_app):
    headers = []
    with sentry_sdk.start_transaction(name="/api/unexpected", sampled=True):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (headers.append(request.headers), httpx.Response(200))[1]
            )
        ) as client:
            await client.get("https://www.googleapis.com/oauth2/v3/certs")
    assert "sentry-trace" not in headers[0] and "baggage" not in headers[0]
