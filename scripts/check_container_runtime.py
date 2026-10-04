"""Run an owned, synthetic Compose acceptance campaign; never target existing volumes."""

import json
import os
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
        response = urllib.request.urlopen("http://127.0.0.1:3000" + path, timeout=3)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, dict(response.headers), response.read(65536)


def run() -> None:
    project = "sso-ci-" + uuid.uuid4().hex
    volume = project + "_sso_db_data"
    existing = command(["docker", "volume", "ls", "--format", "{{.Name}}"])
    if volume in existing.splitlines():
        raise RuntimeError("Campaign volume exists; refusing to use it")
    sha = command(["git", "rev-parse", "HEAD"]).strip()
    if len(sha) != 40:
        raise RuntimeError("Missing exact build revision")
    environment = {
        "ALX_BUILD_SHA": sha,
        "POSTGRES_USER": "ci_owner",
        "POSTGRES_DB": "sso_ci_test",
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "SSO_RUNTIME_PASSWORD": secrets.token_hex(32),
        "SSO_MIGRATOR_PASSWORD": secrets.token_hex(32),
        "ENVIRONMENT": "testing",
        "SESSION_SECRET_KEY": secrets.token_hex(64),
        "BASE_URL": "http://localhost:3000",
        "FRONTEND_URL": "http://localhost:3000",
        "OIDC_ISSUER": "http://localhost:3000",
        "WEBAUTHN_RP_ID": "localhost",
        "WEBAUTHN_ORIGIN": "http://localhost:3000",
    }
    with tempfile.TemporaryDirectory(prefix="sso-container-") as temp:
        envfile = Path(temp) / ".env"
        envfile.write_text(
            "\n".join(f"{key}={value}" for key, value in environment.items()) + "\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            envfile.chmod(0o600)
        compose = ["docker", "compose", "--env-file", str(envfile), "-p", project]
        for service in ("backend", "migrate", "frontend"):
            command(
                [
                    "docker",
                    "tag",
                    "sso-frontend-check" if service == "frontend" else "sso-backend-check",
                    project + "-" + service,
                ]
            )
        try:
            command(compose + ["up", "-d", "--no-build"])
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
                env=os.environ | {"PLAYWRIGHT_BASE_URL": "http://localhost:3000"},
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
            command(compose + ["stop", "db"])
            assert request("/health/ready")[0] == 503
            command(compose + ["start", "db"])
            deadline = time.monotonic() + 30
            while request("/health/ready")[0] != 200:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Database restart readiness timeout")
                time.sleep(1)
            print(
                "Compose runtime: non-root/read-only/capabilities/resources/runtime role/CSP/DB outage and recovery passed"
            )
        finally:
            # Stop only this campaign. Delete only its exact, labelled new volume.
            command(compose + ["down"], check=True)
            result = command(["docker", "volume", "ls", "--format", "{{.Name}}"])
            if volume in result.splitlines():
                description = json.loads(command(["docker", "volume", "inspect", volume]))[0]
                assert description["Labels"]["com.docker.compose.project"] == project
                assert description["Name"] == volume
                command(["docker", "volume", "rm", volume])


if __name__ == "__main__":
    run()
