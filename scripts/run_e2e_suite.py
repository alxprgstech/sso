"""
ALXPRGS SSO - Автоматизированный запуск E2E браузерных тестов в изолированном окружении (GOAL-06).
Обеспечивает:
1. Запуск frontend preview (порт 5173).
2. Запуск default-off профиля бэкенда (порт 8000).
3. Preflight проверку capabilities бэкенда и frontend proxy.
4. Прогон SSO, privacy и appearance UI regression.
5. Остановку default-off бэкенда и подтверждение освобождения порта.
6. Запуск enabled профиля бэкенда (порт 8000).
7. Preflight проверку capabilities бэкенда и frontend proxy.
8. Прогон enabled Passkey и privacy.
9. Надежную остановку всех процессов в finally блоке.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
MANAGE_SCRIPT = os.path.join(ROOT_DIR, "scripts", "manage_test_server.py")
SEED_SCRIPT = os.path.join(ROOT_DIR, "scripts", "prepare_e2e_data.py")


def run_cmd(cmd: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> int:
    print(f"[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd or ROOT_DIR, env=env, text=True)
    return res.returncode


@dataclass(frozen=True)
class CampaignPaths:
    frontend_pid: str
    frontend_log: str
    backend_pid: str
    backend_log: str


@dataclass(frozen=True)
class BrowserProfile:
    name: str
    env: dict[str, str]
    specs: tuple[str, ...]


def browser_environment() -> dict[str, str]:
    db_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://sso_test_user:sso_test_password@localhost:5433/alxprgs_sso_test",
    )

    base_env = os.environ.copy()
    # All services in this campaign are loopback. System HTTP proxies must not
    # receive synthetic OAuth codes/client secrets intended for these services.
    loopback_bypass = ",".join(
        filter(
            None,
            [base_env.get("no_proxy", base_env.get("NO_PROXY", "")), "localhost,127.0.0.1,::1"],
        )
    )
    base_env.update(NO_PROXY=loopback_bypass, no_proxy=loopback_bypass)
    base_env.update(
        {
            "TEST_DATABASE_URL": db_url,
            "DATABASE_URL": db_url,
            "DATABASE_URL_SYNC": db_url,
            "SESSION_SECRET_KEY": "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only",
            "TOTP_ENCRYPTION_KEY": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
            "JWT_PRIVATE_KEY_PEM": "",
            "OIDC_ISSUER": "https://auth.alxprgs.tech",
            "FRONTEND_URL": "http://localhost:5173",
            "WEBAUTHN_RP_ID": "localhost",
            "WEBAUTHN_ORIGIN": "http://localhost:5173",
            "PORT": "8000",
            "PYTHON_BIN": sys.executable,
            "PLAYWRIGHT_BASE_URL": "http://localhost:5173",
        }
    )

    return base_env


def browser_profiles(suite: str, base_env: dict[str, str]) -> list[BrowserProfile]:
    profiles = []
    definitions = (
        (
            "default-off",
            ("sso", "all"),
            ("sso", "multi_client_sso", "telemetry", "privacy", "appearance"),
        ),
        ("enabled", ("passkey", "all"), ("passkey", "telemetry", "privacy")),
    )
    for name, suites, specs in definitions:
        if suite not in suites:
            continue
        env = base_env.copy()
        enabled = name == "enabled"
        flag = str(enabled).lower()
        env.update(
            FEATURE_TOTP_ENABLED=flag,
            FEATURE_PASSKEY_ENABLED=flag,
            FEATURE_RECOVERY_CODES_ENABLED=flag,
            FEATURE_EMAIL_VERIFICATION_ENABLED="true",
            REQUIRE_VERIFIED_EMAIL="false",
            PRIVACY_ENABLED_PROFILE="1" if enabled else "0",
        )
        profiles.append(BrowserProfile(name, env, tuple(f"e2e/{spec}.spec.ts" for spec in specs)))
    return profiles


def ensure_frontend_build() -> int:
    if Path(FRONTEND_DIR, "dist", "index.html").exists():
        return 0
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    return run_cmd([npm, "run", "build"], cwd=FRONTEND_DIR)


def start_browser_frontend(paths: CampaignPaths) -> int:
    return run_cmd(
        [
            sys.executable,
            MANAGE_SCRIPT,
            "start-frontend",
            "--port",
            "5173",
            "--pidfile",
            paths.frontend_pid,
            "--logfile",
            paths.frontend_log,
            "--backend-url",
            "http://localhost:8000",
        ]
    )


def stop_browser_backend(paths: CampaignPaths) -> int:
    return run_cmd(
        [sys.executable, MANAGE_SCRIPT, "stop", "--pidfile", paths.backend_pid, "--port", "8000"]
    )


def run_browser_profile(profile: BrowserProfile, paths: CampaignPaths) -> int:
    print(f"[PROFILE] {profile.name}")
    if run_cmd([sys.executable, SEED_SCRIPT], env=profile.env):
        return 1
    if run_cmd(
        [
            sys.executable,
            MANAGE_SCRIPT,
            "start",
            "--port",
            "8000",
            "--pidfile",
            paths.backend_pid,
            "--logfile",
            paths.backend_log,
            "--profile",
            profile.name,
        ],
        env=profile.env,
    ):
        return 1
    if run_cmd(
        [
            sys.executable,
            MANAGE_SCRIPT,
            "preflight",
            "--profile",
            profile.name,
            "--backend-url",
            "http://127.0.0.1:8000",
            "--frontend-url",
            "http://localhost:5173",
        ]
    ):
        return 1
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    result = run_cmd([npx, "playwright", "test", *profile.specs], cwd=FRONTEND_DIR, env=profile.env)
    if result:
        return result
    return stop_browser_backend(paths)


def cleanup_browser_campaign(paths: CampaignPaths) -> None:
    print("[CLEANUP] Stopping owned test servers")
    stop_browser_backend(paths)
    run_cmd(
        [sys.executable, MANAGE_SCRIPT, "stop", "--pidfile", paths.frontend_pid, "--port", "5173"]
    )


def run_e2e(suite: str) -> int:
    if suite == "email":
        return run_email_e2e()
    temp = Path(tempfile.gettempdir())
    paths = CampaignPaths(
        *(str(temp / f"sso_{suffix}") for suffix in ("fe.pid", "fe.log", "be.pid", "be.log"))
    )
    profiles = browser_profiles(suite, browser_environment())
    try:
        if ensure_frontend_build():
            return 1
        if start_browser_frontend(paths):
            return 1
        for profile in profiles:
            result = run_browser_profile(profile, paths)
            if result:
                return result
    finally:
        cleanup_browser_campaign(paths)
    return 0


def run_email_e2e() -> int:
    """Reuse lifecycle tools, but isolate credentials and suppress raw child output."""
    sys.path.insert(0, ROOT_DIR)
    sys.path.insert(0, os.path.join(ROOT_DIR, "backend"))
    from tests.db_guard import get_test_database_url
    from tests.helpers.email_test_settings import load_email_settings
    from tests.helpers.testmail_cli import preflight

    report_path = Path(ROOT_DIR) / "artifacts/email/runner-summary.json"
    stages: list[dict[str, object]] = []
    active_stage = "configuration"
    result = 1
    try:
        settings = load_email_settings()
        active_stage = "provider-preflight"
        preflight(settings)
        db_url = get_test_database_url()
        common = {
            "TEST_DATABASE_URL": db_url,
            "DATABASE_URL": db_url,
            "DATABASE_URL_SYNC": db_url,
            "BASE_URL": "http://localhost:8000",
            "FRONTEND_URL": "http://localhost:5173",
            "PLAYWRIGHT_BASE_URL": "http://localhost:5173",
            "PYTHON_BIN": sys.executable,
            "EMAIL_PROVIDER": "ses",
            "ENVIRONMENT": "testing",
            "REQUIRE_VERIFIED_EMAIL": "true",
            "FEATURE_TOTP_ENABLED": "false",
            "FEATURE_PASSKEY_ENABLED": "false",
            "FEATURE_RECOVERY_CODES_ENABLED": "false",
            "FEATURE_EMAIL_VERIFICATION_ENABLED": "true",
            "SES_REGION": settings.SES_REGION,
            "SES_FROM_EMAIL": settings.SES_FROM_EMAIL,
            "SES_FROM_NAME": settings.SES_FROM_NAME,
        }
        backend_env = settings.process_environment(recipient="backend") | common
        helper_env = settings.process_environment() | common
        frontend_env = settings.process_environment(recipient="frontend") | common
        npx = "npx.cmd" if sys.platform == "win32" else "npx"

        def stage(name, command, env, *, cwd=ROOT_DIR):
            nonlocal active_stage
            active_stage = name
            child = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
            stages.append({"stage": name, "exit_status": child.returncode})
            print(f"Email stage {name}: {'passed' if child.returncode == 0 else 'failed'}")
            if child.returncode:
                raise RuntimeError("Email stage failed")

        with tempfile.TemporaryDirectory(prefix="sso-email-") as directory:
            fe_pid, be_pid = os.path.join(directory, "fe.pid"), os.path.join(directory, "be.pid")
            try:
                if not os.path.exists(os.path.join(FRONTEND_DIR, "dist/index.html")):
                    npm = "npm.cmd" if sys.platform == "win32" else "npm"
                    stage("build", [npm, "run", "build"], frontend_env, cwd=FRONTEND_DIR)
                stage("seed", [sys.executable, SEED_SCRIPT], frontend_env)
                stage(
                    "frontend",
                    [
                        sys.executable,
                        MANAGE_SCRIPT,
                        "start-frontend",
                        "--port",
                        "5173",
                        "--pidfile",
                        fe_pid,
                        "--logfile",
                        os.path.join(directory, "frontend.log"),
                        "--backend-url",
                        "http://localhost:8000",
                    ],
                    frontend_env,
                )
                stage(
                    "backend",
                    [
                        sys.executable,
                        MANAGE_SCRIPT,
                        "start",
                        "--port",
                        "8000",
                        "--pidfile",
                        be_pid,
                        "--logfile",
                        os.path.join(directory, "backend.log"),
                        "--profile",
                        "email",
                    ],
                    backend_env,
                )
                stage(
                    "capabilities",
                    [
                        sys.executable,
                        MANAGE_SCRIPT,
                        "preflight",
                        "--profile",
                        "email",
                        "--backend-url",
                        "http://127.0.0.1:8000",
                        "--frontend-url",
                        "http://localhost:5173",
                    ],
                    frontend_env,
                )
                stage(
                    "browser",
                    [npx, "playwright", "test", "--config", "playwright.email.config.ts"],
                    helper_env,
                    cwd=FRONTEND_DIR,
                )
            finally:
                cleanup_failed = False
                for pidfile, port in ((be_pid, "8000"), (fe_pid, "5173")):
                    stopped = subprocess.run(
                        [
                            sys.executable,
                            MANAGE_SCRIPT,
                            "stop",
                            "--pidfile",
                            pidfile,
                            "--port",
                            port,
                        ],
                        cwd=ROOT_DIR,
                        env=frontend_env,
                        capture_output=True,
                        text=True,
                    )
                    stages.append({"stage": f"stop-{port}", "exit_status": stopped.returncode})
                    cleanup_failed |= bool(stopped.returncode)
                if cleanup_failed:
                    active_stage = "cleanup"
                    raise RuntimeError("Email server cleanup failed")
        result = 0
    except Exception:
        print(f"Email E2E failed at {active_stage}; raw output withheld. See docs/testing/email.md")
    finally:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps({"exit_status": result, "last_stage": active_stage, "stages": stages}),
            encoding="utf-8",
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Автоматический запуск E2E сьюитов")
    parser.add_argument(
        "--suite",
        choices=["sso", "passkey", "all", "email"],
        default="all",
        help="Какой сьюит запускать (sso, passkey, all)",
    )
    args = parser.parse_args()
    return run_e2e(args.suite)


if __name__ == "__main__":
    sys.exit(main())
