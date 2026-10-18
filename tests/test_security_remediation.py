"""Security boundary regressions, independent of external providers."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from app.api.deps import validate_cookie_origin
from app.api.mfa import _find_discoverable_credential
from app.config import Settings
from app.core.credential_ids import canonical_credential_id
from app.core.exceptions import AuthenticationException
from app.core.urls import validate_redirect
from app.services import google_keys
from app.services.webauthn_assertion import locked_assertion_credential
from fastapi import HTTPException
from starlette.requests import Request


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://*.example.test/cb",
        "https://user@rp.test/cb",
        "https://rp.test/cb#f",
        "http://rp.test/cb",
        "https://rp.test/\\evil",
    ],
)
def test_unsafe_redirects_rejected_even_in_local_profile(url):
    with pytest.raises(ValueError):
        validate_redirect(url, local=True)


def test_loopback_redirect_requires_explicit_local_profile():
    with pytest.raises(ValueError):
        validate_redirect("http://localhost:8001/callback?x=1")
    validate_redirect("http://localhost:8001/callback?x=1", local=True)


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "https://evil.test"},
        {"origin": "null"},
        {"origin": "http://localhost:5173/path"},
        {"referer": "https://evil.test/path"},
    ],
)
def test_cookie_origin_rejects_foreign_origin_and_referer(headers):
    request = Request(
        {
            "type": "http",
            "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
        }
    )
    with pytest.raises(HTTPException) as error:
        validate_cookie_origin(request, Settings(_env_file=None))
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [{}, {"origin": "http://localhost:5173"}, {"referer": "http://localhost:5173/path?query=yes"}],
)
def test_cookie_origin_allows_exact_origin(headers):
    request = Request(
        {
            "type": "http",
            "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
        }
    )
    validate_cookie_origin(request, Settings(_env_file=None))


@pytest.mark.parametrize(
    "method,path,origin,allowed",
    [
        ("GET", "/oauth/authorize", None, True),
        ("GET", "/oauth/logout", None, True),
        ("POST", "/oauth/logout", None, False),
        ("GET", "/api/v1/auth/sessions", None, False),
        ("POST", "/api/v1/auth/change-password", None, False),
        ("GET", "/oauth/authorize", "https://rp.example.test", False),
        ("GET", "/oauth/logout", "null", False),
    ],
)
def test_cookie_origin_preserves_oidc_front_channel_only(method, path, origin, allowed):
    headers = [(b"referer", b"https://rp.example.test/account")]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    request = Request({"type": "http", "method": method, "path": path, "headers": headers})
    cfg = Settings(_env_file=None)
    if allowed:
        validate_cookie_origin(request, cfg)
    else:
        with pytest.raises(HTTPException) as error:
            validate_cookie_origin(request, cfg)
        assert error.value.status_code == 403


@pytest.mark.parametrize("value", ["YWJj", "YWJj=", "YWJj=="])
def test_credential_id_canonical(value):
    assert canonical_credential_id(value) == "YWJj"


@pytest.mark.parametrize("value", ["", "a", "wrong id", "../YWJj", "YWJj===", "a" * 513, None])
@pytest.mark.asyncio
async def test_invalid_credential_rejected_before_database(value):
    db = AsyncMock()
    with pytest.raises(AuthenticationException):
        await _find_discoverable_credential(db, value)
    db.scalar.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_credential_is_one_exact_lookup():
    db = AsyncMock()
    db.scalar.return_value = None
    assert await _find_discoverable_credential(db, "YWJj==") is None
    sql = str(db.scalar.call_args.args[0])
    assert "WHERE webauthn_credentials.credential_id =" in sql
    db.scalar.assert_awaited_once()
    db.execute.assert_not_called()
    db.reset_mock()
    with pytest.raises(AuthenticationException):
        await locked_assertion_credential(db, "user", {"id": "YWJj"})
    assert "webauthn_credentials.user_id =" in str(db.scalar.call_args.args[0])
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "http://evil.test"}),
        httpx.Response(200, content=b"x" * 65537),
        httpx.Response(200, json={"keys": []}),
    ],
)
async def test_google_invalid_response_fails_closed(monkeypatch, response):
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return response

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(google_keys.httpx, "AsyncClient", client)
    google_keys.clear_cache()
    results = await asyncio.gather(
        *(google_keys.signing_keys() for _ in range(8)), return_exceptions=True
    )
    assert all(isinstance(result, ValueError) for result in results)
    assert calls == [google_keys.GOOGLE_CERTS_URL]
    google_keys.clear_cache()


@pytest.mark.asyncio
async def test_google_cache_single_flight(monkeypatch):
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"keys": [{"kid": "fixture"}]})

    monkeypatch.setattr(
        google_keys.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    google_keys.clear_cache()
    results = await asyncio.gather(*(google_keys.signing_keys() for _ in range(8)))
    assert len(calls) == 1 and all(result == results[0] for result in results)
    google_keys.clear_cache()
