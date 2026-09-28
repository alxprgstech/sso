"""Offline negative checks for the common release bundle verifier."""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.release_bundle import (
    ReleaseError,
    empty_output,
    package_version,
    payload_names,
    sha256,
    source_identity,
    verify,
)

VERSION = "0.2.0"


def test_prerelease_package_names_use_pep440() -> None:
    assert package_version("0.3.0-rc.2") == "0.3.0rc2"
    assert "alxprgs_sso-0.3.0rc2-py3-none-any.whl" in payload_names("0.3.0-rc.2")
    assert "alxprgs-sso-frontend-0.3.0-rc.2.tar.gz" in payload_names("0.3.0-rc.2")
    with pytest.raises(ReleaseError, match="Unsupported"):
        payload_names("0.3.0-rc.0")


def _tar(path: Path, name: str) -> None:
    with tarfile.open(path, "w:gz") as archive:
        body = b"synthetic"
        entry = tarfile.TarInfo(name)
        entry.size = len(body)
        archive.addfile(entry, io.BytesIO(body))


def _bundle(path: Path) -> None:
    path.mkdir()
    for name in payload_names(VERSION):
        target = path / name
        if name.endswith(".whl"):
            with zipfile.ZipFile(target, "w") as archive:
                member = "app/main.py" if "backend" in name else "alxprgs_sso/client.py"
                archive.writestr(member, "# synthetic\n")
        elif name.endswith("migrations-0.2.0.tar.gz"):
            with tarfile.open(target, "w:gz") as archive:
                for member in ("alembic.ini", "alembic/versions/0001.py"):
                    content = b"synthetic"
                    entry = tarfile.TarInfo(member)
                    entry.size = len(content)
                    archive.addfile(entry, io.BytesIO(content))
        elif name.endswith("frontend-0.2.0.tar.gz"):
            _tar(target, "index.html")
        elif name.endswith(".tar.gz"):
            _tar(target, "package/README.md")
        else:
            target.write_text("synthetic release instructions\n", encoding="utf-8")
    manifest = {
        "version": VERSION,
        "commit_sha": "a" * 40,
        "artifacts": {
            name: {"sha256": sha256(path / name), "size_bytes": (path / name).stat().st_size}
            for name in payload_names(VERSION)
        },
    }
    (path / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (path / "SHA256SUMS.txt").write_text(
        "".join(
            f"{sha256(path / name)}  {name}\n"
            for name in sorted(payload_names(VERSION) | {"release-manifest.json"})
        ),
        encoding="utf-8",
    )


def test_verifier_accepts_complete_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _bundle(bundle)
    assert verify(bundle, expected_sha="a" * 40)["version"] == VERSION


@pytest.mark.parametrize("mutation", ["missing", "corrupt", "checksums", "manifest_sha"])
def test_verifier_rejects_broken_bundle(tmp_path: Path, mutation: str) -> None:
    bundle = tmp_path / "bundle"
    _bundle(bundle)
    target = bundle / "MIGRATION.md"
    if mutation == "missing":
        target.unlink()
    elif mutation == "corrupt":
        target.write_text("modified", encoding="utf-8")
    elif mutation == "checksums":
        (bundle / "SHA256SUMS.txt").write_text("", encoding="utf-8")
    else:
        with pytest.raises(ReleaseError, match="SHA mismatch"):
            verify(bundle, expected_sha="b" * 40)
        return
    with pytest.raises((ReleaseError, FileNotFoundError)):
        verify(bundle, expected_sha="a" * 40)


def test_existing_output_is_preserved(tmp_path: Path) -> None:
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "user-file.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ReleaseError, match="empty"):
        empty_output(out)
    assert sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("tag", ["v0.2.1", "v0.2.0;echo unsafe", "missing", "v0.2.0-rc.1"])
def test_invalid_tag_is_rejected_before_lookup(monkeypatch: pytest.MonkeyPatch, tag: str) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> str:
        calls.append(command)
        if command[1:3] == ["rev-parse", "HEAD"]:
            return "a" * 40
        if command[1:3] == ["status", "--porcelain"]:
            return ""
        raise AssertionError("Unsafe tag reached git lookup")

    monkeypatch.setattr("scripts.release_bundle.run", fake_run)
    with pytest.raises(ReleaseError, match="Tag format or version mismatch"):
        source_identity(VERSION, tag, False)
    assert not any("rev-list" in command for command in calls)


def test_well_formed_but_missing_tag_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str]) -> str:
        if command[1:3] == ["rev-parse", "HEAD"]:
            return "a" * 40
        if command[1:3] == ["status", "--porcelain"]:
            return ""
        if "rev-list" in command:
            raise ReleaseError("Commit tag is missing")
        raise AssertionError("Unexpected git command")

    monkeypatch.setattr("scripts.release_bundle.run", fake_run)
    with pytest.raises(ReleaseError, match="missing"):
        source_identity(VERSION, "v0.2.0", False)
