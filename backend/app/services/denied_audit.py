"""Bound anonymous denial writes independently of attacker-controlled identities."""

from threading import Lock

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import AuditService

MAX_ROUTES = 256
MAX_COUNT = 2**63 - 1
REASONS = {401: "authentication_required", 403: "access_denied", 429: "rate_limit_exceeded"}


class DeniedAuditBuffer:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: dict[tuple[str, int], int] = {}
        self._flushing = False

    def record(self, route: str, status: int, count: int = 1) -> None:
        with self._lock:
            key = (route, status)
            if key not in self._counts and len(self._counts) >= MAX_ROUTES:
                key = ("anonymous_overflow", status)
            self._counts[key] = min(MAX_COUNT, self._counts.get(key, 0) + count)

    async def flush(self, db: AsyncSession) -> None:
        with self._lock:
            if self._flushing or not self._counts:
                return
            self._flushing = True
            snapshot, self._counts = self._counts, {}
        try:
            for (route, status), count in snapshot.items():
                await AuditService.log_event(
                    db,
                    "action_denied",
                    details={
                        "route": route,
                        "reason": REASONS[status],
                        "count": count,
                        "aggregated": True,
                        "window_seconds": 60,
                    },
                    commit=False,
                )
            await db.commit()
        except BaseException:
            try:
                await db.rollback()
            finally:
                for (route, status), count in snapshot.items():
                    self.record(route, status, count)
            raise
        finally:
            with self._lock:
                self._flushing = False


anonymous_denials = DeniedAuditBuffer()
