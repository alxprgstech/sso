"""Unit checks only; fake responses do not establish production availability."""

import io
import ssl
import urllib.error
from unittest.mock import Mock

import pytest

from scripts import check_public_readiness as public


@pytest.mark.parametrize(
    "status,url,payload,expected",
    [
        (200, public.URL, b'{"status":"ready","database":"connected"}', 0),
        (503, public.URL, b'{"status":"unavailable"}', 1),
        (200, public.URL, b'{"status":"ready","database":"disconnected"}', 1),
        (200, public.URL, b'{"status":"ok"}', 1),
        (200, public.URL, b"<html>maintenance</html>", 1),
        (200, "https://example.com/health/ready", b"{}", 1),
        (302, public.URL, b"{}", 1),
    ],
)
def test_readiness_requires_exact_public_success(monkeypatch, status, url, payload, expected):
    response = Mock(status=status)
    response.geturl.return_value = url
    response.read.return_value = payload
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=response)
    opener.open.return_value.__exit__ = Mock(return_value=False)
    build = Mock(return_value=opener)
    monkeypatch.setattr(public.urllib.request, "build_opener", build)
    assert public.main() == expected
    request = opener.open.call_args.args[0]
    assert request.full_url == public.URL
    assert opener.open.call_args.kwargs == {"timeout": 15}
    assert opener.open.call_count == 1
    tls, redirect = build.call_args.args
    assert tls._context.check_hostname
    assert tls._context.verify_mode == ssl.CERT_REQUIRED
    assert isinstance(redirect, public.NoRedirect)
    if status == 200 and url == public.URL:
        response.read.assert_called_once_with(4096)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("DNS unavailable"),
        ssl.SSLCertVerificationError("untrusted certificate"),
        TimeoutError("timeout"),
        urllib.error.HTTPError(public.URL, 503, "unavailable", {}, io.BytesIO()),
    ],
)
def test_network_failures_are_fatal_without_retry(monkeypatch, error):
    opener = Mock()
    opener.open.side_effect = error
    monkeypatch.setattr(public.urllib.request, "build_opener", Mock(return_value=opener))
    assert public.main() == 1
    assert opener.open.call_count == 1


def test_redirect_is_rejected():
    handler = public.NoRedirect()
    assert handler.redirect_request(None, None, 302, "redirect", {}, public.URL) is None
