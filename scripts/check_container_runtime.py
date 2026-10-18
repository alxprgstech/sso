"""Run an owned, synthetic Compose acceptance campaign; never target existing volumes."""

import ipaddress
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_URL = "http://127.0.0.1:3000"


def command(args: list[str], *, check: bool = True) -> str:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode:
        # CLI output can contain interpolated DB credentials: retain only stage identity.
        raise RuntimeError(
            f"Container command failed: {args[0]} {args[1]} (exit {result.returncode})"
        )
    return result.stdout


def request(path: str) -> tuple[int, dict[str, str], bytes]:
    try:
        response = urllib.request.urlopen(CAMPAIGN_URL + path, timeout=3)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, dict(response.headers), response.read(65536)


def campaign_revision(volume: str) -> str:
    existing = command(["docker", "volume", "ls", "--format", "{{.Name}}"])
    if volume in existing.splitlines():
        raise RuntimeError("Campaign volume exists; refusing to use it")
    sha = command(["git", "rev-parse", "HEAD"]).strip()
    if len(sha) != 40:
        raise RuntimeError("Missing exact build revision")
    return sha


def campaign_environment(sha: str) -> dict[str, str]:
    environment = {
        "ALX_BUILD_SHA": sha,
        "POSTGRES_USER": "ci_owner",
        "POSTGRES_DB": "sso_ci_test",
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "SSO_RUNTIME_PASSWORD": secrets.token_hex(32),
        "SSO_MIGRATOR_PASSWORD": secrets.token_hex(32),
        "ENVIRONMENT": "testing",
        "REDIRECT_TRANSPORT_PROFILE": "local",
        "FEATURE_TOTP_ENABLED": "false",
        "FEATURE_PASSKEY_ENABLED": "false",
        "FEATURE_RECOVERY_CODES_ENABLED": "false",
        "FEATURE_EMAIL_VERIFICATION_ENABLED": "true",
        "EMAIL_PROVIDER": "smtp",
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": "1",
        "SENTRY_ENABLED": "false",
        "SESSION_SECRET_KEY": secrets.token_hex(64),
        "BASE_URL": "http://localhost:3000",
        "FRONTEND_URL": "http://localhost:3000",
        "OIDC_ISSUER": "http://localhost:3000",
        "WEBAUTHN_RP_ID": "localhost",
        "WEBAUTHN_ORIGIN": "http://localhost:3000",
    }
    return environment


def tag_campaign_images(project: str) -> None:
    for service in ("backend", "migrate", "frontend"):
        command(
            [
                "docker",
                "tag",
                os.getenv("SSO_FRONTEND_TEST_IMAGE", "sso-frontend-check")
                if service == "frontend"
                else os.getenv("SSO_BACKEND_TEST_IMAGE", "sso-backend-check"),
                project + "-" + service,
            ]
        )


def wait_initial_readiness() -> None:
    deadline = time.monotonic() + 90
    while True:
        try:
            if request("/health/ready")[0] == 200:
                break
        except (OSError, urllib.error.URLError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Compose readiness timeout")
        time.sleep(1)


def require_container_boundaries(compose: list[str]) -> None:
    for service in ("backend", "frontend", "migrate"):
        container = command(compose + ["ps", "-aq", service]).strip()
        config = json.loads(command(["docker", "inspect", container]))[0]
        assert config["Config"]["User"].split(":")[0] not in ("", "0", "root")
        host = config["HostConfig"]
        assert host["ReadonlyRootfs"] and "ALL" in host["CapDrop"]
        assert not host["Privileged"] and host["Memory"] > 0 and host["PidsLimit"] > 0
        assert "no-new-privileges:true" in host["SecurityOpt"]
        assert not any("docker.sock" in item["Destination"] for item in config["Mounts"])
        assert not host["PortBindings"] or service == "frontend"


def require_runtime_and_browser(compose: list[str]) -> None:
    proof = "import asyncio; from app.database import async_session_maker; from app.core.database_policy import require_runtime_database_role; exec('async def check():\\n    async with async_session_maker() as db: await require_runtime_database_role(db)'); asyncio.run(check())"
    command(compose + ["exec", "-T", "backend", "python", "-c", proof])
    code, headers, body = request("/")
    assert code == 200 and b"<html" in body
    assert (
        "Content-Security-Policy" in headers
        and "'unsafe-inline'" not in headers["Content-Security-Policy"]
    )
    browser = subprocess.run(
        ["npx.cmd" if os.name == "nt" else "npx", "playwright", "test", "e2e/csp.spec.ts"],
        cwd=ROOT / "frontend",
        env=os.environ | {"PLAYWRIGHT_BASE_URL": CAMPAIGN_URL},
    )
    if browser.returncode:
        raise RuntimeError("Real proxy CSP browser regression failed")
    command(
        compose
        + [
            "exec",
            "-T",
            "backend",
            "python",
            "-c",
            "import importlib.util; assert all(importlib.util.find_spec(m) is None for m in ('pytest','mypy','ruff','build'))",
        ]
    )


def require_database_outage_recovery(compose: list[str]) -> None:
    command(compose + ["stop", "db"])
    assert request("/health/ready")[0] == 503
    command(compose + ["start", "db"])
    deadline = time.monotonic() + 30
    while request("/health/ready")[0] != 200:
        if time.monotonic() >= deadline:
            raise RuntimeError("Database restart readiness timeout")
        time.sleep(1)


def cleanup_owned_campaign(compose: list[str], project: str, volume: str) -> None:
    # Stop only this campaign. Delete only its exact, labelled new volume.
    command(compose + ["down"], check=True)
    result = command(["docker", "volume", "ls", "--format", "{{.Name}}"])
    if volume in result.splitlines():
        description = json.loads(command(["docker", "volume", "inspect", volume]))[0]
        assert description["Labels"]["com.docker.compose.project"] == project
        assert description["Name"] == volume
        command(["docker", "volume", "rm", volume])


def run() -> None:
    global CAMPAIGN_URL
    project = "sso-ci-" + uuid.uuid4().hex
    volume = project + "_sso_db_data"
    sha = campaign_revision(volume)
    environment = campaign_environment(sha)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    CAMPAIGN_URL = f"http://127.0.0.1:{port}"
    environment.update(
        BASE_URL=CAMPAIGN_URL,
        FRONTEND_URL=CAMPAIGN_URL,
        OIDC_ISSUER=CAMPAIGN_URL,
        WEBAUTHN_ORIGIN=CAMPAIGN_URL,
    )
    ids = command(["docker", "network", "ls", "-q"]).split()
    existing = json.loads(command(["docker", "network", "inspect", *ids])) if ids else []
    used = [
        ipaddress.ip_network(item["Subnet"])
        for network in existing
        for item in (network.get("IPAM", {}).get("Config") or [])
        if "Subnet" in item
    ]
    free = [
        ipaddress.ip_network(f"172.30.{index}.0/24")
        for index in range(1, 255)
        if all(
            not ipaddress.ip_network(f"172.30.{index}.0/24").overlaps(subnet)
            for subnet in used
            if subnet.version == 4
        )
    ]
    if len(free) < 2:
        raise RuntimeError("No isolated Compose subnets available")
    proxy_subnet, db_subnet = free[:2]
    proxy_ip, backend_ip = str(proxy_subnet[10]), str(proxy_subnet[20])
    environment["TRUSTED_PROXIES"] = json.dumps([proxy_ip], separators=(",", ":"))
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "RESEND_API_KEY",
        "SENTRY_DSN",
        "SENTRY_FRONTEND_DSN",
        "SENTRY_AUTH_TOKEN",
        "SMTP_PASSWORD",
        "SMTP_USER",
    ):
        os.environ.pop(name, None)
    # The subprocess is an explicitly synthetic campaign; inherited values
    # must not override its env-file or activate an external provider.
    os.environ.update(environment)
    with tempfile.TemporaryDirectory(prefix="sso-container-") as temp:
        try:
            from scripts.rotate_keys import private_directory, write_private
        except ModuleNotFoundError:
            from rotate_keys import private_directory, write_private

        private = Path(temp) / "private"
        private_directory(private)
        envfile = private / ".env"
        write_private(
            envfile,
            ("\n".join(f"{key}={value}" for key, value in environment.items()) + "\n").encode(),
        )
        override = private / "compose.override.yml"
        write_private(
            override,
            f'''services:
  db:
    container_name: {project}-db
  backend:
    container_name: {project}-backend
    environment:
      TRUSTED_PROXIES: '["{proxy_ip}"]'
    networks:
      proxy_network:
        ipv4_address: {backend_ip}
  frontend:
    container_name: {project}-frontend
    ports: !override ["127.0.0.1:{port}:8080"]
    networks:
      proxy_network:
        ipv4_address: {proxy_ip}
networks:
  proxy_network:
    ipam:
      config: !override [{{subnet: {proxy_subnet}}}]
  db_network:
    ipam:
      config: !override [{{subnet: {db_subnet}}}]
'''.encode(),
        )
        compose = [
            "docker",
            "compose",
            "--env-file",
            str(envfile),
            "-f",
            str(ROOT / "docker-compose.yml"),
            "-f",
            str(override),
            "-p",
            project,
        ]
        tag_campaign_images(project)
        try:
            command(compose + ["up", "-d", "--no-build"])
            wait_initial_readiness()
            require_container_boundaries(compose)
            require_runtime_and_browser(compose)
            require_database_outage_recovery(compose)
            print(
                "Compose runtime: non-root/read-only/capabilities/resources/runtime role/CSP/DB outage and recovery passed"
            )
        finally:
            cleanup_owned_campaign(compose, project, volume)


if __name__ == "__main__":
    run()
