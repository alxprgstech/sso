"""Bounded, single-flight Google signing-key cache; failure never enables an action."""

import asyncio
import json
import time
from typing import Any

import httpx

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
MAX_BYTES = 65536
CACHE_SECONDS = 300
_keys: dict[str, Any] | None = None
_expires = 0.0
_failed_until = 0.0
_lock = asyncio.Lock()


def clear_cache() -> None:
    """Discard cached public material (also used for isolated transport tests)."""
    global _keys, _expires, _lock, _failed_until
    _keys, _expires, _lock, _failed_until = None, 0.0, asyncio.Lock(), 0.0


async def signing_keys() -> dict[str, Any]:
    global _keys, _expires, _failed_until
    if _keys is not None and time.monotonic() < _expires:
        return _keys
    async with _lock:
        if time.monotonic() < _failed_until:
            raise ValueError("Google key service unavailable")
        if _keys is not None and time.monotonic() < _expires:
            return _keys
        try:
            async with asyncio.timeout(5):
                async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
                    async with client.stream("GET", GOOGLE_CERTS_URL) as response:
                        if response.status_code != 200:
                            raise ValueError("Google key service unavailable")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > MAX_BYTES:
                                raise ValueError("Google key response too large")
                            body.extend(chunk)
            document = json.loads(body)
            if not isinstance(document, dict):
                raise ValueError("Invalid Google signing keys")
            keys = document.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
                raise ValueError("Invalid Google signing keys")
        except Exception:
            _failed_until = time.monotonic() + 5
            raise
        _keys, _expires = document, time.monotonic() + CACHE_SECONDS
        return document
