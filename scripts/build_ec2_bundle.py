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


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


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
        backend = run(
            "docker", "image", "inspect", "--format", "{{.Id}}", f"alxprgs-sso-backend:{args.sha}"
        )
        subprocess.run(
            [
                "docker",
                "save",
                "-o",
                str(stage / "images.tar"),
                f"alxprgs-sso-backend:{args.sha}",
                POSTGRES,
            ],
            check=True,
        )
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
            "backend_image": backend,
            "postgres_image": run("docker", "image", "inspect", "--format", "{{.Id}}", POSTGRES),
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
