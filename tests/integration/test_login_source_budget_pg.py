"""SSO-SEC-0006: isolate targeted failure quotas and bound real Argon2 admission."""

import asyncio
import threading
from secrets import token_urlsafe

import httpx
import pytest
from app.core import security
from app.main import app

from tests.integration.test_security_revision_pg import PASSWORD, seed

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]


async def test_targeted_failures_and_aliases_do_not_lock_other_source(pg_session, pg_client):
    user, _ = await seed(pg_session)
    transport = httpx.ASGITransport(app=app, client=("192.0.2.100", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as attacker:
        wrong = token_urlsafe(32)
        # Username/email aliases cannot bypass the same account+source quota.
        for index in range(5):
            result = await attacker.post(
                "/api/v1/auth/login",
                json={
                    "username": user.username if index < 2 else user.email,
                    "password": wrong,
                },
                headers={"X-Forwarded-For": f"198.51.100.{index}"},
            )
            assert result.status_code == 401
        blocked = await attacker.post(
            "/api/v1/auth/login",
            json={
                "username": user.username,
                "password": PASSWORD,
            },
            headers={"X-Forwarded-For": "198.51.100.240"},
        )
        assert blocked.status_code == 429
        assert blocked.headers["Retry-After"] == "60"
    legitimate = await pg_client.post(
        "/api/v1/auth/login",
        json={
            "username": user.username,
            "password": PASSWORD,
        },
    )
    assert legitimate.status_code == 200
    assert not legitimate.json().get("mfa_required")  # Seed has no configured second factor.
    assert (await pg_client.get("/api/v1/auth/me")).status_code == 200


async def test_eight_login_burst_leaves_capacity_for_other_source_real_argon2(
    pg_session, pg_client, monkeypatch
):
    user, _ = await seed(pg_session)
    gate = threading.Event()
    entered = threading.Event()
    guard = threading.Lock()
    running, maximum = 0, 0
    actual_verify = security.verify_password

    def instrumented_verify(*args):
        nonlocal running, maximum
        with guard:
            running += 1
            maximum = max(maximum, running)
            if running == 2:
                entered.set()
        try:
            assert gate.wait(10)
            return actual_verify(*args)  # Real Argon2, never a successful mock.
        finally:
            with guard:
                running -= 1

    monkeypatch.setattr(security, "verify_password", instrumented_verify)
    transport = httpx.ASGITransport(app=app, client=("192.0.2.101", 123))
    tasks = []
    owner = None
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as attacker:
        for index in range(8):
            tasks.append(
                asyncio.create_task(
                    attacker.post(
                        "/api/v1/auth/login",
                        json={"username": f"unknown_burst_{index}", "password": token_urlsafe(32)},
                    )
                )
            )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            owner = asyncio.create_task(
                pg_client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": user.username,
                        "password": PASSWORD,
                    },
                )
            )
            # Await actual source admission, rather than depending on machine speed.
            async with asyncio.timeout(5):
                while security._password_sources.get("127.0.0.1", 0) != 1:
                    assert not owner.done()
                    await asyncio.sleep(0.01)
            assert security._password_sources["192.0.2.101"] == 2
            # Observe all six rejections before unblocking the two real workers.
            # Otherwise a late-arriving burst request could be admitted after release.
            async with asyncio.timeout(5):
                while sum(task.done() for task in tasks) != 6:
                    assert sum(task.done() for task in tasks) < 6
                    await asyncio.sleep(0.01)
            assert all(task.result().status_code == 429 for task in tasks if task.done())
            gate.set()
            results = await asyncio.gather(*tasks)
            legitimate = await owner
            assert legitimate.status_code == 200
            statuses = [result.status_code for result in results]
            assert statuses.count(401) == 2 and statuses.count(429) == 6
            assert 503 not in statuses
            assert all(
                result.headers["Retry-After"] == "1"
                for result in results
                if result.status_code == 429
            )
            assert maximum == 2
        finally:
            gate.set()
            await asyncio.gather(*tasks, *([owner] if owner else []), return_exceptions=True)
    assert not security._password_sources
