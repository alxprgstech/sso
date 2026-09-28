"""Unit checks for the process-local demo store; browser/PG checks are separate."""

from __future__ import annotations

import pytest
from alxprgs_sso.models import UserClaims, WebSessionInfo

from examples import demo_sessions


def _info() -> WebSessionInfo:
    return WebSessionInfo(
        user=UserClaims(sub="synthetic-user", preferred_username="synthetic-user", roles=["user"]),
        access_token="synthetic-access",
        id_token="synthetic-id",
        expires_in=300,
        id_token_claims={"sub": "synthetic-user"},
    )


def test_flow_is_browser_bound_short_lived_and_one_time(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    monkeypatch.setattr(demo_sessions.time, "monotonic", lambda: now)
    store = demo_sessions.DemoSessions()
    flow_id = store.start_flow("expected", "nonce", "verifier")
    assert store.take_flow(None, "expected") is None
    assert store.take_flow(flow_id, "wrong") is None
    assert store.take_flow(flow_id, "expected") is None

    flow_id = store.start_flow("expected", "nonce", "verifier")
    accepted = store.take_flow(flow_id, "expected")
    assert accepted is not None and accepted.nonce == "nonce" and accepted.verifier == "verifier"
    assert store.take_flow(flow_id, "expected") is None

    flow_id = store.start_flow("expected", "nonce", "verifier")
    now += demo_sessions.FLOW_TTL + 1
    assert store.take_flow(flow_id, "expected") is None


def test_session_revoke_idle_absolute_and_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    monkeypatch.setattr(demo_sessions.time, "monotonic", lambda: now)
    store = demo_sessions.DemoSessions()
    session_id, session = store.create_session(_info())
    assert len(session_id) >= 32 and len(session.csrf) >= 32
    assert store.get_session("forged") is None
    assert demo_sessions.DemoSessions().get_session(session_id) is None
    assert store.get_session(session_id) is session
    now += demo_sessions.SESSION_IDLE_TTL + 1
    assert store.get_session(session_id) is None

    session_id, session = store.create_session(_info())
    now += demo_sessions.SESSION_IDLE_TTL - 1
    assert store.get_session(session_id) is session
    now += demo_sessions.SESSION_ABSOLUTE_TTL
    assert store.get_session(session_id) is None

    session_id, _ = store.create_session(_info())
    assert store.revoke(session_id) is not None
    assert store.get_session(session_id) is None
