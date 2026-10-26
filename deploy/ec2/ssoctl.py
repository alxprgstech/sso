#!/usr/bin/env python3
"""Root-owned EC2 operator. No application dependencies; never prints child stderr."""

from __future__ import annotations

import argparse
import base64
import contextlib
import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path("/opt/alxprgs-sso")
CONFIG = Path("/etc/alxprgs-sso/runtime.env")
STATE = Path("/var/lib/alxprgs-sso")
INBOX = Path("/home/ssodeploy/incoming")
SITE = Path("/etc/nginx/sites-available/alxprgs-sso")
DOMAIN = "auth.alxprgs.tech"
SHA = re.compile(r"[a-f0-9]{40}")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}")
EVENTS = {"backup", "renew", "deploy", "test"}


class OperationError(Exception):
    pass


def run(*args: str, input: bytes | None = None, timeout: int = 600) -> bytes:
    try:
        return subprocess.run(
            args, input=input, capture_output=True, check=True, timeout=timeout
        ).stdout
    except (subprocess.SubprocessError, OSError):
        # Command lines carry no secrets (configuration travels via env files),
        # but child stderr stays private and is never echoed here.
        raise OperationError(
            f"{Path(args[0]).name} failed ({' '.join(args)}); inspect privately on the server"
        ) from None


def private_write(path: Path, content: str) -> None:
    private_write_bytes(path, content.encode())


def private_write_bytes(path: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
        temp = Path(target.name)
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
    os.chmod(temp, 0o600)
    temp.replace(path)
    if os.name != "nt":
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@contextlib.contextmanager
def locked():
    # Imported lazily so pure bundle/sequence checks can run on Windows too.
    import fcntl

    with (STATE / "operator.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def settings() -> dict[str, str]:
    result = {}
    for line in CONFIG.read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            result[key] = json.loads(value)
    return result


MFA_KEYS = (
    "FEATURE_TOTP_ENABLED",
    "FEATURE_PASSKEY_ENABLED",
    "FEATURE_RECOVERY_CODES_ENABLED",
    "REQUIRE_ADMIN_MFA",
)
# Keys absent from an older runtime.env fall back to the application default.
# These defaults are true by product decision; the status command states it.
MFA_CODE_DEFAULTS = {key: True for key in MFA_KEYS}


def _mfa_value(value: str) -> bool:
    return value.strip().strip('"').strip("'").lower() in {"1", "true", "yes", "on"}


def mfa_status() -> None:
    """Read-only: show explicit overrides and the effective code default."""
    if not CONFIG.exists():
        raise OperationError("Configuration is not initialized")
    values = settings()
    print("MFA configuration (runtime.env):")
    for key in MFA_KEYS:
        if key in values:
            state = "explicit"
            effective = _mfa_value(values[key])
        else:
            state = "absent (code default)"
            effective = MFA_CODE_DEFAULTS[key]
        print(f"  {key}={str(effective).lower()} [{state}]")
    if not all(key in values for key in MFA_KEYS):
        print(
            "Absent keys use the current application default; a new release may change "
            "their effective value without editing runtime.env."
        )
    print("No secret values were printed.")


def enable_mfa() -> None:
    """Non-destructive targeted update: only the four MFA keys change.

    All other lines, comments, ordering and secret values are preserved. A
    timestamped private backup is written first; services are not restarted.
    """
    if not CONFIG.exists():
        raise OperationError("Configuration is not initialized")
    original_bytes = CONFIG.read_bytes()
    lines = original_bytes.decode().splitlines()
    updated = []
    seen = set()
    for line in lines:
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=", 1)[0]
            if key in MFA_CODE_DEFAULTS:
                updated.append(f"{key}={json.dumps('true')}")
                seen.add(key)
                continue
        updated.append(line)
    for key in MFA_KEYS:
        if key not in seen:
            updated.append(f"{key}={json.dumps('true')}")
    candidate = "\n".join(updated) + "\n"
    # Validate the complete result before replacing the live file.
    parsed = {}
    for line in candidate.splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            parsed[key] = json.loads(value)
    if any(not _mfa_value(parsed.get(key, "")) for key in MFA_KEYS):
        raise OperationError("Generated configuration failed MFA validation")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = CONFIG.with_name(f"{CONFIG.name}.bak-{stamp}")
    private_write_bytes(backup, original_bytes)
    private_write(CONFIG, candidate)
    print(f"MFA enabled in {CONFIG}; backup written beside it.")
    print("Restart/deploy the backend yourself; this command did not alter services or secrets.")


def configure() -> None:
    if CONFIG.exists():
        settings()  # Fail without overwriting an unreadable/invalid configuration.
        print("Existing configuration preserved.")
        return
    key = getpass.getpass("Resend API key (hidden): ")
    if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise OperationError("Invalid Resend key")
    pem = run(
        "openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"
    ).decode()
    session_secret = secrets.token_hex(64)
    while len(set(session_secret)) < 16:
        session_secret = secrets.token_hex(64)
    values = {
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "SSO_RUNTIME_PASSWORD": secrets.token_hex(32),
        "SSO_MIGRATOR_PASSWORD": secrets.token_hex(32),
        "SESSION_SECRET_KEY": session_secret,
        "TOTP_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "JWT_PRIVATE_KEY_PEM": pem,
        "JWT_KEY_ID": "rsa-" + secrets.token_hex(12),
        "ENVIRONMENT": "production",
        "DEBUG": "false",
        "BASE_URL": f"https://{DOMAIN}",
        "FRONTEND_URL": f"https://{DOMAIN}",
        "OIDC_ISSUER": f"https://{DOMAIN}",
        "WEBAUTHN_ORIGIN": f"https://{DOMAIN}",
        "WEBAUTHN_RP_ID": DOMAIN,
        "FEATURE_TOTP_ENABLED": "true",
        "FEATURE_PASSKEY_ENABLED": "true",
        "FEATURE_RECOVERY_CODES_ENABLED": "true",
        "REQUIRE_ADMIN_MFA": "true",
        "FEATURE_EMAIL_VERIFICATION_ENABLED": "true",
        "REQUIRE_VERIFIED_EMAIL": "false",
        "EMAIL_PROVIDER": "resend",
        "RESEND_API_KEY": key,
        "SMTP_FROM_EMAIL": "sso@alxprgs.tech",
        "SENTRY_ENABLED": "false",
        "SENTRY_FRONTEND_ENABLED": "false",
        "SENTRY_REPLAY_ENABLED": "false",
        "SENTRY_ENVIRONMENT": "production",
    }
    # Compose double-quoted dotenv parses \n but interpolates $. Escape dollars.
    private_write(
        CONFIG, "".join(f"{k}={json.dumps(v).replace('$', '$$')}\n" for k, v in values.items())
    )
    print("Generated persistent configuration; no secret values printed.")


def notify(event: str) -> None:
    if event not in EVENTS:
        raise OperationError("Unknown notification type")
    cfg = settings()
    key = cfg["RESEND_API_KEY"].replace("$$", "$")
    payload = json.dumps(
        {
            "from": "ALXPRGS <sso@alxprgs.tech>",
            "to": ["alxprgs@gmail.com"],
            "subject": f"ALXPRGS SSO: {event}",
            "text": f"SSO {DOMAIN}: {event}. Check systemd journal / GitHub Actions. No logs or secrets attached.",
        }
    ).encode()
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "alxprgs-sso-operations",
        },
    )

    # Never follow redirects with the bearer credential.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            body = json.load(response)
            if response.status != 200 or not isinstance(body.get("id"), str):
                raise ValueError
    except Exception:
        raise OperationError("Resend notification failed; check journal privately") from None


def compose(release: Path, *args: str) -> list[str]:
    manifest = json.loads((release / "manifest.json").read_text())
    image = manifest["backend_image"]
    postgres_image = manifest["postgres_image"]
    if not IMAGE.fullmatch(image) or not IMAGE.fullmatch(postgres_image):
        raise OperationError("Invalid image identity")
    # Process environment rather than command line for configuration values.
    os.environ["SSO_BACKEND_IMAGE"] = image
    os.environ["SSO_POSTGRES_IMAGE"] = postgres_image
    # Never inject owner/migrator credentials into the runtime container.
    cfg = settings()
    private_write(
        CONFIG.with_name("app.env"),
        "".join(
            f"{key}={json.dumps(value)}\n"
            for key, value in cfg.items()
            if key not in {"POSTGRES_PASSWORD", "SSO_RUNTIME_PASSWORD", "SSO_MIGRATOR_PASSWORD"}
        ),
    )
    return [
        "docker",
        "compose",
        "--project-name",
        "alxprgs-sso",
        "--env-file",
        str(CONFIG),
        "-f",
        str(release / "compose.yml"),
        *args,
    ]


def current() -> Path:
    value = (ROOT / "current").resolve(strict=True)
    if value.parent != ROOT / "releases":
        raise OperationError("Unexpected current release")
    return value


def switch(release: Path) -> None:
    link = ROOT / "next"
    link.unlink(missing_ok=True)
    link.symlink_to(release, target_is_directory=True)
    link.replace(ROOT / "current")


def schema(release: Path) -> str:
    query = "SELECT CASE WHEN to_regclass('public.alembic_version') IS NULL THEN 'empty' ELSE 'present' END"
    cmd = compose(
        release,
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
        "sso_db",
        "-c",
    )
    if run(*cmd, query).strip() == b"empty":
        return "empty"
    return run(*cmd, "SELECT version_num FROM public.alembic_version").decode().strip()


def backup(release: Path) -> None:
    directory = STATE / "backups"
    # Retention runs even if PostgreSQL is currently down.
    run(sys.executable, str(release / "scripts/prune_backups.py"), str(directory))
    before = set(directory.glob("*.sql"))
    container = run(*compose(release, "ps", "-q", "db")).decode().strip()
    if not re.fullmatch(r"[a-f0-9]{12,64}", container):
        raise OperationError("Database container not found")
    run(
        sys.executable,
        str(release / "scripts/backup_db.py"),
        "--docker",
        "--container",
        container,
        "--db",
        "sso_db",
        "--user",
        "sso_owner",
        "--output-dir",
        str(directory),
    )
    created = set(directory.glob("*.sql")) - before
    if len(created) != 1:
        raise OperationError("Backup file identity could not be established")
    path = created.pop()
    index_path = STATE / "backup-checksums.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    index = {name: digest for name, digest in index.items() if (directory / name).is_file()}
    with path.open("rb") as source:
        index[path.name] = hashlib.file_digest(source, "sha256").hexdigest()
    private_write(index_path, json.dumps(index))


def verify_backup(name: str) -> None:
    if not re.fullmatch(r"sso_backup_sso_db_[0-9]{8}_[0-9]{6}\.sql", name):
        raise OperationError("Invalid backup filename")
    expected = json.loads((STATE / "backup-checksums.json").read_text()).get(name)
    path = STATE / "backups" / name
    if path.is_symlink() or not expected:
        raise OperationError("Backup checksum unavailable")
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != expected:
            raise OperationError("Backup checksum mismatch")
    print("Backup checksum verified.")


def ready() -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(
                "http://127.0.0.1:8000/health/ready", headers={"Host": DOMAIN}
            )
            with urllib.request.urlopen(request, timeout=4) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(2)
    raise OperationError("Backend readiness failed")


def public_ready() -> None:
    try:
        with urllib.request.urlopen(
            f"https://{DOMAIN}/.well-known/openid-configuration", timeout=15
        ) as response:
            if json.load(response)["issuer"] != f"https://{DOMAIN}":
                raise ValueError
        with urllib.request.urlopen(f"https://{DOMAIN}/", timeout=15) as response:
            if response.status != 200:
                raise ValueError
    except Exception:
        raise OperationError("Public HTTPS / discovery check failed") from None


def validate_sequence(record: dict, sequence: int, sha: str) -> None:
    if sequence < record.get("sequence", 0):
        raise OperationError("Stale deployment rejected")
    if sequence == record.get("sequence") and sha != record.get("sha"):
        raise OperationError("Sequence reused for another SHA")


def unpack(bundle: Path, destination: Path, sha: str) -> dict:
    # Only regular files/directories; no links, devices or traversal, even for trusted CI.
    with tarfile.open(bundle, "r:gz") as archive:
        members = archive.getmembers()
        seen = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or member.name in seen
            ):
                raise OperationError("Unsafe bundle path")
            if not (member.isfile() or member.isdir()):
                raise OperationError("Unsafe bundle type")
            seen.add(member.name)
        archive.extractall(destination, filter="data")
    manifest = json.loads((destination / "manifest.json").read_text())
    if (
        manifest["sha"] != sha
        or not SHA.fullmatch(sha)
        or not IMAGE.fullmatch(manifest["backend_image"])
        or not IMAGE.fullmatch(manifest["postgres_image"])
    ):
        raise OperationError("Bundle identity mismatch")
    inventory = {
        p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()
    } - {"manifest.json"}
    if inventory != set(manifest["files"]):
        raise OperationError("Bundle inventory mismatch")
    for name, digest in manifest["files"].items():
        with (destination / name).open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != digest:
                raise OperationError("Bundle checksum mismatch")
    return manifest


def can_rollback(old: dict, new: dict, actual_schema: str) -> bool:
    return (
        old["migrations"] == new["migrations"]
        and old["schema_revision"] == new["schema_revision"] == actual_schema
    )


def deploy(bundle: Path, sequence: int, sha: str) -> None:
    if not SHA.fullmatch(sha) or sequence < 1:
        raise OperationError("Invalid deployment identity")
    # No arbitrary root filesystem reads from the sudo entry point.
    incoming = INBOX.resolve()
    resolved = bundle.resolve(strict=True)
    if not resolved.is_relative_to(incoming) or not resolved.is_file():
        raise OperationError("Bundle must be in the deployment inbox")
    record_path = STATE / "highwater.json"
    record = json.loads(record_path.read_text()) if record_path.exists() else {}
    validate_sequence(record, sequence, sha)
    destination = ROOT / "releases" / f"{sequence}-{sha}"
    if destination.exists():
        # Retrying failed deployments starts with a fresh verified copy, not a partial tree.
        destination = ROOT / "releases" / f"{sequence}-{sha}-{secrets.token_hex(4)}"
    destination.mkdir(mode=0o755)
    destination.chmod(0o755)
    try:
        manifest = unpack(resolved, destination, sha)
        # tar modes must not make static assets unreadable by nginx or scripts writable.
        for path in destination.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        # Verify disk headroom before image import, backup or maintenance.
        if shutil.disk_usage(ROOT).free < max(3 * 1024**3, manifest["image_bytes"] * 2):
            raise OperationError("Insufficient disk space; no automatic data deletion")
        run("docker", "load", "-i", str(destination / "images.tar"), timeout=900)
        image = json.loads(run("docker", "image", "inspect", manifest["backend_image"]))[0]
        if image["Architecture"] != "amd64":
            raise OperationError("Wrong image architecture")
        identity = json.loads(
            run(
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "python",
                manifest["backend_image"],
                "-c",
                'from importlib.resources import files; print(files("app").joinpath("_build_info.json").read_text())',
            )
        )
        if identity["commit_sha"] != sha:
            raise OperationError("Image source identity mismatch")
        run(*compose(destination, "config", "--quiet"))
        private_write(record_path, json.dumps({"sequence": sequence, "sha": sha}))
        old = current() if (ROOT / "current").exists() else None
        maintenance = STATE / "maintenance"
        maintenance.touch(mode=0o644)
        before = "empty"
        rollback = False
        try:
            # Stop every application writer before the snapshot and migration.
            if old:
                run(*compose(old, "stop", "backend"))
                before = schema(old)
                old_manifest = json.loads((old / "manifest.json").read_text())
                rollback = True  # No migration has been attempted yet.
                backup(old)
            run(*compose(destination, "up", "-d", "--wait", "--wait-timeout", "120", "db"))
            rollback = bool(old) and can_rollback(old_manifest, manifest, before)
            migration_name = f"alxprgs-sso-migrate-{sequence}-{secrets.token_hex(4)}"
            try:
                run(*compose(destination, "run", "--name", migration_name, "--no-deps", "migrate"))
            except OperationError:
                raise OperationError(
                    f"Migration failed; inspect docker logs {migration_name} privately"
                ) from None
            run("docker", "rm", migration_name)
            run(*compose(destination, "up", "-d", "--no-deps", "backend"))
            ready()
            switch(destination)
            shutil.copyfile(destination / "nginx.conf", SITE)
            SITE.chmod(0o644)
            run("nginx", "-t")
            run("systemctl", "reload", "nginx")
            maintenance.unlink()
            public_ready()
        except Exception:
            maintenance.touch(mode=0o644)
            # Stop candidate even if rollback is prohibited. Never restore the DB automatically.
            with contextlib.suppress(OperationError):
                run(*compose(destination, "stop", "backend"))
            if old and rollback and schema(destination) == before:
                switch(old)
                shutil.copyfile(old / "nginx.conf", SITE)
                run(*compose(old, "up", "-d", "--no-deps", "backend"))
                ready()
                run("nginx", "-t")
                run("systemctl", "reload", "nginx")
                maintenance.unlink()
                try:
                    public_ready()
                except OperationError:
                    maintenance.touch(mode=0o644)
                    raise
            raise
        private_write(STATE / "deployed.json", json.dumps({"sequence": sequence, "sha": sha}))
        # Keep image in Docker; avoid retaining the large transport archive per release.
        (destination / "images.tar").unlink()
        run("systemctl", "enable", "--now", "alxprgs-sso-backup.timer")
        print(f"Deployed {sha}; sequence {sequence}")
    except Exception:
        # Failed tree is retained for diagnosis. No volumes or old releases are removed.
        raise


def renew() -> None:
    run(
        "certbot",
        "renew",
        "--non-interactive",
        "--cert-name",
        DOMAIN,
        "--deploy-hook",
        "/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx",
    )
    # Certbot hook failures are not always reflected in its exit code.
    run("nginx", "-t")
    run("systemctl", "reload", "nginx")
    run(
        "openssl",
        "x509",
        "-checkend",
        str(14 * 86400),
        "-noout",
        "-in",
        f"/etc/letsencrypt/live/{DOMAIN}/fullchain.pem",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "configure",
        "backup",
        "renew",
        "test-alert",
        "admin",
        "status",
        "maintenance",
        "resume",
        "mfa-status",
        "enable-mfa",
        "recover-admin",
        "admin-status",
    ):
        sub.add_parser(name)
    deploy_parser = sub.add_parser("deploy")
    deploy_parser.add_argument("bundle", type=Path)
    deploy_parser.add_argument("sequence", type=int)
    deploy_parser.add_argument("sha")
    verify_parser = sub.add_parser("verify-backup")
    verify_parser.add_argument("name")
    recover_parser = sub.add_parser("recover-admin")
    recover_parser.add_argument("--username", required=True)
    recover_parser.add_argument(
        "--reason",
        required=True,
        choices=("lost_factor", "compromised", "owner_request"),
    )
    recover_parser.add_argument(
        "--confirm",
        required=True,
        help="Repeat the exact administrator username",
    )
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo")
    os.umask(0o077)
    try:
        with locked():
            if args.command == "configure":
                configure()
            elif args.command == "deploy":
                deploy(args.bundle, args.sequence, args.sha)
            elif args.command == "backup":
                backup(current())
            elif args.command == "verify-backup":
                verify_backup(args.name)
            elif args.command == "renew":
                renew()
            elif args.command == "test-alert":
                notify("test")
                print("Resend accepted the notification; check the recipient inbox.")
            elif args.command == "maintenance":
                (STATE / "maintenance").touch(mode=0o644)
                run(*compose(current(), "stop", "backend"))
            elif args.command == "resume":
                run(*compose(current(), "up", "-d", "--no-deps", "backend"))
                ready()
                (STATE / "maintenance").unlink(missing_ok=True)
                try:
                    public_ready()
                except OperationError:
                    (STATE / "maintenance").touch(mode=0o644)
                    raise
            elif args.command == "admin":
                # Inherit the terminal for getpass, never put a password in argv or env.
                result = subprocess.run(
                    compose(current(), "exec", "backend", "python", "-m", "app.cli.bootstrap_admin")
                )
                if result.returncode:
                    raise OperationError("Administrator bootstrap failed")
            elif args.command == "mfa-status":
                mfa_status()
            elif args.command == "enable-mfa":
                enable_mfa()
            elif args.command == "recover-admin":
                # Inherit the terminal: the operator types the exact username
                # and reason. No password or factor is created or printed.
                result = subprocess.run(
                    compose(
                        current(),
                        "exec",
                        "backend",
                        "python",
                        "-m",
                        "app.cli.admin_recovery",
                        "reset-factors",
                        "--username",
                        args.username,
                        "--reason",
                        args.reason,
                        "--confirm",
                        args.confirm,
                    )
                )
                if result.returncode:
                    raise OperationError("Administrator MFA recovery failed")
            elif args.command == "admin-status":
                result = subprocess.run(
                    compose(
                        current(),
                        "exec",
                        "backend",
                        "python",
                        "-m",
                        "app.cli.admin_recovery",
                        "status",
                    )
                )
                if result.returncode:
                    raise OperationError("Administrator status check failed")
            elif args.command == "status":
                print(
                    (STATE / "deployed.json").read_text()
                    if (STATE / "deployed.json").exists()
                    else "Not deployed"
                )
                print("maintenance=" + str((STATE / "maintenance").exists()))
        return 0
    except Exception as error:
        # Only our deliberately sanitized errors are user-visible.
        print(
            str(error)
            if isinstance(error, OperationError)
            else f"Operation failed: {type(error).__name__}",
            file=sys.stderr,
        )
        if args.command in EVENTS:
            try:
                notify(args.command)
            except Exception:
                print("Notification failed; inspect local journal.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
