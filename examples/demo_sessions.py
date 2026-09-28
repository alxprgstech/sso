"""Single-process demonstration session store.

The browser receives only opaque random identifiers. This store is deliberately
process-local: a restart revokes all sessions, and multiple workers are not supported.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from alxprgs_sso.models import WebSessionInfo

FLOW_TTL = 300
SESSION_ABSOLUTE_TTL = 86400
SESSION_IDLE_TTL = 3600


@dataclass
class Flow:
    state: str
    nonce: str
    verifier: str
    expires_at: float


@dataclass
class BrowserSession:
    info: WebSessionInfo
    csrf: str
    expires_at: float
    idle_expires_at: float


class DemoSessions:
    def __init__(self) -> None:
        self._flows: dict[str, Flow] = {}
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = threading.RLock()

    def start_flow(self, state: str, nonce: str, verifier: str) -> str:
        now = time.monotonic()
        identifier = secrets.token_urlsafe(32)
        with self._lock:
            self._prune(now)
            self._flows[identifier] = Flow(state, nonce, verifier, now + FLOW_TTL)
        return identifier

    def take_flow(self, identifier: str | None, state: str) -> Flow | None:
        if not identifier:
            return None
        now = time.monotonic()
        with self._lock:
            flow = self._flows.pop(identifier, None)
            if flow is None or flow.expires_at <= now:
                return None
            if not state or not secrets.compare_digest(flow.state, state):
                return None
            return flow

    def create_session(self, info: WebSessionInfo) -> tuple[str, BrowserSession]:
        now = time.monotonic()
        identifier = secrets.token_urlsafe(32)
        session = BrowserSession(
            info=info,
            csrf=secrets.token_urlsafe(32),
            expires_at=now + SESSION_ABSOLUTE_TTL,
            idle_expires_at=now + SESSION_IDLE_TTL,
        )
        with self._lock:
            self._prune(now)
            self._sessions[identifier] = session
        return identifier, session

    def get_session(self, identifier: str | None) -> BrowserSession | None:
        if not identifier:
            return None
        now = time.monotonic()
        with self._lock:
            session = self._sessions.get(identifier)
            if session is None:
                return None
            if session.expires_at <= now or session.idle_expires_at <= now:
                del self._sessions[identifier]
                return None
            session.idle_expires_at = now + SESSION_IDLE_TTL
            return session

    def revoke(self, identifier: str | None) -> BrowserSession | None:
        if not identifier:
            return None
        with self._lock:
            return self._sessions.pop(identifier, None)

    def _prune(self, now: float) -> None:
        for identifier, flow in list(self._flows.items()):
            if flow.expires_at <= now:
                del self._flows[identifier]
        for identifier, session in list(self._sessions.items()):
            if session.expires_at <= now or session.idle_expires_at <= now:
                del self._sessions[identifier]
