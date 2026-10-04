"""Real ASGI messages: no Content-Length or chunking bypasses the memory budget."""

import asyncio

import pytest
from app.core.body_limit import BodyLimitMiddleware


@pytest.mark.asyncio
@pytest.mark.parametrize("chunks", [[b"x" * 17], [b"x" * 8, b"x" * 9]])
async def test_oversized_body_never_reaches_application(chunks):
    called = False
    sent = []
    queue = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]

    async def app(scope, receive, send):
        nonlocal called
        called = True

    async def receive():
        return queue.pop(0)

    async def send(message):
        sent.append(message)

    await BodyLimitMiddleware(app, limit=16)({"type": "http"}, receive, send)
    assert not called
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_slow_body_times_out_without_starting_application():
    called = False
    sent = []

    async def app(scope, receive, send):
        nonlocal called
        called = True

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    await BodyLimitMiddleware(app, receive_timeout=0.01)({"type": "http"}, receive, send)
    assert not called and sent[0]["status"] == 408


@pytest.mark.asyncio
async def test_valid_chunked_body_arrives_once_and_disconnect_is_preserved():
    queue = [
        {"type": "http.request", "body": b"hello", "more_body": True},
        {"type": "http.request", "body": b" world", "more_body": False},
        {"type": "http.disconnect"},
    ]

    async def receive():
        return queue.pop(0)

    async def app(scope, receive, send):
        assert await receive() == {
            "type": "http.request",
            "body": b"hello world",
            "more_body": False,
        }
        assert await receive() == {"type": "http.disconnect"}

    await BodyLimitMiddleware(app)({"type": "http"}, receive, None)
