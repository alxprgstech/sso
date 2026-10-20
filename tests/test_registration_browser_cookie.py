"""Enrollment cookie is host-only/HttpOnly, with Secure mandatory for HTTPS/production."""

import pytest
from app.config import Settings
from app.core.registration_flow import browser_secret, set_browser_secret
from app.core.security import generate_random_token
from fastapi import Request, Response


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_registration_cookie_is_host_only_and_cannot_be_read_by_script(scheme):
    request = Request(
        {"type": "http", "scheme": scheme, "path": "/", "headers": [(b"host", b"testserver")]}
    )
    response = Response()
    secret = generate_random_token(32)
    set_browser_secret(response, request, Settings(_env_file=None), secret)
    header = response.headers["set-cookie"]
    assert "HttpOnly" in header and "SameSite=lax" in header and "Path=/" in header
    assert "Domain=" not in header and "Max-Age=3600" in header
    assert ("Secure" in header) == (scheme == "https")
    assert header.startswith(
        "__Host-alx_registration=" if scheme == "https" else "alx_registration="
    )
    absent = Request(
        {"type": "http", "scheme": scheme, "path": "/", "headers": [(b"host", b"testserver")]}
    )
    assert browser_secret(absent, Settings(_env_file=None)) is None
