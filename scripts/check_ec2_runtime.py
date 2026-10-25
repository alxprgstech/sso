"""Verify an EC2 bundle on isolated Docker resources with synthetic data, never AWS."""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts.rotate_keys import generate_session_secret, private_directory

ROOT = Path(__file__).resolve().parents[1]


def prepare_workspace(root: Path, project: str) -> Path:
    artifacts = root / "artifacts"
    if artifacts.is_symlink():
        raise ValueError("Artifacts directory must not be a symlink")
    artifacts.mkdir(exist_ok=True)
    workspace = artifacts / project
    private_directory(workspace)
    return workspace


def run(*args: str, input: bytes | None = None) -> bytes:
    result = subprocess.run(args, input=input, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed ({result.returncode}); output withheld")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    project = "sso-ec2-check-" + secrets.token_hex(5)
    workspace = prepare_workspace(ROOT, project)
    spec = importlib.util.spec_from_file_location("ec2_operator", ROOT / "deploy/ec2/ssoctl.py")
    ctl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ctl)
    release = workspace / "release"
    manifest = ctl.unpack(args.bundle.resolve(), release, args.sha)
    run("docker", "load", "-i", str(release / "images.tar"))
    # Rehearse the server-side identity check: the config digests recorded in the
    # manifest must resolve as image IDs after loading, exactly as ssoctl deploy does.
    for field in ("backend_image", "postgres_image"):
        image = json.loads(run("docker", "image", "inspect", manifest[field]))[0]
        assert image["Architecture"] == "amd64"
    config = workspace / "runtime.env"
    pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=3072)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    values = {
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "SSO_RUNTIME_PASSWORD": secrets.token_hex(32),
        "SSO_MIGRATOR_PASSWORD": secrets.token_hex(32),
        "SESSION_SECRET_KEY": generate_session_secret(),
        "TOTP_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "JWT_PRIVATE_KEY_PEM": pem,
        "JWT_KEY_ID": "synthetic-" + secrets.token_hex(8),
        "ENVIRONMENT": "production",
        "BASE_URL": "https://auth.alxprgs.tech",
        "FRONTEND_URL": "https://auth.alxprgs.tech",
        "OIDC_ISSUER": "https://auth.alxprgs.tech",
        "WEBAUTHN_ORIGIN": "https://auth.alxprgs.tech",
        "WEBAUTHN_RP_ID": "auth.alxprgs.tech",
        "EMAIL_PROVIDER": "resend",
        "RESEND_API_KEY": secrets.token_urlsafe(32),
        "SMTP_FROM_EMAIL": "sso@example.invalid",
        "FEATURE_TOTP_ENABLED": "false",
        "FEATURE_PASSKEY_ENABLED": "false",
        "FEATURE_RECOVERY_CODES_ENABLED": "false",
        "FEATURE_EMAIL_VERIFICATION_ENABLED": "true",
        "SENTRY_ENABLED": "false",
    }
    config.write_text(
        "".join(f"{k}={json.dumps(v)}\n" for k, v in values.items()), encoding="utf-8"
    )
    ctl.CONFIG = config
    ctl.compose(release, "config")  # Generates app.env without privileged DB credentials.
    compose_file = release / "compose.yml"
    source = compose_file.read_text().replace("name: alxprgs-sso", f"name: {project}")
    source = source.replace("name: alxprgs-sso-data", f"name: {project}-data")
    # Separate subnet/project/ephemeral host port: do not touch the user's local SSO network.
    source = source.replace("172.29.40.", "172.30.48.").replace(
        "127.0.0.1:8000:8000", "127.0.0.1:0:8000"
    )
    source = source.replace("/etc/alxprgs-sso/app.env", config.with_name("app.env").as_posix())
    compose_file.write_text(source, encoding="utf-8")
    for path in (release / "postgres").iterdir():
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    os.environ["SSO_BACKEND_IMAGE"] = manifest["backend_image"]
    os.environ["SSO_POSTGRES_IMAGE"] = manifest["postgres_image"]

    def compose(*arguments):
        return [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(config),
            "-f",
            str(compose_file),
            *arguments,
        ]

    def sql(statement, *, database="sso_db"):
        return run(
            *compose(
                "exec",
                "-T",
                "db",
                "psql",
                "-XAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "sso_owner",
                "-d",
                database,
                "-c",
                statement,
            )
        ).strip()

    started = False
    try:
        run(*compose("config", "--quiet"))
        started = True
        run(*compose("up", "-d", "--wait", "--wait-timeout", "120", "db"))
        run(*compose("run", "--rm", "--no-deps", "migrate"))
        assert (
            sql("SELECT version_num FROM alembic_version").decode() == manifest["schema_revision"]
        )
        run(*compose("up", "-d", "--no-deps", "backend"))
        port = run(*compose("port", "backend", "8000")).decode().strip().rsplit(":", 1)[1]
        deadline = time.monotonic() + 120
        while True:
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/health/ready", headers={"Host": "auth.alxprgs.tech"}
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    assert response.status == 200
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Production backend readiness failed") from None
                time.sleep(2)
        proof = run(
            *compose(
                "exec",
                "-T",
                "backend",
                "python",
                "-c",
                "import asyncio; from app.database import async_session_maker; "
                "from app.core.database_policy import require_runtime_database_role; "
                'exec("async def check():\\n async with async_session_maker() as db:\\n  await require_runtime_database_role(db)\\nasyncio.run(check())")',
            )
        )
        assert not proof
        sql(
            "SET ROLE sso_migrator; CREATE TABLE ec2_probe(value text); INSERT INTO ec2_probe VALUES ('synthetic-persistent-marker')"
        )
        run(*compose("stop", "backend"))
        db = run(*compose("ps", "-q", "db")).decode().strip()
        backups = workspace / "backups"
        backups.mkdir(mode=0o700)
        if os.name == "nt":
            backups.rmdir()
            private_directory(backups)
        ctl.STATE = workspace
        ctl.compose = lambda release, *arguments: compose(*arguments)
        ctl.backup(release)
        dump = next(backups.glob("*.sql"))
        ctl.verify_backup(dump.name)
        assert dump.stat().st_size > 0
        sys.path.insert(0, str(release / "scripts"))
        from privacy_journal import EXPORT_SQL

        journal = workspace / "fresh-journal.json"
        journal.write_bytes(sql(EXPORT_SQL))
        sql("CREATE DATABASE sso_restore")
        run(
            sys.executable,
            str(release / "scripts/restore_db.py"),
            str(dump),
            "--confirm",
            "--docker",
            "--container",
            db,
            "--user",
            "sso_owner",
            "--db",
            "sso_restore",
            "--deletion-journal",
            str(journal),
        )
        assert (
            sql("SELECT value FROM ec2_probe", database="sso_restore")
            == b"synthetic-persistent-marker"
        )
        run(*compose("run", "--rm", "--no-deps", "migrate"))
        run(*compose("up", "-d", "--no-deps", "backend"))
        assert sql("SELECT value FROM ec2_probe") == b"synthetic-persistent-marker"
        print(
            "PASS: actual PostgreSQL migration, production readiness/runtime role, backup/restore, persistent data"
        )
    finally:
        # Compose only removes the randomly named test project, never global resources.
        if started:
            containers = run(*compose("ps", "-aq")).decode().split()
            for container in containers:
                actual = (
                    run(
                        "docker",
                        "inspect",
                        "--format",
                        '{{index .Config.Labels "com.docker.compose.project"}}',
                        container,
                    )
                    .decode()
                    .strip()
                )
                if actual != project:
                    raise RuntimeError("Cleanup ownership mismatch")
            run(*compose("down", "--volumes", "--remove-orphans"))
        print(
            f"Local test project: {project}; synthetic captures remain in ignored artifacts directory"
        )


if __name__ == "__main__":
    main()
