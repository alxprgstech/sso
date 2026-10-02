"""Sentry boundary: only an explicit safe projection may leave the process."""

from __future__ import annotations

import logging
import re
import math
import builtins
from pathlib import Path
from typing import Any, TYPE_CHECKING, cast
from collections.abc import Mapping

if TYPE_CHECKING:
    from sentry_sdk._types import DataCollectionUserOptions, Event
from urllib.parse import urlsplit

import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.transport import Transport
from starlette.exceptions import HTTPException

from app.build_info import get_build_info
from app.config import Settings

_routes: list[tuple[str, re.Pattern[str]]] = []
_EXCLUDED = {"/health/live", "/health/ready", "/api/v1/auth/telemetry-config"}
_OPERATIONS = {"capabilities", "email_delivery", "send_email"}
_HEX = re.compile(r"^[a-f0-9]+$")
_CODE_FILES = {
    "app/" + path.relative_to(Path(__file__).parent).as_posix()
    for path in Path(__file__).parent.rglob("*.py")
}
_EXCEPTION_TYPES = {
    name
    for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, Exception)
} | {
    "HTTPException",
    "SESEmailDeliveryError",
    "OperationalError",
    "IntegrityError",
    "DBAPIError",
    "InterfaceError",
    "ProgrammingError",
    "DataError",
    "SQLAlchemyError",
    "InvalidRequestError",
    "NoResultFound",
    "MultipleResultsFound",
}
DATA_COLLECTION: "DataCollectionUserOptions" = {
    "user_info": False,
    "cookies": {"mode": "off"},
    "http_headers": {"request": {"mode": "off"}},
    "http_bodies": [],
    "url_query_params": {"mode": "off"},
    "graphql": {"document": False, "variables": False},
    "gen_ai": {"inputs": False, "outputs": False},
    "database_query_data": False,
    "queues": False,
    "stack_frame_variables": False,
    "frame_context_lines": 0,
}


def register_routes(app: Any) -> None:
    global _routes
    from starlette.routing import compile_path

    # FastAPI 0.141 defers included routers; OpenAPI exposes their effective paths.
    _routes = [(path, compile_path(path)[0]) for path in app.openapi()["paths"]]


def safe_route(value: str) -> str | None:
    try:
        path = urlsplit(value).path
    except (TypeError, ValueError):
        return None
    for template, pattern in _routes:
        if path == template or pattern.fullmatch(path):
            return template
    return None


def _hex(value: Any, length: int) -> str | None:
    return (
        value if isinstance(value, str) and len(value) == length and _HEX.fullmatch(value) else None
    )


def safe_span(span: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, length in (("trace_id", 32), ("span_id", 16), ("parent_span_id", 16)):
        if value := _hex(span.get(key), length):
            result[key] = value
    for key in ("start_timestamp", "timestamp"):
        if isinstance(span.get(key), (int, float)) and math.isfinite(span[key]):
            result[key] = span[key]
        elif isinstance(span.get(key), str) and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T[\d:.]+Z", span[key]
        ):
            result[key] = span[key]
    if span.get("status") in {
        "ok",
        "internal_error",
        "unavailable",
        "cancelled",
        "deadline_exceeded",
        "unauthenticated",
        "permission_denied",
        "not_found",
        "resource_exhausted",
        "invalid_argument",
        "unknown_error",
    }:
        result["status"] = span["status"]
    operation = span.get("op", "")
    result["op"] = (
        operation
        if operation
        in {
            "http.server",
            "http.client",
            "db",
            "db.sql.query",
            "email.send",
            "middleware.starlette",
            "middleware.starlette.receive",
            "middleware.starlette.send",
        }
        else "app"
    )
    result["description"] = result["op"]
    data = span.get("data", {})
    result["data"] = {
        key: data[key]
        for key, allowed in {
            "provider": {"ses", "smtp"},
            "operation": _OPERATIONS,
            "template": {"email_verification"},
            "result": {"success", "failure"},
            "db.system": {"postgresql"},
            "db.system.name": {"postgresql"},
            "http.request.method": {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
        }.items()
        if isinstance(data.get(key), str) and data[key] in allowed
    }
    for key in ("http.response.status_code", "http.status_code"):
        if isinstance(data.get(key), int) and 100 <= data[key] <= 599:
            result["data"][key] = data[key]
    return result


def sanitize_event(event: Mapping[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    try:
        hint.pop("attachments", None)
        exc_info = hint.get("exc_info")
        if exc_info and isinstance(exc_info[1], HTTPException) and exc_info[1].status_code < 500:
            return None
        request = event.get("request", {})
        route = safe_route(request.get("url", "")) or safe_route(event.get("transaction", ""))
        if route in _EXCLUDED:
            return None
        transaction = event.get("type") == "transaction"
        if transaction and not route:
            return None
        result: dict[str, Any] = {
            "platform": "python",
            "level": "error",
            "tags": {"component": "backend"},
        }
        for key in ("timestamp", "start_timestamp"):
            if isinstance(event.get(key), (int, float)) and math.isfinite(event[key]):
                result[key] = event[key]
            elif isinstance(event.get(key), str) and re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T[\d:.]+Z", event[key]
            ):
                result[key] = event[key]
        if event_id := _hex(event.get("event_id"), 32):
            result["event_id"] = event_id
        # These values come from SDK init, never from request-local overrides.
        options = sentry_sdk.get_client().options
        for key in ("release", "environment"):
            if options.get(key):
                result[key] = options[key]
        if route:
            result["transaction"] = route
            result["request"] = {"url": route}
            if request.get("method") in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
                result["request"]["method"] = request["method"]
        trace = event.get("contexts", {}).get("trace")
        if trace:
            result["contexts"] = {"trace": safe_span(trace)}
        if transaction:
            result["type"] = "transaction"
            result["transaction_info"] = {"source": "route"}
            result["spans"] = [safe_span(span) for span in event.get("spans", [])]
        else:
            values = []
            for exc in event.get("exception", {}).get("values", []):
                kind = exc.get("type", "Error")
                value: dict[str, Any] = {
                    "type": kind if kind in _EXCEPTION_TYPES else "ApplicationError",
                    "value": "Unexpected application failure",
                }
                frames = []
                for frame in exc.get("stacktrace", {}).get("frames", []):
                    filename = str(frame.get("filename", "")).replace("\\", "/")
                    # Only relative code locations; no absolute developer paths or arbitrary URL.
                    marker = filename.rfind("/app/")
                    filename = filename[marker + 1 :] if marker >= 0 else filename
                    if filename not in _CODE_FILES:
                        filename = "external.py"
                    clean: dict[str, Any] = {
                        "filename": filename,
                        "in_app": filename.startswith("app/"),
                    }
                    if isinstance(frame.get("lineno"), int):
                        clean["lineno"] = frame["lineno"]
                    frames.append(clean)
                if frames:
                    value["stacktrace"] = {"frames": frames}
                values.append(value)
            if not values:
                return None  # No free-form capture_message channel.
            result["exception"] = {"values": values}
        operation = event.get("tags", {}).get("operation")
        if operation in _OPERATIONS:
            result["tags"]["operation"] = operation
        return result
    except Exception:
        return None


def traces_sampler(context: dict[str, Any], rate: float) -> float:
    scope = context.get("asgi_scope", {})
    route = safe_route(scope.get("path", ""))
    if not rate or scope.get("method") == "OPTIONS" or not route or route in _EXCLUDED:
        return 0
    if context.get("parent_sampled") is not None:
        return float(bool(context["parent_sampled"]))
    return min(rate, 0.001) if route.startswith("/.well-known/") else rate


def initialize_sentry(settings: Settings, *, transport: Transport | None = None) -> bool:
    if not settings.SENTRY_ENABLED or not settings.SENTRY_DSN:
        return False
    if settings.ENVIRONMENT == "testing" and transport is None:
        return False
    try:
        integrations: list[Any] = [
            FastApiIntegration(
                transaction_style="url", failed_request_status_codes=set(range(500, 600))
            ),
            StarletteIntegration(
                transaction_style="url", failed_request_status_codes=set(range(500, 600))
            ),
        ]
        if settings.SENTRY_TRACES_SAMPLE_RATE:
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
            from sentry_sdk.integrations.httpx import HttpxIntegration

            integrations += [SqlalchemyIntegration(), HttpxIntegration()]
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.telemetry_environment,
            release=get_build_info()["release"],
            default_integrations=False,
            auto_enabling_integrations=False,
            integrations=integrations,
            data_collection=DATA_COLLECTION,
            max_request_body_size="never",
            include_local_variables=False,
            include_source_context=False,
            trace_lifecycle="static",
            traces_sample_rate=None,
            traces_sampler=(
                lambda context: traces_sampler(context, settings.SENTRY_TRACES_SAMPLE_RATE)
            )
            if settings.SENTRY_TRACES_SAMPLE_RATE
            else None,
            trace_propagation_targets=[],
            strict_trace_continuation=True,
            before_send=lambda event, hint: cast("Event | None", sanitize_event(event, hint)),
            before_send_transaction=lambda event, hint: cast(
                "Event | None", sanitize_event(event, hint)
            ),
            before_breadcrumb=lambda breadcrumb, hint: None,
            enable_logs=False,
            enable_metrics=False,
            before_send_log=lambda log, hint: None,
            before_send_metric=lambda metric, hint: None,
            profiles_sample_rate=0,
            auto_session_tracking=False,
            send_client_reports=False,
            transport_queue_size=100,
            shutdown_timeout=2,
            transport=transport,
        )
        return True
    except Exception:
        logging.getLogger("app.telemetry").warning("Telemetry initialization disabled")
        return False


def capture_infrastructure_failure(error: Exception, operation: str) -> None:
    if operation not in _OPERATIONS:
        return
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("operation", operation)
            sentry_sdk.capture_exception(error)
    except Exception:
        pass


class TraceHeaderFilter:
    """Preserve only trace identity and org id; arbitrary baggage never enters scopes."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = []
            for key, value in scope.get("headers", []):
                if key == b"baggage":
                    safe = [
                        item.strip()
                        for item in value.split(b",")
                        if re.fullmatch(
                            rb"sentry-(?:trace_id=[a-f0-9]{32}|org_id=[0-9]+|sampled=(?:true|false))",
                            item.strip(),
                        )
                    ]
                    if safe:
                        headers.append((key, b",".join(safe)))
                else:
                    headers.append((key, value))
            scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


class TelemetryFastAPI(FastAPI):
    """Sanitize propagation before the SDK's patched Starlette __call__."""

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await TraceHeaderFilter(super().__call__)(scope, receive, send)
