import asyncio
import threading

import pytest
from app.core import security
from argon2 import extract_parameters
from fastapi import HTTPException


def test_dummy_hash_has_same_real_argon2_parameters_and_password_policy():
    password = "Синтетический длинный пароль 🔒"
    encoded = security.hash_password(password)
    assert extract_parameters(encoded) == extract_parameters(security._dummy_password_hash)
    assert security.verify_password(password, encoded)
    assert not security.verify_password(password, security._dummy_password_hash)
    for blocked in ("passwordpassword", "123456789012345", "short", "a" * 20):
        with pytest.raises(ValueError):
            security.hash_password(blocked)


@pytest.mark.asyncio
async def test_real_argon2_does_not_block_event_loop():
    encoded = security.hash_password("SyntheticLongPasswordBudget2026!")
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.005)

    task = asyncio.create_task(heartbeat())
    try:
        assert await security.async_verify_password("SyntheticLongPasswordBudget2026!", encoded)
        assert ticks > 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_worker_capacity_stays_reserved_after_request_cancellation():
    gate = threading.Event()
    entered = threading.Event()

    def operation():
        entered.set()
        assert gate.wait(5)
        return True

    tasks = [asyncio.create_task(security.password_work(operation)) for _ in range(4)]
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.sleep(0.02)
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        with pytest.raises(HTTPException) as failure:
            await security.password_work(operation)
        assert failure.value.status_code == 503
    finally:
        gate.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    # The cancelled request's real worker has completed and released capacity.
    assert await security.password_work(lambda: True)
