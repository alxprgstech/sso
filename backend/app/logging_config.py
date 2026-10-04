"""Safe independent stdout logs: no exception values, SQL, headers or URL queries."""

import builtins
import json
import logging
from datetime import datetime, timezone
from typing import Any


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            return self._format_safe(record)
        except Exception:
            # Prevent logging's fallback from printing the original message/args.
            return '{"component":"backend","level":"ERROR","message":"Log formatting failed"}'

    def _format_safe(self, record: logging.LogRecord) -> str:
        result: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname
            if record.levelname in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
            else "INFO",
            "component": "backend",
            "logger": next(
                (
                    name
                    for name in ("app", "uvicorn", "sqlalchemy")
                    if record.name == name or record.name.startswith(name + ".")
                ),
                "library",
            ),
            "message": "Application log",
        }
        if (
            record.name == "uvicorn.access"
            and isinstance(record.args, tuple)
            and len(record.args) == 5
        ):
            # Never emit raw path/client/referrer. Registered route template only.
            from app.telemetry import safe_route

            _, method, path, _, code = record.args
            result["message"] = "HTTP request"
            result["route"] = safe_route(str(path)) or "unmatched"
            result["method"] = (
                method
                if method in {"GET", "POST", "PATCH", "DELETE", "OPTIONS", "PUT"}
                else "other"
            )
            result["status"] = code if isinstance(code, int) and 100 <= code <= 599 else 0
        elif record.name.startswith("sqlalchemy."):
            result["message"] = "Database operation"
        elif record.name == "app.telemetry":
            result["message"] = "Telemetry initialization disabled"
        if record.exc_info:
            kind = record.exc_info[0]
            result["error_type"] = (
                kind.__name__
                if kind is not None and kind in vars(builtins).values()
                else "ApplicationError"
            )
        from app.core.diagnostics import CODES, request_id

        operation = getattr(record, "operation", None)
        reason = getattr(record, "reason", None)
        if isinstance(operation, str) and operation in CODES and reason in CODES[operation]:
            result["operation"] = operation
            result["reason"] = reason
        current_id = request_id.get()
        if current_id:
            result["request_id"] = current_id
        return json.dumps(result, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
