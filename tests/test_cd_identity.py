"""Unit checks for the early CD identity decision. Fake HTTP proves no live install."""

import hashlib
import json
import ssl
import urllib.error
import urllib.request

import pytest

from scripts import check_deployed_revision as identity

COMMIT = hashlib.sha1(b"identity regression", usedforsecurity=False).hexdigest()
OTHER = "c" * 40


class FakeResponse:
    def __init__(self, url, payload, *, status=200, cache="no-store"):
        self.status = status
        self.url = url
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.headers = {"Cache-Control": cache} if cache is not None else {}

    def geturl(self):
        return self.url

    def read(self, amount):
        return self.payload[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request.full_url, timeout))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def backend(payload, **kwargs):
    return FakeResponse(identity.IDENTITY_URL, payload, **kwargs)


def frontend(payload, **kwargs):
    return FakeResponse(identity.FRONTEND_IDENTITY_URL, payload, **kwargs)


def matched_opener():
    return FakeOpener(
        [
            backend({"status": "ready", "database": "connected", "commit_sha": COMMIT}),
            frontend({"version": "0.3.0", "commit_sha": COMMIT, "release": "sso@0.3.0"}),
        ]
    )


def test_matching_installed_revision_is_already_deployed():
    opener = matched_opener()
    decision = identity.decide(COMMIT, opener)
    assert decision.result == "already_deployed"
    assert decision.installed_sha == COMMIT
    assert [url for url, _ in opener.calls] == [
        identity.IDENTITY_URL,
        identity.FRONTEND_IDENTITY_URL,
    ]
    assert all(timeout == identity.TIMEOUT_SECONDS for _, timeout in opener.calls)


def test_different_sha_with_same_version_is_a_normal_deploy():
    opener = FakeOpener(
        [
            backend({"status": "ready", "database": "connected", "commit_sha": OTHER}),
        ]
    )
    decision = identity.decide(COMMIT, opener)
    assert decision.result == "deploy"
    assert decision.installed_sha == OTHER
    assert "differs" in decision.reason
    assert len(opener.calls) == 1


def test_same_version_alone_never_causes_skip():
    opener = FakeOpener(
        [
            backend({"status": "ready", "database": "connected", "commit_sha": OTHER}),
            frontend({"version": "0.3.0", "commit_sha": OTHER, "release": "sso@0.3.0"}),
        ]
    )
    assert identity.decide(COMMIT, opener).result == "deploy"


def test_missing_identity_endpoint_on_legacy_install_is_a_normal_deploy():
    error = urllib.error.HTTPError(identity.IDENTITY_URL, 404, "not found", {}, None)
    decision = identity.decide(COMMIT, FakeOpener([error]))
    assert decision.result == "deploy"
    assert decision.installed_sha == ""
    assert "HTTP 404" in decision.reason


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"{",
        b"[]",
        b'{"status":"ready"}',
        b'{"status":"ready","database":"connected","commit_sha":""}',
        b'{"status":"ready","database":"connected","commit_sha":"abc"}',
        b'{"status":"ready","database":"connected","commit_sha":"' + b"G" * 40 + b'"}',
        b'{"status":"ready","database":"connected","commit_sha":"' + b"c" * 40 + b'","extra":1}',
    ],
)
def test_invalid_backend_identity_never_claims_already_deployed(payload):
    decision = identity.decide(COMMIT, FakeOpener([backend(payload)]))
    assert decision.result == "deploy"


def test_unready_database_never_claims_already_deployed():
    decision = identity.decide(
        COMMIT,
        FakeOpener(
            [
                backend(
                    {"status": "unavailable", "database": "disconnected", "commit_sha": COMMIT},
                    status=503,
                )
            ]
        ),
    )
    assert decision.result == "deploy"
    assert "HTTP 503" in decision.reason


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b'{"version":"0.3.0","commit_sha":"","release":"x"}',
        b'{"version":"0.3.0","commit_sha":"' + b"c" * 40 + b'","release":"x"}',
    ],
)
def test_frontend_identity_must_match_the_target(payload):
    opener = FakeOpener(
        [
            backend({"status": "ready", "database": "connected", "commit_sha": COMMIT}),
            frontend(payload),
        ]
    )
    decision = identity.decide(COMMIT, opener)
    assert decision.result == "deploy"
    assert decision.installed_sha == COMMIT


def test_missing_frontend_build_info_never_claims_ready():
    decision = identity.decide(
        COMMIT,
        FakeOpener(
            [
                backend({"status": "ready", "database": "connected", "commit_sha": COMMIT}),
                urllib.error.HTTPError(identity.FRONTEND_IDENTITY_URL, 404, "not found", {}, None),
            ]
        ),
    )
    assert decision.result == "deploy"


def test_cacheable_identity_response_is_not_trusted():
    decision = identity.decide(
        COMMIT,
        FakeOpener(
            [
                backend(
                    {"status": "ready", "database": "connected", "commit_sha": COMMIT},
                    cache="max-age=3600",
                )
            ]
        ),
    )
    assert decision.result == "deploy"
    assert "cached" in decision.reason


def test_oversized_identity_response_is_not_trusted():
    decision = identity.decide(COMMIT, FakeOpener([backend(b"{" + b" " * 5000)]))
    assert decision.result == "deploy"


@pytest.mark.parametrize("error", [TimeoutError("timeout"), OSError("connection reset")])
def test_transport_failures_continue_with_normal_deployment(error):
    decision = identity.decide(COMMIT, FakeOpener([error]))
    assert decision.result == "deploy"


@pytest.mark.parametrize(
    "error",
    [
        ssl.SSLCertVerificationError("untrusted certificate"),
        ssl.SSLError("handshake failed"),
        urllib.error.URLError(ssl.SSLCertVerificationError("hostname mismatch")),
        urllib.error.HTTPError(identity.IDENTITY_URL, 302, "found", {}, None),
    ],
)
def test_tls_redirect_and_trusted_origin_violations_are_security_errors(error):
    with pytest.raises(identity.SecurityError):
        identity.decide(COMMIT, FakeOpener([error]))


def test_unexpected_response_origin_is_a_security_error():
    wrong = FakeResponse(
        "https://example.com/health/identity",
        b'{"status":"ready","database":"connected","commit_sha":"' + COMMIT.encode() + b'"}',
    )
    with pytest.raises(identity.SecurityError):
        identity.decide(COMMIT, FakeOpener([wrong]))


def test_invalid_target_sha_is_rejected():
    with pytest.raises(ValueError):
        identity.decide("abc")


def test_main_writes_github_outputs_and_exit_codes(monkeypatch, tmp_path):
    opener = matched_opener()
    monkeypatch.setattr(identity, "build_opener", lambda: opener)
    output = tmp_path / "github-output"
    assert identity.main(["--sha", COMMIT, "--github-output", str(output)]) == 0
    text = output.read_text()
    assert "decision=already_deployed" in text
    assert f"installed_sha={COMMIT}" in text
    assert "reason=" in text


def test_main_fails_on_security_errors(monkeypatch, tmp_path, capsys):
    opener = FakeOpener([ssl.SSLCertVerificationError("untrusted certificate")])
    monkeypatch.setattr(identity, "build_opener", lambda: opener)
    output = tmp_path / "github-output"
    assert identity.main(["--sha", COMMIT, "--github-output", str(output)]) == 2
    assert "security check failed" in capsys.readouterr().err
    assert not output.exists()


def test_default_opener_verifies_tls_and_disables_redirects_proxy(monkeypatch):
    captured = {}

    def fake_build_opener(*handlers):
        captured["handlers"] = handlers
        return object()

    monkeypatch.setattr(identity.urllib.request, "build_opener", fake_build_opener)
    identity.build_opener()
    handlers = captured["handlers"]
    https = next(
        handler for handler in handlers if isinstance(handler, urllib.request.HTTPSHandler)
    )
    assert https._context.check_hostname
    assert https._context.verify_mode == ssl.CERT_REQUIRED
    assert any(isinstance(handler, identity.NoRedirect) for handler in handlers)
    assert any(isinstance(handler, urllib.request.ProxyHandler) for handler in handlers)
