"""Offline release trust boundary; network/CLI are mocked only in these unit tests."""

import hashlib
import io
import json
import sys
import tarfile
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from scripts import sentry_release
from scripts.release_bundle import payload_names, sha256
from tests.test_release_bundle import IDENTITY, VERSION, _bundle


@pytest.fixture
def release_pair(tmp_path):
    release = tmp_path / "release"
    _bundle(release)
    private = tmp_path / "private"
    (private / "assets").mkdir(parents=True)
    debug = "a" * 8 + "-" + "b" * 4 + "-" + "c" * 4 + "-" + "d" * 4 + "-" + "e" * 12
    files = {
        "assets/index-test.js": f"//# debugId={debug}\n".encode(),
        "assets/index-test.js.map": json.dumps({"version": 3, "debug_id": debug}).encode(),
    }
    for name, body in files.items():
        (private / name).write_bytes(body)
    (private / "manifest.json").write_text(
        json.dumps(
            {
                "identity": IDENTITY,
                "files": {
                    name: {"sha256": hashlib.sha256(body).hexdigest(), "debug_id": debug}
                    for name, body in files.items()
                },
            }
        )
    )
    archive_path = release / f"alxprgs-sso-frontend-{VERSION}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, body in {
            "index.html": b"synthetic",
            "build-info.json": json.dumps(IDENTITY).encode(),
            "assets/index-test.js": files["assets/index-test.js"],
        }.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(body)
            archive.addfile(entry, io.BytesIO(body))
    manifest = json.loads((release / "release-manifest.json").read_text())
    manifest.update(tag=f"v{VERSION}", source_tree_dirty=False)
    manifest["artifacts"][archive_path.name] = {
        "sha256": sha256(archive_path),
        "size_bytes": archive_path.stat().st_size,
    }
    (release / "release-manifest.json").write_text(json.dumps(manifest))
    (release / "SHA256SUMS.txt").write_text(
        "".join(
            f"{sha256(release / name)}  {name}\n"
            for name in sorted(payload_names(VERSION) | {"release-manifest.json"})
        )
    )
    return release, private


def arguments(monkeypatch, pair, upload=False):
    release, private = pair
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sentry_release",
            "--release-dir",
            str(release),
            "--private-maps",
            str(private),
            "--expected-sha",
            "a" * 40,
            "--repository",
            "owner/sso",
        ]
        + (["--upload"] if upload else []),
    )


def test_offline_validation_never_reads_token_or_mutates_network(monkeypatch, release_pair):
    arguments(monkeypatch, release_pair)
    monkeypatch.setattr(sentry_release, "api", lambda *args: pytest.fail("Offline mode called API"))
    monkeypatch.setattr(
        sentry_release.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Offline mode invoked CLI"),
    )
    assert sentry_release.main() == 0


def test_enabled_upload_requires_credentials(monkeypatch, release_pair):
    arguments(monkeypatch, release_pair, upload=True)
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        sentry_release, "api", lambda *args: pytest.fail("Missing token called API")
    )
    assert sentry_release.main() == 1


def test_server_processing_failure_prevents_finalize(monkeypatch, release_pair):
    arguments(monkeypatch, release_pair, upload=True)
    for name, value in {
        "SENTRY_AUTH_TOKEN": "synthetic-ci-credential",
        "SENTRY_ORG": "test-org",
        "SENTRY_PROJECT_BACKEND": "backend",
        "SENTRY_PROJECT_FRONTEND": "frontend",
        "SENTRY_URL": "https://de.sentry.io/",
    }.items():  # pragma: allowlist secret -- synthetic unit credential
        monkeypatch.setenv(name, value)
    calls = []

    def api(url, method, payload, token):
        calls.append(method)
        return {"version": IDENTITY["release"], "ref": "a" * 40}

    monkeypatch.setattr(sentry_release, "api", api)

    def failed_cli(command, **kwargs):
        assert "--strict" in command and "--wait-for" in command and "--no-rewrite" in command
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(sentry_release.subprocess, "run", failed_cli)
    assert sentry_release.main() == 1
    assert calls == ["GET"]


@pytest.mark.parametrize("released", [None, "2026-10-01T00:00:00Z"])
def test_create_is_unfinalized_and_retry_preserves_release_date(
    monkeypatch, release_pair, released
):
    arguments(monkeypatch, release_pair, upload=True)
    for name, value in {
        "SENTRY_AUTH_TOKEN": "synthetic-ci-credential",
        "SENTRY_ORG": "test-org",
        "SENTRY_PROJECT_BACKEND": "backend",
        "SENTRY_PROJECT_FRONTEND": "frontend",
        "SENTRY_URL": "https://de.sentry.io/",
    }.items():  # pragma: allowlist secret -- synthetic unit credential
        monkeypatch.setenv(name, value)
    calls = []
    state = {
        "version": IDENTITY["release"],
        "ref": "a" * 40,
        "url": "https://github.com/owner/sso/commit/" + "a" * 40,
        "lastCommit": {"id": "a" * 40},
        "dateReleased": released,
        "projects": [{"slug": "backend"}, {"slug": "frontend"}],
    }

    def api(url, method, payload, token):
        calls.append(method)
        if len(calls) == 1 and released is None:
            raise HTTPError(url, 404, "Not found", {}, None)
        if method == "POST":
            assert payload["dateReleased"] is None
            assert payload["commits"] == [{"id": "a" * 40}]
            assert "refs" not in payload
        return state

    def successful_cli(*args, **kwargs):
        calls.append("UPLOAD")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sentry_release, "api", api)
    monkeypatch.setattr(sentry_release.subprocess, "run", successful_cli)
    assert sentry_release.main() == 0
    assert calls == (
        ["GET", "POST", "UPLOAD", "GET", "PUT"] if released is None else ["GET", "UPLOAD", "GET"]
    )


def test_private_map_corruption_rejected_before_network(monkeypatch, release_pair):
    arguments(monkeypatch, release_pair, upload=True)
    (release_pair[1] / "assets/index-test.js.map").write_text("corrupt")
    monkeypatch.setattr(sentry_release, "api", lambda *args: pytest.fail("Corrupt maps called API"))
    assert sentry_release.main() == 1
