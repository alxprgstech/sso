"""Bound request memory and receive time even when the backend is reached directly."""

import asyncio

from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    def __init__(self, app, limit: int = 65536, receive_timeout: float = 10):
        self.app, self.limit, self.receive_timeout = app, limit, receive_timeout

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        try:
            async with asyncio.timeout(self.receive_timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    size += len(chunk)
                    if size > self.limit:
                        return await JSONResponse(
                            {"error": "invalid_request", "detail": "Превышен размер запроса"},
                            status_code=413,
                        )(scope, receive, send)
                    chunks.append(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await JSONResponse(
                {"error": "invalid_request", "detail": "Истёк срок передачи запроса"},
                status_code=408,
            )(scope, receive, send)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
