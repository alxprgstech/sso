"""Build and verify a release bundle without publishing or deleting prior data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-rc\.[1-9]\d*)?$")


class ReleaseError(RuntimeError):
    pass


def package_version(version: str) -> str:
    if not TAG_RE.fullmatch(f"v{version}"):
        raise ReleaseError("Unsupported release version")
    return version.replace("-rc.", "rc")


def run(command: list[str], *, cwd: Path = ROOT) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ReleaseError(f"Command failed ({Path(command[0]).name}, exit {result.returncode})")
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_names(version: str) -> set[str]:
    python_version = package_version(version)
    return {
        f"alxprgs_sso_backend-{python_version}-py3-none-any.whl",
        f"alxprgs_sso_backend-{python_version}.tar.gz",
        f"alxprgs_sso-{python_version}-py3-none-any.whl",
        f"alxprgs_sso-{python_version}.tar.gz",
        f"alxprgs-sso-frontend-{version}.tar.gz",
        f"alxprgs-sso-migrations-{version}.tar.gz",
        "MIGRATION.md",
        "RELEASE_NOTES.md",
    }


def release_notes(version: str) -> str:
    source = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", source)
    if not match or not match.group(1).strip():
        raise ReleaseError("Version-specific release notes are missing")
    return match.group(1).strip() + "\n"


def source_identity(version: str, tag: str | None, clean: bool) -> tuple[str, bool]:
    sha = run(["git", "rev-parse", "HEAD"])
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ReleaseError("Invalid commit SHA")
    dirty = bool(run(["git", "status", "--porcelain", "--untracked-files=normal"]))
    if clean and dirty:
        raise ReleaseError("Release checkout must be clean")
    if tag:
        if not TAG_RE.fullmatch(tag) or tag[1:] != version:
            raise ReleaseError("Tag format or version mismatch")
        if run(["git", "rev-list", "-n", "1", f"refs/tags/{tag}"]) != sha:
            raise ReleaseError("Tag does not resolve to checkout SHA")
        run(["git", "merge-base", "--is-ancestor", sha, "origin/main"])
    return sha, dirty


def empty_output(path: Path) -> Path:
    output = path.resolve()
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ReleaseError("Output directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    return output


def archive_tree(archive: tarfile.TarFile, root: Path, prefix: str = "") -> None:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ReleaseError("Symlink in release input")
        if path.is_file():
            archive.add(path, arcname=prefix + path.relative_to(root).as_posix(), recursive=False)


def inspect_packages(output: Path, version: str) -> None:
    python_version = package_version(version)
    with zipfile.ZipFile(
        output / f"alxprgs_sso_backend-{python_version}-py3-none-any.whl"
    ) as archive:
        if "app/main.py" not in archive.namelist():
            raise ReleaseError("Backend wheel lacks entrypoint")
    with zipfile.ZipFile(output / f"alxprgs_sso-{python_version}-py3-none-any.whl") as archive:
        if "alxprgs_sso/client.py" not in archive.namelist():
            raise ReleaseError("SDK wheel lacks client")
    with tarfile.open(output / f"alxprgs-sso-migrations-{version}.tar.gz") as archive:
        names = archive.getnames()
        if "alembic.ini" not in names or not any(n.startswith("alembic/versions/") for n in names):
            raise ReleaseError("Migration archive is incomplete")
    with tarfile.open(output / f"alxprgs-sso-frontend-{version}.tar.gz") as archive:
        if "index.html" not in archive.getnames():
            raise ReleaseError("Frontend archive lacks index.html")


def verify(output: Path, expected_sha: str | None = None) -> dict:
    manifest = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    if expected_sha and manifest["commit_sha"] != expected_sha:
        raise ReleaseError("Manifest SHA mismatch")
    payload = payload_names(version)
    if set(manifest["artifacts"]) != payload:
        raise ReleaseError("Manifest artifact set mismatch")
    actual = {path.name for path in output.iterdir() if path.is_file()}
    if actual != payload | {"release-manifest.json", "SHA256SUMS.txt"}:
        raise ReleaseError("Bundle contains missing or unexpected files")
    for name, metadata in manifest["artifacts"].items():
        path = output / name
        if path.stat().st_size != metadata["size_bytes"] or sha256(path) != metadata["sha256"]:
            raise ReleaseError("Artifact integrity mismatch")
    sums = (output / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    required = {f"{sha256(output / name)}  {name}" for name in payload | {"release-manifest.json"}}
    if set(sums) != required or len(sums) != len(required):
        raise ReleaseError("SHA256SUMS is incomplete or invalid")
    inspect_packages(output, version)
    return manifest


def build(output: Path, tag: str | None = None, require_clean: bool = False) -> dict:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    run([sys.executable, str(ROOT / "scripts" / "bump_version.py"), "check"])
    notes = release_notes(version)
    sha, dirty = source_identity(version, tag, require_clean)
    output = empty_output(output)
    for package in ("backend", "packages/python-sdk"):
        run([sys.executable, "-m", "build", "--no-isolation", package, "--outdir", str(output)])
    frontend = ROOT / "frontend"
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    run([npm, "ci"], cwd=frontend)
    for step in ("lint", "typecheck", "typecheck:tests", "test", "test:components", "build"):
        run([npm, "run", step], cwd=frontend)
    with tarfile.open(output / f"alxprgs-sso-frontend-{version}.tar.gz", "w:gz") as archive:
        archive_tree(archive, frontend / "dist")
    with tarfile.open(output / f"alxprgs-sso-migrations-{version}.tar.gz", "w:gz") as archive:
        archive_tree(archive, ROOT / "backend" / "alembic", "alembic/")
        archive.add(ROOT / "backend" / "alembic.ini", arcname="alembic.ini")
    (output / "RELEASE_NOTES.md").write_text(notes, encoding="utf-8")
    (output / "MIGRATION.md").write_bytes((ROOT / "docs" / "migration.md").read_bytes())
    payload = payload_names(version)
    if {path.name for path in output.iterdir() if path.is_file()} != payload:
        raise ReleaseError("Build produced an incomplete or unexpected payload")
    manifest = {
        "product": "ALXPRGS SSO",
        "version": version,
        "tag": tag,
        "commit_sha": sha,
        "source_tree_dirty": dirty,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            name: {"sha256": sha256(output / name), "size_bytes": (output / name).stat().st_size}
            for name in sorted(payload)
        },
    }
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "SHA256SUMS.txt").write_text(
        "".join(
            f"{sha256(output / name)}  {name}\n"
            for name in sorted(payload | {"release-manifest.json"})
        ),
        encoding="utf-8",
    )
    verify(output, expected_sha=sha)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["build", "verify"])
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    try:
        result = (
            build(args.outdir, args.tag, args.require_clean)
            if args.action == "build"
            else verify(args.outdir, args.expected_sha)
        )
        print(f"Release bundle verified: {result['version']} at {result['commit_sha']}")
        return 0
    except (
        ReleaseError,
        OSError,
        KeyError,
        ValueError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"Release bundle rejected: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
