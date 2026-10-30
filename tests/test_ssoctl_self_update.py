"""Contract regressions for the ssoctl parser fix and self-update source trust.

HTTP and subprocess outputs are synthetic; no GitHub credential, production
server or installed operator is touched by this module.
"""

import argparse
import base64
import contextlib
import hashlib
import http.client
import importlib.util
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sso_ec2", ROOT / "deploy/ec2/ssoctl.py")
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)

SOURCE = (ROOT / "deploy/ec2/ssoctl.py").read_bytes()
COMMIT = hashlib.sha1(b"self-update main", usedforsecurity=False).hexdigest()
OTHER = hashlib.sha1(b"self-update other", usedforsecurity=False).hexdigest()
TOKEN_VALUE = "github_pat_" + "s" * 24


def current_uid() -> int:
    return os.getuid() if hasattr(os, "getuid") else 0


def current_gid() -> int:
    return os.getgid() if hasattr(os, "getgid") else 0


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def commit_document(sha: str, *, tree: str | None = None) -> dict:
    return {"sha": sha, "commit": {"tree": {"sha": tree or "c" * 40}, "message": "synthetic"}}


def compare_document(base: str, status: str = "ahead") -> dict:
    # GitHub returns no head_commit for commit...branch; the merge base proves ancestry.
    return {
        "status": status,
        "base_commit": {"sha": base},
        "merge_base_commit": {"sha": base},
        "ahead_by": 0 if status == "identical" else 3,
        "behind_by": 0,
        "total_commits": 0 if status == "identical" else 3,
        "commits": [],
        "files": [],
    }


def contents_document(data: bytes, **overrides) -> dict:
    document = {
        "type": "file",
        "path": ctl.GITHUB_OPERATOR,
        "encoding": "base64",
        "content": base64.encodebytes(data).decode(),
        "size": len(data),
        "sha": git_blob(data),
    }
    document.update(overrides)
    return document


class FakeResponse:
    def __init__(self, payload: bytes, *, status: int = 200, url: str | None = None):
        self.payload = payload
        self.status = status
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, amount: int = -1) -> bytes:
        return self.payload if amount < 0 else self.payload[:amount]

    def geturl(self) -> str:
        return self.url or ""


class FakeOpener:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[int] = []

    def open(self, request: urllib.request.Request, timeout: int | None = None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        if not self.response.url:
            self.response.url = request.full_url
        return self.response


@pytest.fixture
def token(tmp_path, monkeypatch):
    path = tmp_path / "github-read.token"
    path.write_text(TOKEN_VALUE + "\n", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(ctl, "GITHUB_TOKEN", path)
    monkeypatch.setattr(ctl, "ROOT_UID", current_uid())
    monkeypatch.setattr(ctl, "ROOT_GID", current_gid())
    return path


def install_fake_api(monkeypatch, opener: FakeOpener):
    monkeypatch.setattr(ctl, "_github_opener", lambda: opener)
    return opener


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(ROOT / "deploy/ec2/ssoctl.py"), *args],
        cwd=cwd or ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_real_entrypoint_help_succeeds_without_root(tmp_path):
    result = run_cli("--help", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "recover-admin" in result.stdout
    assert "self-update" in result.stdout
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_recover_admin_help_keeps_required_interface(tmp_path):
    result = run_cli("recover-admin", "--help", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    for expected in (
        "--username",
        "--reason",
        "--confirm",
        "lost_factor",
        "compromised",
        "owner_request",
    ):
        assert expected in result.stdout


def test_self_update_help_shows_only_the_fixed_sha_option(tmp_path):
    result = run_cli("self-update", "--help", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--sha" in result.stdout
    assert "--url" not in result.stdout
    assert "--repo" not in result.stdout
    assert "--path" not in result.stdout
    assert "--branch" not in result.stdout


@pytest.mark.parametrize("value", ["abc", "main", "v1.0.0", "A" * 40, "a" * 39, "a" * 41])
def test_real_entrypoint_rejects_invalid_sha_before_sudo(tmp_path, value):
    result = run_cli("self-update", "--sha", value, cwd=tmp_path)
    assert result.returncode == 2
    assert "full 40-character lowercase hexadecimal commit SHA" in result.stderr
    assert "Run with sudo" not in result.stderr


def test_parser_builds_and_registers_each_command_once():
    # Before the fix build_parser() itself raised: conflicting subparser recover-admin.
    parser = ctl.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(ctl.REQUIRED_COMMANDS) <= set(sub.choices)
    assert len(list(sub.choices)) == len(set(sub.choices))
    assert ctl.REQUIRED_COMMANDS.count("recover-admin") == 1


def test_recover_admin_arguments_and_choices_are_preserved():
    parser = ctl.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    recover = sub.choices["recover-admin"]
    required = {action.dest for action in recover._actions if action.required}
    assert required == {"username", "reason", "confirm"}
    reason = next(action for action in recover._actions if action.dest == "reason")
    assert tuple(reason.choices) == ("lost_factor", "compromised", "owner_request")


def test_self_update_parser_has_no_arbitrary_source_or_destination_arguments():
    parser = ctl.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    update = sub.choices["self-update"]
    options = {action.dest: action for action in update._actions}
    assert set(options) == {"help", "sha"}
    assert options["sha"].required is False
    assert options["sha"].type is ctl.commit_sha
    assert all(action.option_strings for action in update._actions)


def test_help_parsing_has_no_network_docker_or_file_side_effects(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["ssoctl", "--help"])
    monkeypatch.setattr(ctl, "_github_opener", lambda: pytest.fail("network must not start"))
    monkeypatch.setattr(ctl, "run", lambda *a, **k: pytest.fail("command must not run"))
    monkeypatch.setattr(
        ctl.os, "geteuid", lambda: pytest.fail("root check must not run"), raising=False
    )
    original = Path.cwd()
    os.chdir(tmp_path)
    try:
        with pytest.raises(SystemExit) as stop:
            ctl.main()
    finally:
        os.chdir(original)
    assert stop.value.code == 0
    assert list(tmp_path.iterdir()) == []


def test_self_update_requires_root_sudo(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ssoctl", "self-update"])
    monkeypatch.setattr(ctl.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(ctl, "self_update", lambda requested: pytest.fail("must not run"))
    with pytest.raises(SystemExit) as stop:
        ctl.main()
    assert stop.value.code == 2
    assert "Run with sudo" in capsys.readouterr().err


def test_main_dispatches_self_update_inside_the_shared_operator_lock(monkeypatch, capsys):
    observed = {"locked": False, "called": False}

    @contextlib.contextmanager
    def fake_locked():
        observed["locked"] = True
        try:
            yield
        finally:
            observed["locked"] = False

    def fake_update(requested):
        observed["called"] = True
        assert observed["locked"] is True
        assert requested == COMMIT

    monkeypatch.setattr(sys, "argv", ["ssoctl", "self-update", "--sha", COMMIT])
    monkeypatch.setattr(ctl.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(ctl, "locked", fake_locked)
    monkeypatch.setattr(ctl, "self_update", fake_update)
    previous_umask = os.umask(0o022)
    try:
        assert ctl.main() == 0
    finally:
        os.umask(previous_umask)
    assert observed == {"locked": False, "called": True}


def test_failed_self_update_does_not_send_email(monkeypatch, capsys):
    @contextlib.contextmanager
    def fake_locked():
        yield

    def fail_update(requested):
        raise ctl.OperationError("synthetic self-update failure")

    monkeypatch.setattr(sys, "argv", ["ssoctl", "self-update"])
    monkeypatch.setattr(ctl.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(ctl, "locked", fake_locked)
    monkeypatch.setattr(ctl, "self_update", fail_update)
    monkeypatch.setattr(ctl, "notify", lambda event: pytest.fail("email must not be sent"))
    previous_umask = os.umask(0o022)
    try:
        assert ctl.main() == 1
    finally:
        os.umask(previous_umask)
    assert "synthetic self-update failure" in capsys.readouterr().err


def test_fixed_trusted_source_constants_are_not_configurable():
    assert ctl.GITHUB_API == "https://api.github.com"
    assert ctl.GITHUB_REPO == "alxprgstech/sso"
    assert ctl.GITHUB_BRANCH == "main"
    assert ctl.GITHUB_OPERATOR == "deploy/ec2/ssoctl.py"
    assert ctl.ROOT_UID == 0 and ctl.ROOT_GID == 0
    assert ctl.GITHUB_TOKEN.as_posix().startswith("/etc/alxprgs-sso/")
    assert "self-update" not in ctl.EVENTS


def test_github_api_uses_fixed_origin_and_header_only_credentials(token, monkeypatch):
    payload = {"sha": COMMIT}
    opener = install_fake_api(monkeypatch, FakeOpener(FakeResponse(json.dumps(payload).encode())))
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("GITHUB_API_URL", "https://evil.invalid")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-environment-token")
    assert ctl.github_api("/repos/x/y/commits/main") == payload
    request = opener.requests[0]
    assert request.full_url == "https://api.github.com/repos/x/y/commits/main"
    assert request.get_header("Authorization") == f"Bearer {TOKEN_VALUE}"
    assert TOKEN_VALUE not in request.full_url
    assert opener.timeouts == [ctl.HTTP_TIMEOUT]


def test_redirect_handler_refuses_every_redirect():
    handler = ctl._NoRedirect()
    assert handler.redirect_request(object(), None, 302, "", {}, "https://evil.invalid") is None


def test_opener_disables_environment_proxy_and_redirects(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setattr(ctl, "_tls_context", ssl.create_default_context)
    opener = ctl._github_opener()
    # An explicitly empty ProxyHandler suppresses the environment-derived default;
    # the empty handler itself registers no proxy_open hooks.
    assert not any(isinstance(h, urllib.request.ProxyHandler) for h in opener.handlers)
    assert any(isinstance(h, ctl._NoRedirect) for h in opener.handlers)
    assert not any(type(h) is urllib.request.HTTPRedirectHandler for h in opener.handlers)


@pytest.mark.skipif(
    not Path(ssl.get_default_verify_paths().cafile or "").is_file(),
    reason="platform Python has no CA bundle file",
)
def test_tls_context_uses_fixed_bundle_verification(monkeypatch):
    monkeypatch.setattr(ctl, "CA_BUNDLE", Path(ssl.get_default_verify_paths().cafile or ""))
    context = ctl._tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_tls_context_without_system_bundle_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(ctl, "CA_BUNDLE", tmp_path / "missing-ca.pem")
    with pytest.raises(ctl.OperationError, match="CA bundle"):
        ctl._tls_context()


def test_github_api_rejects_redirect_status_size_and_metadata(token, monkeypatch):
    monkeypatch.setattr(
        ctl, "_github_opener", lambda: FakeOpener(FakeResponse(b"{}", url="https://evil.invalid"))
    )
    with pytest.raises(ctl.OperationError, match="redirected"):
        ctl.github_api("/x")
    install_fake_api(
        monkeypatch,
        FakeOpener(FakeResponse(json.dumps({"sha": COMMIT}).encode(), status=201)),
    )
    with pytest.raises(ctl.OperationError, match="HTTP 201"):
        ctl.github_api("/x")
    install_fake_api(
        monkeypatch, FakeOpener(FakeResponse(b"{" + b"a" * ctl.MAX_RESPONSE_BYTES + b"}"))
    )
    with pytest.raises(ctl.OperationError, match="size limit"):
        ctl.github_api("/x")
    install_fake_api(monkeypatch, FakeOpener(FakeResponse(b"not-json")))
    with pytest.raises(ctl.OperationError, match="invalid metadata"):
        ctl.github_api("/x")
    install_fake_api(monkeypatch, FakeOpener(FakeResponse(b"[]")))
    with pytest.raises(ctl.OperationError, match="invalid metadata"):
        ctl.github_api("/x")


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (401, "rejected the read token"),
        (403, "rejected the read token"),
        (404, "not found"),
        (500, "HTTP 500"),
    ],
)
def test_http_failures_are_sanitized(token, monkeypatch, code, message):
    error = urllib.error.HTTPError("https://api.github.com/x", code, "synthetic", {}, None)
    install_fake_api(monkeypatch, FakeOpener(error=error))
    with pytest.raises(ctl.OperationError, match=message) as failure:
        ctl.github_api("/x")
    assert TOKEN_VALUE not in str(failure.value)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError(ssl.SSLCertVerificationError("certificate verify failed")),
        TimeoutError("timed out"),
        http.client.IncompleteRead(b"partial", 10),
    ],
)
def test_network_and_tls_failures_are_sanitized(token, monkeypatch, error):
    install_fake_api(monkeypatch, FakeOpener(error=error))
    with pytest.raises(ctl.OperationError, match="unreachable") as failure:
        ctl.github_api("/x")
    assert TOKEN_VALUE not in str(failure.value)


def test_missing_token_fails_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(ctl, "GITHUB_TOKEN", tmp_path / "absent-token")
    monkeypatch.setattr(ctl, "_github_opener", lambda: pytest.fail("network must not start"))
    with pytest.raises(ctl.OperationError, match="missing"):
        ctl.github_api("/x")


def test_token_requires_private_mode(token):
    if os.name == "nt":
        pytest.skip("POSIX file modes are checked on Linux")
    token.chmod(0o644)
    with pytest.raises(ctl.OperationError, match="mode 0600"):
        ctl.github_token()


def test_token_must_not_be_a_symlink(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("symlink creation requires privileges on Windows")
    target = tmp_path / "token-target"
    target.write_text(TOKEN_VALUE, encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "token-link"
    link.symlink_to(target)
    monkeypatch.setattr(ctl, "GITHUB_TOKEN", link)
    monkeypatch.setattr(ctl, "ROOT_UID", current_uid())
    with pytest.raises(ctl.OperationError, match="regular"):
        ctl.github_token()


def test_token_must_be_owned_by_root(token, monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows reports a synthetic owner")
    monkeypatch.setattr(ctl, "ROOT_UID", current_uid() + 1)
    with pytest.raises(ctl.OperationError, match="owned by root"):
        ctl.github_token()


def test_token_rejects_invalid_size_and_format(token, monkeypatch):
    token.write_text("short", encoding="utf-8")
    with pytest.raises(ctl.OperationError, match="size"):
        ctl.github_token()
    token.write_text("!" * 24, encoding="utf-8")
    with pytest.raises(ctl.OperationError, match="format"):
        ctl.github_token()


def test_valid_token_is_returned(token):
    assert ctl.github_token() == TOKEN_VALUE


def test_resolve_without_sha_pins_main_to_one_immutable_revision(monkeypatch):
    calls: list[str] = []

    def api(path):
        calls.append(path)
        if path == f"/repos/{ctl.GITHUB_REPO}/commits/{ctl.GITHUB_BRANCH}":
            return commit_document(COMMIT)
        if path == f"/repos/{ctl.GITHUB_REPO}/contents/{ctl.GITHUB_OPERATOR}?ref={COMMIT}":
            return contents_document(SOURCE)
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(ctl, "github_api", api)
    revision = ctl.resolve_revision(None)
    assert revision == COMMIT
    assert ctl.download_operator(revision) == SOURCE
    assert calls.count(f"/repos/{ctl.GITHUB_REPO}/commits/{ctl.GITHUB_BRANCH}") == 1
    assert not any("ref=main" in path or path.endswith("/main") for path in calls[1:])


def test_main_advance_after_resolution_does_not_mix_revisions(monkeypatch):
    main_calls = 0

    def api(path):
        nonlocal main_calls
        if path == f"/repos/{ctl.GITHUB_REPO}/commits/{ctl.GITHUB_BRANCH}":
            main_calls += 1
            if main_calls > 1:
                raise AssertionError("main must not be resolved twice")
            return commit_document(COMMIT)
        if path == f"/repos/{ctl.GITHUB_REPO}/contents/{ctl.GITHUB_OPERATOR}?ref={COMMIT}":
            return contents_document(SOURCE)
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(ctl, "github_api", api)
    revision = ctl.resolve_revision(None)
    assert ctl.download_operator(revision) == SOURCE
    assert main_calls == 1


@pytest.mark.parametrize("status", ["ahead", "identical"])
def test_explicit_sha_inside_main_history_is_accepted(monkeypatch, status):
    def api(path):
        if path == f"/repos/{ctl.GITHUB_REPO}/commits/{COMMIT}":
            return commit_document(COMMIT)
        if path == f"/repos/{ctl.GITHUB_REPO}/compare/{COMMIT}...{ctl.GITHUB_BRANCH}":
            return compare_document(COMMIT, status=status)
        if path == f"/repos/{ctl.GITHUB_REPO}/contents/{ctl.GITHUB_OPERATOR}?ref={COMMIT}":
            return contents_document(SOURCE)
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(ctl, "github_api", api)
    assert ctl.resolve_revision(COMMIT) == COMMIT
    assert ctl.download_operator(COMMIT) == SOURCE


@pytest.mark.parametrize(
    "comparison",
    [
        compare_document(COMMIT, status="behind"),
        compare_document(COMMIT, status="diverged"),
        {**compare_document(COMMIT), "base_commit": {"sha": OTHER}},
        {**compare_document(COMMIT), "merge_base_commit": {"sha": OTHER}},
        {
            key: value
            for key, value in compare_document(COMMIT).items()
            if key != "merge_base_commit"
        },
        {**compare_document(COMMIT), "behind_by": 2},
        {**compare_document(COMMIT), "ahead_by": "many"},
    ],
)
def test_explicit_sha_outside_main_history_is_rejected_before_download(monkeypatch, comparison):
    downloaded = []

    def api(path):
        if path == f"/repos/{ctl.GITHUB_REPO}/commits/{COMMIT}":
            return commit_document(COMMIT)
        if path == f"/repos/{ctl.GITHUB_REPO}/compare/{COMMIT}...{ctl.GITHUB_BRANCH}":
            return comparison
        downloaded.append(path)
        raise AssertionError(f"download must not start: {path}")

    monkeypatch.setattr(ctl, "github_api", api)
    with pytest.raises(ctl.OperationError, match="main history"):
        ctl.resolve_revision(COMMIT)
    assert downloaded == []


@pytest.mark.parametrize(
    "document",
    [
        commit_document(OTHER),
        {"sha": COMMIT},
        {"sha": COMMIT, "commit": {"tree": {"sha": "not-a-sha"}}},
        {"sha": COMMIT.upper(), "commit": {"tree": {"sha": COMMIT}}},
    ],
)
def test_commit_metadata_must_be_consistent(monkeypatch, document):
    monkeypatch.setattr(ctl, "github_api", lambda path: document)
    with pytest.raises(ctl.OperationError, match="commit identity|requested SHA"):
        ctl.resolve_revision(COMMIT)


@pytest.mark.parametrize("value", ["abc", "main", "a" * 39, "A" * 40, "a" * 41])
def test_resolve_rejects_invalid_sha_without_network(monkeypatch, value):
    monkeypatch.setattr(ctl, "github_api", lambda path: pytest.fail("network must not start"))
    with pytest.raises(ctl.OperationError, match="full 40-character"):
        ctl.resolve_revision(value)


def test_download_operator_returns_exact_verified_content(monkeypatch):
    monkeypatch.setattr(ctl, "github_api", lambda path: contents_document(SOURCE))
    assert ctl.download_operator(COMMIT) == SOURCE
    path_checked = []

    def api(path):
        path_checked.append(path)
        return contents_document(SOURCE)

    monkeypatch.setattr(ctl, "github_api", api)
    ctl.download_operator(COMMIT)
    assert path_checked == [f"/repos/{ctl.GITHUB_REPO}/contents/{ctl.GITHUB_OPERATOR}?ref={COMMIT}"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "dir"},
        {"path": "deploy/ec2/other.py"},
        {"encoding": "none"},
        {"size": 1},
        {"size": 0},
        {"size": ctl.MAX_OPERATOR_BYTES + 1},
        {"sha": "c" * 40},
        {"content": "not base64!"},
        {"content": base64.b64encode(b"short").decode(), "size": 10},
        {"content": "", "size": 10},
    ],
)
def test_download_rejects_inconsistent_metadata(monkeypatch, overrides):
    monkeypatch.setattr(ctl, "github_api", lambda path: contents_document(SOURCE, **overrides))
    with pytest.raises(ctl.OperationError):
        ctl.download_operator(COMMIT)


def test_download_rejects_invalid_revision_without_network(monkeypatch):
    monkeypatch.setattr(ctl, "github_api", lambda path: pytest.fail("network must not start"))
    with pytest.raises(ctl.OperationError, match="Invalid operator revision"):
        ctl.download_operator("main")


@pytest.fixture
def portable_operator(tmp_path, monkeypatch):
    root = tmp_path / "opt"
    tools = root / "tools"
    state = tmp_path / "state"
    tools.mkdir(parents=True)
    state.mkdir()
    path = tools / "ssoctl.py"
    path.write_bytes(SOURCE)
    path.chmod(0o755)
    monkeypatch.setattr(ctl, "ROOT", root)
    monkeypatch.setattr(ctl, "STATE", state)
    monkeypatch.setattr(ctl, "SYSTEM_PYTHON", Path(sys.executable))
    monkeypatch.setattr(ctl, "ROOT_UID", current_uid())
    monkeypatch.setattr(ctl, "ROOT_GID", current_gid())
    monkeypatch.setattr(ctl, "resolve_revision", lambda requested: COMMIT)
    monkeypatch.setattr(ctl, "download_operator", lambda revision: SOURCE)
    return root, state, path


def test_identical_content_is_a_successful_noop_without_backup(
    portable_operator, monkeypatch, capsys
):
    root, state, path = portable_operator
    before = path.stat()
    monkeypatch.setattr(ctl, "run", lambda *a, **k: pytest.fail("application command must not run"))
    monkeypatch.setattr(ctl, "settings", lambda: pytest.fail("configuration must not be read"))
    monkeypatch.setattr(ctl, "current", lambda: pytest.fail("release must not be resolved"))
    monkeypatch.setattr(ctl, "notify", lambda event: pytest.fail("email must not be sent"))
    ctl.self_update(None)
    after = path.stat()
    output = capsys.readouterr().out
    assert "already current" in output
    assert COMMIT in output
    assert before.st_ino == after.st_ino
    assert before.st_mtime_ns == after.st_mtime_ns
    assert not (state / "operator-backups").exists()
    assert not (root / "releases").exists()
    assert not list((root / "tools").glob(".ssoctl-candidate-*"))
    assert "application" in output.lower()


@pytest.mark.parametrize(
    "candidate",
    [
        b"",
        b"def broken(:\n",
        (
            b"import argparse\n"
            b"parser = argparse.ArgumentParser()\n"
            b"sub = parser.add_subparsers(dest='command')\n"
            b"sub.add_parser('recover-admin')\n"
            b"sub.add_parser('recover-admin')\n"
        ),
        b"import argparse\nargparse.ArgumentParser().parse_args()\n",
        b"raise SystemExit(3)\n",
    ],
    ids=["empty", "syntax", "argparse-conflict", "missing-interface", "help-fails"],
)
def test_candidate_is_rejected_before_replacement(portable_operator, monkeypatch, candidate):
    root, state, path = portable_operator
    before = path.stat()
    monkeypatch.setattr(ctl, "download_operator", lambda revision: candidate)
    with pytest.raises(ctl.OperationError):
        ctl.self_update(None)
    after = path.stat()
    assert before.st_ino == after.st_ino
    assert before.st_mtime_ns == after.st_mtime_ns
    assert path.read_bytes() == SOURCE
    assert not (state / "operator-backups").exists()
    assert not list((root / "tools").glob(".ssoctl-candidate-*"))


def test_hanging_help_is_bounded_by_timeout(portable_operator, monkeypatch):
    root, state, path = portable_operator
    monkeypatch.setattr(ctl, "download_operator", lambda revision: b"import time\ntime.sleep(60)\n")
    monkeypatch.setattr(ctl, "HELP_TIMEOUT", 0.5)
    with pytest.raises(ctl.OperationError, match="could not run"):
        ctl.self_update(None)
    assert path.read_bytes() == SOURCE
    assert not (state / "operator-backups").exists()
    assert not list((root / "tools").glob(".ssoctl-candidate-*"))


@pytest.mark.parametrize("failure", ["HTTP 404", "unreachable", "invalid metadata"])
def test_download_failure_keeps_installed_operator(portable_operator, monkeypatch, failure):
    root, state, path = portable_operator
    before = path.read_bytes()

    def fail(revision):
        raise ctl.OperationError(failure)

    monkeypatch.setattr(ctl, "download_operator", fail)
    with pytest.raises(ctl.OperationError, match=failure):
        ctl.self_update(None)
    assert path.read_bytes() == before
    assert not (state / "operator-backups").exists()
    assert not list((root / "tools").glob(".ssoctl-candidate-*"))


def test_resolution_failure_keeps_installed_operator(portable_operator, monkeypatch):
    root, state, path = portable_operator
    before = path.read_bytes()

    def fail(requested):
        raise ctl.OperationError("Requested commit is not in main history")

    monkeypatch.setattr(ctl, "resolve_revision", fail)
    monkeypatch.setattr(ctl, "download_operator", lambda revision: pytest.fail("no download"))
    with pytest.raises(ctl.OperationError, match="main history"):
        ctl.self_update(OTHER)
    assert path.read_bytes() == before
    assert not (state / "operator-backups").exists()


def test_bootstrap_has_no_self_update_sudoers_or_wrapper_change():
    bootstrap = (ROOT / "deploy/ec2/bootstrap.sh").read_text(encoding="utf-8")
    assert "NOPASSWD: /usr/local/sbin/ssoctl deploy *" in bootstrap
    assert "self-update" not in bootstrap
    assert "ssoctl.py" in bootstrap
    operator = (ROOT / "deploy/ec2/ssoctl.py").read_text(encoding="utf-8")
    assert operator.count('add_parser("recover-admin")') == 1
