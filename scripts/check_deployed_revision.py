"""Decide whether the exact target revision is already installed and healthy.

The check talks only to the fixed production origin over verified TLS, accepts
no redirects, bounds every response and uses the installed application's own
build identity. A missing, malformed, cacheable or stale response never yields
``already_deployed``: the caller continues with the normal verified deployment.
TLS and trusted-origin violations are security errors and fail the run.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

BASE_URL = "https://auth.alxprgs.tech"
IDENTITY_URL = f"{BASE_URL}/health/identity"
FRONTEND_IDENTITY_URL = f"{BASE_URL}/build-info.json"
SHA = re.compile(r"[a-f0-9]{40}")
TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 4096
BACKEND_KEYS = {"status", "database", "commit_sha"}
FRONTEND_KEYS = {"version", "commit_sha", "release"}


class SecurityError(Exception):
    """A TLS, trusted-origin or redirect violation; never a deploy signal."""


class Unavailable(Exception):
    """The identity cannot be confirmed; continue with the normal deployment."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Decision:
    result: str
    reason: str
    installed_sha: str = ""


def build_opener() -> urllib.request.OpenerDirector:
    # Empty ProxyHandler keeps HTTPS_PROXY on the runner from intercepting the
    # trusted origin; the default context verifies the certificate and hostname.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        NoRedirect(),
    )


def _is_tls_error(error: BaseException) -> bool:
    if isinstance(error, ssl.SSLError):
        return True
    return isinstance(error, urllib.error.URLError) and isinstance(error.reason, ssl.SSLError)


def _raise_redirect(error: BaseException) -> None:
    if isinstance(error, urllib.error.HTTPError) and 300 <= error.code < 400:
        raise SecurityError("trusted origin attempted an HTTP redirect") from None


def _raise_tls(error: BaseException) -> None:
    if _is_tls_error(error):
        raise SecurityError("TLS certificate or hostname verification failed") from None


def _raise_unavailable(error: BaseException) -> NoReturn:
    if isinstance(error, urllib.error.HTTPError):
        raise Unavailable(f"HTTP {error.code}") from None
    raise Unavailable("request timed out or connection failed") from None


def _translate_fetch_error(error: BaseException) -> NoReturn:
    _raise_redirect(error)
    _raise_tls(error)
    _raise_unavailable(error)


def _open_response(
    opener: urllib.request.OpenerDirector, request: urllib.request.Request
) -> object:
    try:
        return opener.open(request, timeout=TIMEOUT_SECONDS)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        ssl.SSLError,
        TimeoutError,
        OSError,
    ) as error:
        _translate_fetch_error(error)


def _response_parts(response: object) -> tuple[int, str, str, bytes]:
    return (
        response.status,
        response.geturl(),
        response.headers.get("Cache-Control", ""),
        response.read(MAX_RESPONSE_BYTES + 1),
    )


def _check_cache(cache_control: str) -> None:
    tokens = {token.strip().lower() for token in cache_control.split(",")}
    if "no-store" not in tokens:
        raise Unavailable("identity response may be cached")


def _validate_response(
    url: str, status: int, final_url: str, body: bytes, cache_control: str
) -> None:
    if final_url != url:
        raise SecurityError("trusted origin returned an unexpected response address")
    if status != 200:
        raise Unavailable(f"HTTP {status}")
    if len(body) > MAX_RESPONSE_BYTES:
        raise Unavailable("response exceeds the size limit")
    _check_cache(cache_control)


def fetch(opener: urllib.request.OpenerDirector, url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Cache-Control": "no-cache"},
    )
    response = _open_response(opener, request)
    with response:
        status, final_url, cache_control, body = _response_parts(response)
    _validate_response(url, status, final_url, body, cache_control)
    return body


def _json_object(body: bytes) -> dict:
    try:
        value = json.loads(body)
    except (ValueError, TypeError):
        raise Unavailable("response is not valid JSON") from None
    if not isinstance(value, dict):
        raise Unavailable("response is not a JSON object")
    return value


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and bool(SHA.fullmatch(value))


def _check_identity_shape(payload: dict, expected_keys: set[str], label: str) -> None:
    if set(payload) != expected_keys:
        raise Unavailable(f"{label} identity has an unexpected payload")


def _check_identity_sha(payload: dict, label: str) -> None:
    if not _valid_sha(payload["commit_sha"]):
        raise Unavailable(f"{label} identity does not contain a full commit SHA")


def _read_identity(
    opener: urllib.request.OpenerDirector,
    url: str,
    expected_keys: set[str],
    label: str,
) -> dict:
    try:
        payload = _json_object(fetch(opener, url))
    except Unavailable as error:
        raise Unavailable(f"{label} identity unavailable ({error})") from None
    _check_identity_shape(payload, expected_keys, label)
    _check_identity_sha(payload, label)
    return payload


def backend_identity(opener: urllib.request.OpenerDirector) -> tuple[str | None, str]:
    try:
        payload = _read_identity(opener, IDENTITY_URL, BACKEND_KEYS, "backend")
    except Unavailable as error:
        return None, str(error)
    if payload["status"] != "ready" or payload["database"] != "connected":
        return None, "backend readiness is not confirmed"
    return payload["commit_sha"], ""


def frontend_identity(opener: urllib.request.OpenerDirector) -> tuple[str | None, str]:
    try:
        payload = _read_identity(opener, FRONTEND_IDENTITY_URL, FRONTEND_KEYS, "frontend")
    except Unavailable as error:
        return None, str(error)
    return payload["commit_sha"], ""


def decide(sha: str, opener: urllib.request.OpenerDirector | None = None) -> Decision:
    if not SHA.fullmatch(sha):
        raise ValueError("Target must be a full lowercase commit SHA")
    opener = opener or build_opener()
    backend_sha, backend_reason = backend_identity(opener)
    if backend_sha is None:
        return Decision("deploy", backend_reason)
    if backend_sha != sha:
        return Decision(
            "deploy",
            "installed backend revision differs from the target",
            installed_sha=backend_sha,
        )
    frontend_sha, frontend_reason = frontend_identity(opener)
    if frontend_sha is None:
        return Decision("deploy", frontend_reason, installed_sha=backend_sha)
    if frontend_sha != sha:
        return Decision(
            "deploy",
            "published frontend revision differs from the target",
            installed_sha=backend_sha,
        )
    return Decision(
        "already_deployed",
        "installed backend, published frontend and readiness match the target",
        installed_sha=backend_sha,
    )


def write_outputs(path: Path, decision: Decision) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"decision={decision.result}\n")
        output.write(f"installed_sha={decision.installed_sha}\n")
        output.write(f"reason={decision.reason}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        decision = decide(args.sha)
    except SecurityError as error:
        print(f"::error::EC2 CD security check failed: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"::error::EC2 CD identity check rejected: {error}", file=sys.stderr)
        return 2
    write_outputs(args.github_output, decision)
    print(f"EC2 CD identity decision: {decision.result} ({decision.reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
