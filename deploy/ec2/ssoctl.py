#!/usr/bin/env python3
"""Root-owned EC2 operator. No application dependencies; never prints child stderr."""

from __future__ import annotations

import argparse
import base64
import contextlib
import getpass
import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
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
RESULT_PREFIX = "ssoctl-result:"
PROTOCOL_VERSION = 1

# Self-update reads one fixed path from one fixed branch of the trusted private
# repository. The token is a separate read-only credential, never runtime.env.
GITHUB_API = "https://api.github.com"
GITHUB_REPO = "alxprgstech/sso"
GITHUB_BRANCH = "main"
GITHUB_OPERATOR = "deploy/ec2/ssoctl.py"
GITHUB_TOKEN = Path("/etc/alxprgs-sso/github-read.token")
CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")
SYSTEM_PYTHON = Path("/usr/bin/python3")
HTTP_TIMEOUT = 20
HELP_TIMEOUT = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_OPERATOR_BYTES = 1024 * 1024
ROOT_UID = 0
ROOT_GID = 0
REQUIRED_COMMANDS = (
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
    "deploy",
    "verify-backup",
    "self-update",
)


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


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def result_protocol(result: str, sha: str, sequence: int) -> str:
    return RESULT_PREFIX + json.dumps(
        {
            "version": PROTOCOL_VERSION,
            "result": result,
            "sha": sha,
            "sequence": sequence,
        },
        separators=(",", ":"),
    )


def backend_runtime_identity() -> dict:
    request = urllib.request.Request(
        "http://127.0.0.1:8000/health/identity", headers={"Host": DOMAIN}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200 or response.geturl() != request.full_url:
            raise OperationError("Backend identity is unavailable")
        value = json.loads(response.read(4096))
    if not isinstance(value, dict):
        raise OperationError("Backend identity is invalid")
    return value


def installation_matches(sha: str) -> bool:
    """Read-only proof that this exact revision is installed and serving.

    Any missing or inconsistent fact means "not proven" and falls through to the
    normal verified installation. Must be called under the deployment lock; it
    performs no unpacking, image load, backup, migration, restart or switch.
    """
    if not SHA.fullmatch(sha) or (STATE / "maintenance").exists():
        return False
    record = _json_object(STATE / "deployed.json")
    if record.get("sha") != sha or not isinstance(record.get("sequence"), int):
        return False
    try:
        release = current()
        manifest = _json_object(release / "manifest.json")
        frontend = _json_object(release / "public/build-info.json")
        if manifest.get("sha") != sha or frontend.get("commit_sha") != sha:
            return False
        container = (
            run(
                "docker",
                "ps",
                "-q",
                "--filter",
                "label=com.docker.compose.project=alxprgs-sso",
                "--filter",
                "label=com.docker.compose.service=backend",
            )
            .decode()
            .strip()
        )
        if not re.fullmatch(r"[a-f0-9]{12,64}", container):
            return False
        inspected = json.loads(run("docker", "inspect", container))[0]
        labels = (inspected.get("Config") or {}).get("Labels") or {}
        if not (inspected.get("State") or {}).get("Running"):
            return False
        if inspected.get("Image") != manifest.get("backend_image"):
            return False
        if labels.get("com.docker.compose.service") != "backend":
            return False
        config_files = labels.get("com.docker.compose.project.config_files", "")
        if str(release / "compose.yml") not in {item.strip() for item in config_files.split(",")}:
            return False
        identity = backend_runtime_identity()
        if identity.get("status") != "ready" or identity.get("database") != "connected":
            return False
        if identity.get("commit_sha") != sha:
            return False
    except (OperationError, OSError, ValueError, KeyError, IndexError, TypeError):
        return False
    return True


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


def operator_path() -> Path:
    return ROOT / "tools" / "ssoctl.py"


def commit_sha(value: str) -> str:
    if not SHA.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "expected a full 40-character lowercase hexadecimal commit SHA"
        )
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _tls_context():
    # Fixed Ubuntu CA bundle: SSL_CERT_FILE/SSL_CERT_DIR cannot replace trust.
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        context.load_verify_locations(cafile=str(CA_BUNDLE))
    except (OSError, ssl.SSLError):
        raise OperationError("System CA bundle is unavailable; refusing GitHub access") from None
    return context


def _github_opener():
    # Fixed trusted origin, fixed TLS trust, no environment proxy, no redirect.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=_tls_context()),
        _NoRedirect,
    )


def github_token() -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(GITHUB_TOKEN, flags)
    except FileNotFoundError:
        raise OperationError(
            f"GitHub read token is missing at {GITHUB_TOKEN}; configure read-only access first"
        ) from None
    except OSError:
        raise OperationError("GitHub read token must be a regular root-owned file") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OperationError("GitHub read token must be a regular root-owned file")
        if info.st_uid != ROOT_UID:
            raise OperationError("GitHub read token must be owned by root")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
            raise OperationError("GitHub read token must have mode 0600")
        if not 20 <= info.st_size <= 1024:
            raise OperationError("GitHub read token has an invalid size")
        raw = os.read(descriptor, 1025)
    except OSError:
        raise OperationError("GitHub read token cannot be read") from None
    finally:
        os.close(descriptor)
    if len(raw) > 1024:
        raise OperationError("GitHub read token has an invalid size")
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        raise OperationError("GitHub read token has an invalid format") from None
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,1024}", token):
        raise OperationError("GitHub read token has an invalid format")
    return token


def _github_failure(code: int) -> OperationError:
    if code in {401, 403}:
        return OperationError(
            f"GitHub rejected the read token (HTTP {code}); rotate the read-only token"
        )
    if code == 404:
        return OperationError(
            "GitHub repository, commit, or operator file was not found (HTTP 404)"
        )
    if 300 <= code < 400:
        return OperationError("GitHub API returned an unexpected redirect")
    return OperationError(f"GitHub API returned HTTP {code}; installed operator unchanged")


def github_api(path: str) -> dict:
    token = github_token()
    url = GITHUB_API + path
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "alxprgs-sso-ssoctl-self-update",
        },
    )
    try:
        with _github_opener().open(request, timeout=HTTP_TIMEOUT) as response:
            status = response.status
            final_url = response.geturl()
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise _github_failure(error.code) from None
    except (urllib.error.URLError, http.client.HTTPException, OSError):
        raise OperationError(
            "GitHub is unreachable (network or TLS failure); installed operator unchanged"
        ) from None
    if status != 200:
        raise _github_failure(status)
    if final_url != url:
        raise OperationError("GitHub API redirected to an untrusted origin")
    if len(payload) > MAX_RESPONSE_BYTES:
        raise OperationError("GitHub API response exceeds the size limit")
    try:
        value = json.loads(payload)
    except ValueError:
        raise OperationError("GitHub API returned invalid metadata") from None
    if not isinstance(value, dict):
        raise OperationError("GitHub API returned invalid metadata")
    return value


def _full_sha(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _commit_identity(document: dict) -> str:
    commit = document.get("commit")
    tree = commit.get("tree") if isinstance(commit, dict) else None
    revision = document.get("sha")
    if not _full_sha(revision) or not isinstance(tree, dict) or not _full_sha(tree.get("sha")):
        raise OperationError("GitHub returned an invalid commit identity")
    return revision


def resolve_revision(requested: str | None) -> str:
    if requested is not None:
        if not _full_sha(requested):
            raise OperationError("--sha must be a full 40-character lowercase commit SHA")
        document = github_api(f"/repos/{GITHUB_REPO}/commits/{requested}")
        if _commit_identity(document) != requested:
            raise OperationError("GitHub commit identity does not match the requested SHA")
        comparison = github_api(f"/repos/{GITHUB_REPO}/compare/{requested}...{GITHUB_BRANCH}")
        base = comparison.get("base_commit")
        merge_base = comparison.get("merge_base_commit")
        ahead_by = comparison.get("ahead_by")
        if (
            comparison.get("status") not in {"ahead", "identical"}
            or not isinstance(base, dict)
            or base.get("sha") != requested
            or not isinstance(merge_base, dict)
            or merge_base.get("sha") != requested
            or comparison.get("behind_by") != 0
            or not isinstance(ahead_by, int)
            or ahead_by < 0
        ):
            raise OperationError("Requested commit is not in main history; refusing to install it")
        return requested
    document = github_api(f"/repos/{GITHUB_REPO}/commits/{GITHUB_BRANCH}")
    return _commit_identity(document)


def download_operator(revision: str) -> bytes:
    if not _full_sha(revision):
        raise OperationError("Invalid operator revision")
    document = github_api(f"/repos/{GITHUB_REPO}/contents/{GITHUB_OPERATOR}?ref={revision}")
    content = document.get("content")
    size = document.get("size")
    blob = document.get("sha")
    if (
        document.get("type") != "file"
        or document.get("path") != GITHUB_OPERATOR
        or document.get("encoding") != "base64"
        or not isinstance(content, str)
        or not isinstance(size, int)
        or not 0 < size <= MAX_OPERATOR_BYTES
        or not _full_sha(blob)
    ):
        raise OperationError("GitHub returned invalid operator file metadata")
    try:
        data = base64.b64decode("".join(content.split()), validate=True)
    except (ValueError, TypeError):
        raise OperationError("GitHub returned an undecodable operator file") from None
    if len(data) != size or not data or len(data) > MAX_OPERATOR_BYTES:
        raise OperationError("Operator file size does not match GitHub metadata")
    # Git blob identity is a content integrity check, not a local trust anchor:
    # provenance comes from the fixed authenticated repository and pinned commit.
    digest = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
    if digest != blob:
        raise OperationError("Operator file content does not match GitHub metadata")
    return data


def _lstat(path: Path, label: str) -> os.stat_result:
    try:
        return path.lstat()
    except FileNotFoundError:
        raise OperationError(f"{label} is missing") from None
    except OSError:
        raise OperationError(f"{label} cannot be inspected") from None


def _require_operator_directory(path: Path) -> Path:
    directory = path.parent
    info = _lstat(directory, "Operator tools directory")
    if not stat.S_ISDIR(info.st_mode):
        raise OperationError("Operator tools directory must be a real directory")
    if info.st_uid != ROOT_UID:
        raise OperationError("Operator tools directory must be owned by root")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o022:
        raise OperationError("Operator tools directory has unsafe permissions")
    return directory


def read_installed_operator(path: Path) -> bytes:
    _require_operator_directory(path)
    info = _lstat(path, "Installed operator")
    if not stat.S_ISREG(info.st_mode):
        raise OperationError("Installed operator must be a regular file, not a symlink")
    if info.st_uid != ROOT_UID:
        raise OperationError("Installed operator must be owned by root")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o022:
        raise OperationError("Installed operator has unsafe permissions")
    if not 0 < info.st_size <= MAX_OPERATOR_BYTES:
        raise OperationError("Installed operator has an invalid size")
    try:
        data = path.read_bytes()
    except OSError:
        raise OperationError("Installed operator cannot be read") from None
    if len(data) != info.st_size or not data:
        raise OperationError("Installed operator changed while it was read")
    return data


def _write_candidate(directory: Path, data: bytes) -> Path:
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".ssoctl-candidate-", delete=False
        ) as handle:
            temp = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
    except OSError:
        if temp is not None:
            with contextlib.suppress(OSError):
                temp.unlink()
        raise OperationError("Operator candidate could not be stored securely") from None
    return temp


def _help_environment() -> dict[str, str]:
    environment = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    if os.name == "nt":
        for key in ("SYSTEMROOT", "TEMP", "TMP"):
            if key in os.environ:
                environment[key] = os.environ[key]
    return environment


def _operator_help(path: Path, command: str | None = None) -> str:
    argv = [str(SYSTEM_PYTHON), "-I", str(path)]
    if command is not None:
        argv.append(command)
    argv.append("--help")
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            timeout=HELP_TIMEOUT,
            env=_help_environment(),
        )
    except (subprocess.SubprocessError, OSError):
        raise OperationError("Operator help check could not run") from None
    if result.returncode != 0:
        label = f"{command} --help" if command is not None else "--help"
        raise OperationError(f"Operator {label} failed; candidate rejected")
    return result.stdout.decode("utf-8", "replace")


def _check_candidate(data: bytes) -> None:
    if not data or len(data) > MAX_OPERATOR_BYTES:
        raise OperationError("Operator candidate is empty or exceeds the size limit")
    try:
        compile(data, "<operator-candidate>", "exec")
    except (SyntaxError, ValueError, TypeError):
        raise OperationError("Operator candidate has invalid Python syntax") from None


def _check_candidate_interface(path: Path) -> None:
    listing = _operator_help(path)
    missing = [
        name
        for name in REQUIRED_COMMANDS
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", listing) is None
    ]
    if missing:
        raise OperationError(
            "Operator candidate is missing required commands: " + ", ".join(missing)
        )
    # argparse conflicts surface here, before anything is installed.
    _operator_help(path, "recover-admin")
    if "--sha" not in _operator_help(path, "self-update"):
        raise OperationError("Operator candidate lacks the self-update --sha interface")


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _backup_directory() -> Path:
    directory = STATE / "operator-backups"
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        raise OperationError("Operator backup directory cannot be created") from None
    info = _lstat(directory, "Operator backup directory")
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != ROOT_UID:
        raise OperationError("Operator backup directory is not a safe root-owned directory")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
        try:
            directory.chmod(0o700)
        except OSError:
            raise OperationError("Operator backup directory permissions cannot be fixed") from None
    return directory


def _write_backup(data: bytes) -> Path:
    directory = _backup_directory()
    digest = hashlib.sha256(data).hexdigest()[:12]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    for attempt in range(8):
        suffix = f"-{attempt}" if attempt else ""
        path = directory / f"ssoctl.py.{stamp}.{digest}{suffix}.bak"
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            continue
        except OSError:
            raise OperationError(
                "Operator backup cannot be written; installed operator unchanged"
            ) from None
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(path, 0o600)
        except OSError:
            with contextlib.suppress(OSError):
                path.unlink()
            raise OperationError(
                "Operator backup cannot be written; installed operator unchanged"
            ) from None
        _sync_directory(directory)
        return path
    raise OperationError("Operator backup name collision; installed operator unchanged")


def _replace_operator(temp: Path, path: Path, previous: bytes) -> None:
    _require_operator_directory(path)
    info = _lstat(path, "Installed operator")
    if not stat.S_ISREG(info.st_mode):
        raise OperationError("Installed operator path is not a regular file")
    if read_installed_operator(path) != previous:
        raise OperationError("Installed operator changed during self-update; nothing was replaced")
    try:
        os.chmod(temp, 0o755)
        os.chown(temp, ROOT_UID, ROOT_GID)
    except OSError:
        raise OperationError("Operator candidate ownership or mode could not be set") from None
    try:
        os.replace(temp, path)
    except OSError:
        raise OperationError("Installed operator could not be replaced") from None
    _sync_directory(path.parent)


def _verify_operator_file(path: Path, expected: bytes) -> None:
    _require_operator_directory(path)
    info = _lstat(path, "Installed operator")
    if not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID:
        raise OperationError("Installed operator owner or type is unexpected")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o755:
        raise OperationError("Installed operator mode is unexpected")
    try:
        data = path.read_bytes()
    except OSError:
        raise OperationError("Installed operator cannot be read after replacement") from None
    if data != expected:
        raise OperationError(
            "Installed operator content does not match the expected verified content"
        )


def _verify_installed(path: Path, expected: bytes) -> None:
    _verify_operator_file(path, expected)
    _operator_help(path)
    _operator_help(path, "self-update")


def _restore_operator(path: Path, previous: bytes) -> None:
    temp = _write_candidate(path.parent, previous)
    try:
        os.chmod(temp, 0o755)
        os.chown(temp, ROOT_UID, ROOT_GID)
        os.replace(temp, path)
    except OSError:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise OperationError("Automatic restore of the previous operator failed") from None
    _sync_directory(path.parent)
    # The previous operator may itself be the broken revision being replaced,
    # so restore verifies bytes and mode rather than its --help output.
    _verify_operator_file(path, previous)


def self_update(requested: str | None) -> None:
    path = operator_path()
    _require_operator_directory(path)
    installed = read_installed_operator(path)
    revision = resolve_revision(requested)
    data = download_operator(revision)
    _check_candidate(data)
    temp = _write_candidate(path.parent, data)
    backup: Path | None = None
    try:
        _check_candidate_interface(temp)
        if data == installed:
            print(f"Operator source: {GITHUB_REPO} {GITHUB_BRANCH} {GITHUB_OPERATOR}")
            print(f"Commit SHA: {revision}")
            print("Installed operator: already current; no backup or replacement was made")
            print("Application and configuration were not changed.")
            return
        backup = _write_backup(installed)
        _replace_operator(temp, path, installed)
        try:
            _verify_installed(path, data)
        except Exception:
            try:
                _restore_operator(path, installed)
            except OperationError as restore_error:
                raise OperationError(
                    "Installed operator failed verification and automatic restore failed "
                    f"({restore_error}); restore manually from {backup}"
                ) from None
            raise OperationError(
                "Installed operator failed verification; "
                f"the previous file was restored from {backup}"
            ) from None
    finally:
        with contextlib.suppress(OSError):
            temp.unlink()
    print(f"Operator source: {GITHUB_REPO} {GITHUB_BRANCH} {GITHUB_OPERATOR}")
    print(f"Commit SHA: {revision}")
    print("Installed operator: updated")
    print(f"Backup: {backup}")
    print("Application and configuration were not changed.")


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


def deploy(bundle: Path, sequence: int, sha: str) -> str:
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
    # Recheck under the operator lock before the first installation side effect.
    # highwater.json only records an attempt and is deliberately not evidence.
    if installation_matches(sha):
        return "already_deployed"
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
        # Keep the success record last: a cleanup or timer failure must not make a
        # later retry mistake the installation for complete evidence.
        # Keep image in Docker; avoid retaining the large transport archive per release.
        (destination / "images.tar").unlink()
        run("systemctl", "enable", "--now", "alxprgs-sso-backup.timer")
        private_write(STATE / "deployed.json", json.dumps({"sequence": sequence, "sha": sha}))
        return "deployed"
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


def build_parser() -> argparse.ArgumentParser:
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
        "admin-status",
    ):
        sub.add_parser(name)
    deploy_parser = sub.add_parser("deploy")
    deploy_parser.add_argument("bundle", type=Path)
    deploy_parser.add_argument("sequence", type=int)
    deploy_parser.add_argument("sha")
    verify_parser = sub.add_parser("verify-backup")
    verify_parser.add_argument("name")
    # Registered once, with its required arguments, outside the plain loop.
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
    update_parser = sub.add_parser("self-update")
    update_parser.add_argument(
        "--sha",
        type=commit_sha,
        help="full 40-character commit SHA from main history (default: current main)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo")
    os.umask(0o077)
    try:
        with locked():
            if args.command == "configure":
                configure()
            elif args.command == "self-update":
                self_update(args.sha)
            elif args.command == "deploy":
                result = deploy(args.bundle, args.sequence, args.sha)
                print(result_protocol(result, args.sha, args.sequence))
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
