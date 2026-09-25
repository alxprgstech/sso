"""
ALXPRGS SSO - Автоматизированный запуск E2E браузерных тестов в изолированном окружении (GOAL-06).
Обеспечивает:
1. Запуск frontend preview (порт 5173).
2. Запуск default-off профиля бэкенда (порт 8000).
3. Preflight проверку capabilities бэкенда и frontend proxy.
4. Прогон e2e/sso.spec.ts.
5. Остановку default-off бэкенда и подтверждение освобождения порта.
6. Запуск enabled профиля бэкенда (порт 8000).
7. Preflight проверку capabilities бэкенда и frontend proxy.
8. Прогон e2e/passkey.spec.ts.
9. Надежную остановку всех процессов в finally блоке.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
MANAGE_SCRIPT = os.path.join(ROOT_DIR, "scripts", "manage_test_server.py")
SEED_SCRIPT = os.path.join(ROOT_DIR, "scripts", "prepare_e2e_data.py")


def run_cmd(cmd: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> int:
    print(f"[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd or ROOT_DIR, env=env, text=True)
    return res.returncode


def run_e2e(suite: str) -> int:
    temp_dir = tempfile.gettempdir()
    fe_pid = os.path.join(temp_dir, "sso_fe.pid")
    fe_log = os.path.join(temp_dir, "sso_fe.log")
    be_pid = os.path.join(temp_dir, "sso_be.pid")
    be_log = os.path.join(temp_dir, "sso_be.log")

    db_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://sso_test_user:sso_test_password@localhost:5433/alxprgs_sso_test",
    )

    base_env = os.environ.copy()
    base_env.update(
        {
            "TEST_DATABASE_URL": db_url,
            "DATABASE_URL": db_url,
            "DATABASE_URL_SYNC": db_url,
            "SESSION_SECRET_KEY": "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only",
            "TOTP_ENCRYPTION_KEY": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
            "JWT_PRIVATE_KEY_PEM": "",
            "OIDC_ISSUER": "https://auth.alxprgs.tech",
            "WEBAUTHN_RP_ID": "localhost",
            "WEBAUTHN_ORIGIN": "http://localhost:5173",
            "PORT": "8000",
            "PYTHON_BIN": sys.executable,
            "PLAYWRIGHT_BASE_URL": "http://localhost:5173",
        }
    )

    default_off_env = base_env.copy()
    default_off_env.update(
        {
            "FEATURE_TOTP_ENABLED": "false",
            "FEATURE_PASSKEY_ENABLED": "false",
            "FEATURE_RECOVERY_CODES_ENABLED": "false",
            "FEATURE_EMAIL_VERIFICATION_ENABLED": "false",
            "REQUIRE_VERIFIED_EMAIL": "false",
        }
    )

    enabled_env = base_env.copy()
    enabled_env.update(
        {
            "FEATURE_TOTP_ENABLED": "true",
            "FEATURE_PASSKEY_ENABLED": "true",
            "FEATURE_RECOVERY_CODES_ENABLED": "true",
            "FEATURE_EMAIL_VERIFICATION_ENABLED": "true",
            "REQUIRE_VERIFIED_EMAIL": "false",
        }
    )

    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"

    try:
        # 0. Проверка сборки фронтенда
        dist_index = os.path.join(FRONTEND_DIR, "dist", "index.html")
        if not os.path.exists(dist_index):
            print("\n================== 0. СБОРКА ФРОНТЕНДА ДЛЯ PREVIEW ==================")
            npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
            bld_res = subprocess.run([npm_cmd, "run", "build"], cwd=FRONTEND_DIR)
            if bld_res.returncode != 0:
                print("[ERROR] Не удалось выполнить сборку фронтенда ('npm run build')!")
                return 1

        # 1. Запуск фронтенда
        print("\n================== 1. ЗАПУСК FRONTEND PREVIEW ==================")
        fe_start = subprocess.run(
            [
                sys.executable,
                MANAGE_SCRIPT,
                "start-frontend",
                "--port",
                "5173",
                "--pidfile",
                fe_pid,
                "--logfile",
                fe_log,
                "--backend-url",
                "http://localhost:8000",
            ],
            cwd=ROOT_DIR,
        )
        if fe_start.returncode != 0:
            print("[ERROR] Не удалось запустить frontend preview!")
            return 1

        # 2. SSO Suite (default-off)
        if suite in ("sso", "all"):
            print("\n================== 2. СЬЮИТ: SSO (DEFAULT-OFF) ==================")
            # Seed
            seed_res = subprocess.run(
                [sys.executable, SEED_SCRIPT], env=default_off_env, cwd=ROOT_DIR
            )
            if seed_res.returncode != 0:
                print("[ERROR] Ошибка подготовки тестовых данных default-off!")
                return 1

            # Start backend
            be_start = subprocess.run(
                [
                    sys.executable,
                    MANAGE_SCRIPT,
                    "start",
                    "--port",
                    "8000",
                    "--pidfile",
                    be_pid,
                    "--logfile",
                    be_log,
                    "--profile",
                    "default-off",
                ],
                env=default_off_env,
                cwd=ROOT_DIR,
            )
            if be_start.returncode != 0:
                print("[ERROR] Не удалось запустить default-off бэкенд!")
                return 1

            # Preflight
            pref_res = subprocess.run(
                [
                    sys.executable,
                    MANAGE_SCRIPT,
                    "preflight",
                    "--profile",
                    "default-off",
                    "--backend-url",
                    "http://127.0.0.1:8000",
                    "--frontend-url",
                    "http://localhost:5173",
                ],
                cwd=ROOT_DIR,
            )
            if pref_res.returncode != 0:
                print("[ERROR] Preflight проверка default-off провалена!")
                return 1

            # Playwright
            pw_res = subprocess.run(
                [npx_cmd, "playwright", "test", "e2e/sso.spec.ts"],
                cwd=FRONTEND_DIR,
                env=default_off_env,
            )
            if pw_res.returncode != 0:
                print("[ERROR] Playwright SSO тесты завершились с ошибкой!")
                return pw_res.returncode

            # Stop default-off backend
            be_stop = subprocess.run(
                [
                    sys.executable,
                    MANAGE_SCRIPT,
                    "stop",
                    "--pidfile",
                    be_pid,
                    "--port",
                    "8000",
                ],
                cwd=ROOT_DIR,
            )
            if be_stop.returncode != 0:
                print("[ERROR] Ошибка остановки default-off бэкенда!")
                return 1
            print("[INFO] Default-off бэкенд успешно остановлен, порт 8000 свободен.\n")

        # 3. Passkey Suite (enabled)
        if suite in ("passkey", "all"):
            print("\n================== 3. СЬЮИТ: PASSKEY (ENABLED) ==================")
            # Seed
            seed_res = subprocess.run([sys.executable, SEED_SCRIPT], env=enabled_env, cwd=ROOT_DIR)
            if seed_res.returncode != 0:
                print("[ERROR] Ошибка подготовки тестовых данных enabled!")
                return 1

            # Start backend
            be_start = subprocess.run(
                [
                    sys.executable,
                    MANAGE_SCRIPT,
                    "start",
                    "--port",
                    "8000",
                    "--pidfile",
                    be_pid,
                    "--logfile",
                    be_log,
                    "--profile",
                    "enabled",
                ],
                env=enabled_env,
                cwd=ROOT_DIR,
            )
            if be_start.returncode != 0:
                print("[ERROR] Не удалось запустить enabled бэкенд!")
                return 1

            # Preflight
            pref_res = subprocess.run(
                [
                    sys.executable,
                    MANAGE_SCRIPT,
                    "preflight",
                    "--profile",
                    "enabled",
                    "--backend-url",
                    "http://127.0.0.1:8000",
                    "--frontend-url",
                    "http://localhost:5173",
                ],
                cwd=ROOT_DIR,
            )
            if pref_res.returncode != 0:
                print("[ERROR] Preflight проверка enabled провалена!")
                return 1

            # Playwright
            pw_res = subprocess.run(
                [npx_cmd, "playwright", "test", "e2e/passkey.spec.ts"],
                cwd=FRONTEND_DIR,
                env=enabled_env,
            )
            if pw_res.returncode != 0:
                print("[ERROR] Playwright Passkey тесты завершились с ошибкой!")
                return pw_res.returncode

            # Stop enabled backend
            be_stop = subprocess.run(
                [
                    sys.executable,
                    MANAGE_SCRIPT,
                    "stop",
                    "--pidfile",
                    be_pid,
                    "--port",
                    "8000",
                ],
                cwd=ROOT_DIR,
            )
            if be_stop.returncode != 0:
                print("[ERROR] Ошибка остановки enabled бэкенда!")
                return 1
            print("[INFO] Enabled бэкенд успешно остановлен, порт 8000 свободен.\n")

    finally:
        print("\n================== CLEANUP: ОСТАНОВКА ПРОЦЕССОВ ==================")
        subprocess.run(
            [sys.executable, MANAGE_SCRIPT, "stop", "--pidfile", be_pid, "--port", "8000"],
            cwd=ROOT_DIR,
        )
        subprocess.run(
            [sys.executable, MANAGE_SCRIPT, "stop", "--pidfile", fe_pid, "--port", "5173"],
            cwd=ROOT_DIR,
        )
        print("[CLEANUP-DONE] Все тестовые серверы остановлены.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Автоматический запуск E2E сьюитов")
    parser.add_argument(
        "--suite",
        choices=["sso", "passkey", "all"],
        default="all",
        help="Какой сьюит запускать (sso, passkey, all)",
    )
    args = parser.parse_args()
    return run_e2e(args.suite)


if __name__ == "__main__":
    sys.exit(main())
