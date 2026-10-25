"""Build private EC2 transport from this checkout. Images are built only on CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTGRES = (
    "postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
)
# Digest pulls stay unnamed in the classic image store; tag them so the saved
# archive and the loaded server image carry one stable identity everywhere.
POSTGRES_TAG = f"alxprgs-sso-postgres:{POSTGRES.rsplit('sha256:', 1)[1][:12]}"
# Classic-store archives reference configs as "<digest>.json" (Docker <=24) or
# "blobs/sha256/<digest>" (Docker 25+ hybrid docker-archive layout).
CONFIG_REFERENCE = re.compile(r"^(?:([a-f0-9]{64})\.json|blobs/sha256[:/]([a-f0-9]{64}))$")


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def archive_config_digests(archive: Path, expected: set[str]) -> dict[str, str]:
    """Map every expected tag to the config digest stored inside a saved archive.

    The EC2 server runs the classic image store, where a loaded image takes the
    config digest as its ID. The daemon that built the archive may instead report
    manifest digests (containerd image store), so transport identity is derived
    from the archive bytes themselves, never from `docker image inspect`.
    """
    with tarfile.open(archive) as tar:
        if "manifest.json" not in tar.getnames():
            raise ValueError(
                "images.tar is not a classic docker archive; the runner image store "
                "must keep containerd-snapshotter=false so identity matches the server"
            )
        entries = json.loads(tar.extractfile("manifest.json").read())
    if len(entries) != len(expected):
        raise ValueError("images.tar must contain exactly the expected images")
    result: dict[str, str] = {}
    for entry in entries:
        match = CONFIG_REFERENCE.match(entry.get("Config", ""))
        tags = entry.get("RepoTags") or []
        if not match or not all(isinstance(tag, str) for tag in tags):
            # Entries carry only tags and digests; include them for diagnosis.
            raise ValueError(f"images.tar entry without config digest or tags: {entry}")
        digest = match.group(1) or match.group(2)
        for tag in tags:
            if tag in result:
                raise ValueError(f"Duplicate tag in images.tar: {tag}")
            result[tag] = f"sha256:{digest}"
    if set(result) != expected:
        raise ValueError(f"images.tar tags {sorted(result)} do not match {sorted(expected)}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch("[a-f0-9]{40}", args.sha) or run("git", "rev-parse", "HEAD") != args.sha:
        parser.error("SHA must match this checkout")
    if run("git", "status", "--porcelain", "--untracked-files=all"):
        parser.error("Checkout must be clean, including untracked source files")
    os.environ.pop("DOCKER_DEFAULT_PLATFORM", None)
    for name in ("backend", "frontend"):
        subprocess.run(
            [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "--build-arg",
                f"ALX_BUILD_SHA={args.sha}",
                "-f",
                f"{name}/Dockerfile",
                "-t",
                f"alxprgs-sso-{name}:{args.sha}",
                ".",
            ],
            cwd=ROOT,
            check=True,
        )
    subprocess.run(["docker", "pull", "--platform", "linux/amd64", POSTGRES], check=True)
    subprocess.run(["docker", "tag", POSTGRES, POSTGRES_TAG], check=True)
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        for name in ("compose.yml", "nginx.conf"):
            shutil.copyfile(ROOT / "deploy/ec2" / name, stage / name)
        shutil.copytree(ROOT / "deploy/postgres", stage / "postgres")
        scripts = stage / "scripts"
        scripts.mkdir()
        for name in (
            "backup_db.py",
            "restore_db.py",
            "privacy_journal.py",
            "rotate_keys.py",
            "export_deletion_journal.py",
            "prune_backups.py",
        ):
            shutil.copyfile(ROOT / "scripts" / name, scripts / name)
        shutil.copyfile(ROOT / "frontend/csp.conf", stage / "csp.conf")
        container = run("docker", "create", f"alxprgs-sso-frontend:{args.sha}")
        try:
            subprocess.run(
                ["docker", "cp", f"{container}:/usr/share/nginx/html", str(stage / "public")],
                check=True,
            )
        finally:
            subprocess.run(["docker", "rm", container], check=True)
        if list((stage / "public").rglob("*.map")):
            raise ValueError("Source maps must not enter deployment")
        identity = json.loads((stage / "public/build-info.json").read_text())
        if identity["commit_sha"] != args.sha:
            raise ValueError("Frontend source identity mismatch")
        backend_tag = f"alxprgs-sso-backend:{args.sha}"
        subprocess.run(
            [
                "docker",
                "save",
                "-o",
                str(stage / "images.tar"),
                backend_tag,
                POSTGRES_TAG,
            ],
            check=True,
        )
        images = archive_config_digests(stage / "images.tar", {backend_tag, POSTGRES_TAG})
        migrations = hashlib.sha256()
        for path in sorted((ROOT / "backend/alembic").rglob("*.py")):
            migrations.update(path.relative_to(ROOT).as_posix().encode())
            migrations.update(path.read_bytes())
        revision = re.search(
            r'SCHEMA_REVISION = "([A-Za-z0-9_]+)"',
            (ROOT / "backend/app/core/database_policy.py").read_text(),
        )
        if revision is None:
            raise ValueError("Schema guard not found")
        manifest = {
            "sha": args.sha,
            "backend_image": images[backend_tag],
            "postgres_image": images[POSTGRES_TAG],
            "schema_revision": revision[1],
            "migrations": migrations.hexdigest(),
            "image_bytes": (stage / "images.tar").stat().st_size,
            "files": {},
        }
        for path in stage.rglob("*"):
            if path.is_file():
                with path.open("rb") as source:
                    manifest["files"][path.relative_to(stage).as_posix()] = hashlib.file_digest(
                        source, "sha256"
                    ).hexdigest()
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(args.output, "w:gz") as archive:
            for path in sorted(stage.iterdir()):
                archive.add(path, arcname=path.name)
    print(f"Created EC2 bundle for {args.sha}")


if __name__ == "__main__":
    main()
