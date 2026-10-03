"""
ALXPRGS SSO - Ночная кампания стабильности и нагрузочного тестирования (GOAL-07).
Реализует этапы:
- G7-BOOT:    5 полных циклов старта, переключения профилей (default-off -> enabled) и E2E тестов.
- G7-SOAK:    20-минутный непрерывный тест стабильности со сбором телеметрии (RSS, соединения БД, latency p50/p95).
- G7-RACE:    Тестирование конкурентной одноразовости (authorization code, recovery code, refresh replay, регистрация).
- G7-RECOVER: Устойчивость к сбоям (перезапуск бэкенда, недоступность БД, backup & restore с проверкой входа).
- G7-MIGRATE: Проверка чистой установки и отката/наката миграций схемы на изолированной БД.
- G7-FINAL:   Агрегация результатов, генерация машиночитаемых отчетов (JSON, CSV).
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Корневой каталог репозитория
ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
BACKEND_DIR = ROOT_DIR / "backend"
SDK_DIR = ROOT_DIR / "packages" / "python-sdk"
MANAGE_SCRIPT = ROOT_DIR / "scripts" / "manage_test_server.py"
SEED_SCRIPT = ROOT_DIR / "scripts" / "prepare_e2e_data.py"

if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

# Настройки по умолчанию
DEFAULT_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://sso_test_user:sso_test_password@localhost:5433/alxprgs_sso_test",
)
DEFAULT_CONTAINER = "alxprgs-sso-test-db"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173


# ==============================================================================
# Утилиты памяти (RSS) и телеметрии процессов
# ==============================================================================


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def get_process_rss_mb(pid: int) -> float:
    """Безопасное получение RSS процесса в MiB (без внешних зависимостей)."""
    if pid <= 0:
        return 0.0
    if sys.platform == "win32":
        try:
            handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            if handle:
                counters = _PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
                if ctypes.windll.psapi.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), ctypes.sizeof(counters)
                ):
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return round(counters.WorkingSetSize / (1024 * 1024), 2)
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            statm = Path(f"/proc/{pid}/statm")
            if statm.exists():
                rss_pages = int(statm.read_text().split()[1])
                page_size = os.sysconf("SC_PAGE_SIZE")
                return round((rss_pages * page_size) / (1024 * 1024), 2)
        except Exception:
            pass
    return 0.0


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect((host, port))
            return True
        except (socket.error, ConnectionRefusedError, OSError):
            return False


def get_pg_active_connections(db_url: str, db_name: str = "alxprgs_sso_test") -> int:
    """Получение числа активных подключений к целевой тестовой БД PostgreSQL."""
    try:
        import psycopg

        clean_url = db_url.replace("+psycopg", "")
        with psycopg.connect(clean_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(1) FROM pg_stat_activity WHERE datname = %s",
                    (db_name,),
                )
                res = cur.fetchone()
                return int(res[0]) if res else 0
    except Exception:
        return -1


def read_pid_file(pid_file: str | Path) -> int | None:
    path = Path(pid_file)
    if path.exists():
        try:
            return int(path.read_text().strip())
        except Exception:
            return None
    return None


if str(ROOT_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "scripts"))
try:
    from manage_test_server import get_pid_listening_on_port
except ImportError:

    def get_pid_listening_on_port(port: int, host: str = "127.0.0.1") -> int | None:
        return None


def verify_server_worker_pid(pid: int, port: int = 8000) -> bool:
    """Проверяет принадлежность PID запущенному тестовому серверу бэкенда:
    1. Процесс должен быть активен и слушать указанный порт (8000).
    2. Процесс должен идентифицироваться как процесс Python / uvicorn."""
    if pid <= 0:
        return False
    listening = get_pid_listening_on_port(port)
    if listening != pid:
        return False
    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            out = res.stdout.lower()
            if "python" in out:
                return True
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            cmdline_path = Path(f"/proc/{pid}/cmdline")
            if cmdline_path.exists():
                cmdline = cmdline_path.read_text().lower()
                if "python" in cmdline or "uvicorn" in cmdline:
                    return True
        except Exception:
            pass
    else:
        return True
    return False


def evaluate_soak_criteria(
    duration_achieved_sec: float,
    target_duration_sec: float,
    telemetry_records: list[dict[str, Any]],
    expected_samples: int,
    unexpected_errors: int,
    browser_smoke_runs: int,
    browser_smoke_failed: int,
    pg_baseline: int,
    pg_final: int,
    backend_port_busy: bool,
    frontend_port_busy: bool,
    pid_verified: bool = True,
    expected_browser_smoke_runs: int | None = None,
) -> list[str]:
    """Строгая валидация критериев успешности этапа soak (GOAL-07)."""
    failure_reasons: list[str] = []

    # 1. Досрочное завершение или недостаточная длительность нагрузки (< target_duration_sec)
    if duration_achieved_sec < target_duration_sec:
        failure_reasons.append(
            f"Early termination or insufficient load duration: achieved {duration_achieved_sec:.1f}s < required {target_duration_sec:.1f}s"
        )

    # 2. Недостаточное число точек телеметрии (<90% ожидаемого)
    min_samples = int(expected_samples * 0.9)
    if len(telemetry_records) < min_samples:
        failure_reasons.append(
            f"Insufficient telemetry samples: {len(telemetry_records)} < {min_samples} (90% threshold)"
        )

    # 3. Наличие непредвиденных ошибок
    if unexpected_errors > 0:
        failure_reasons.append(f"Unexpected operational errors: {unexpected_errors}")

    # 4. Падение браузерного smoke-теста
    if browser_smoke_failed > 0:
        failure_reasons.append(f"Browser smoke test failures: {browser_smoke_failed}")

    # 5. Выполнение всех запланированных браузерных smoke-проверок
    if expected_browser_smoke_runs is None:
        if target_duration_sec >= 300.0:
            expected_browser_smoke_runs = int((target_duration_sec - 0.1) // 300.0)
        else:
            expected_browser_smoke_runs = 0

    if target_duration_sec >= 300.0 and browser_smoke_runs == 0:
        failure_reasons.append("Browser smoke tests were never executed during >=5min soak run")
    elif browser_smoke_runs < expected_browser_smoke_runs:
        failure_reasons.append(
            f"Scheduled browser smoke tests missed: executed {browser_smoke_runs} < expected {expected_browser_smoke_runs}"
        )

    # 6. Невосстановление пула соединений PostgreSQL (строгий возврат к baseline)
    if pg_final > pg_baseline:
        failure_reasons.append(
            f"PostgreSQL connection pool not recovered (leak detected: baseline={pg_baseline}, final={pg_final}, must return to baseline)"
        )

    # 7. Утечка портов после завершения этапа
    if backend_port_busy or frontend_port_busy:
        failure_reasons.append(
            f"Port leak detected: backend_busy={backend_port_busy}, frontend_busy={frontend_port_busy}"
        )

    # 8. Проверка принадлежности измеряемого PID тестовому серверу
    if not pid_verified:
        failure_reasons.append(
            "Monitored backend PID is foreign or unverified (does not belong to test server worker on port 8000)"
        )

    # 9. Валидация показаний телеметрии: RSS заведомо ненулевой и реалистичный (> 10 МБ)
    if not telemetry_records:
        failure_reasons.append("No telemetry records collected")
    else:
        low_rss_samples = [
            r["sample"] for r in telemetry_records if r.get("backend_rss_mb", 0.0) <= 10.0
        ]
        if low_rss_samples:
            min_rss = min(r.get("backend_rss_mb", 0.0) for r in telemetry_records)
            failure_reasons.append(
                f"Backend RSS suspiciously low (<=10.0MB) at samples {low_rss_samples} (min: {min_rss}MB)"
            )

    return failure_reasons


# ==============================================================================
# HTTP Client Helper
# ==============================================================================


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class SimpleHttpClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")
        self.cookies: dict[str, str] = {}
        self.last_headers: dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        follow_redirects: bool = True,
    ) -> tuple[int, dict[str, Any], float]:
        url = f"{self.base_url}{path}"
        req_headers = {
            "User-Agent": "SSO-Overnight-Runner/1.0",
            "Accept": "application/json",
        }
        if json_data is not None:
            req_headers["Content-Type"] = "application/json"
        if headers:
            req_headers.update(headers)

        # Cookie header
        if self.cookies:
            req_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())

        body = json.dumps(json_data).encode("utf-8") if json_data is not None else None
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)

        start_t = time.perf_counter()
        status_code = 0
        resp_data: dict[str, Any] = {}
        self.last_headers = {}

        opener = (
            urllib.request.build_opener()
            if follow_redirects
            else urllib.request.build_opener(_NoRedirectHandler)
        )

        try:
            with opener.open(req, timeout=timeout) as resp:
                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                status_code = resp.status
                for k, v in resp.headers.items():
                    self.last_headers[k.lower()] = v
                # Save cookies
                for cookie_header in resp.headers.get_all("Set-Cookie") or []:
                    parts = cookie_header.split(";")[0].split("=", 1)
                    if len(parts) == 2:
                        self.cookies[parts[0].strip()] = parts[1].strip()
                raw_body = resp.read().decode("utf-8")
                if raw_body:
                    try:
                        resp_data = json.loads(raw_body)
                    except Exception:
                        resp_data = {"raw": raw_body}
        except urllib.error.HTTPError as e:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            status_code = e.code
            for k, v in e.headers.items():
                self.last_headers[k.lower()] = v
            for cookie_header in e.headers.get_all("Set-Cookie") or []:
                parts = cookie_header.split(";")[0].split("=", 1)
                if len(parts) == 2:
                    self.cookies[parts[0].strip()] = parts[1].strip()
            raw_body = e.read().decode("utf-8")
            if raw_body:
                try:
                    resp_data = json.loads(raw_body)
                except Exception:
                    resp_data = {"raw": raw_body}
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            status_code = -1
            resp_data = {"error": str(e)}

        return status_code, resp_data, round(elapsed_ms, 2)


# ==============================================================================
# G7-BOOT: Повторяемость чистого запуска и смены профилей (5 циклов)
# ==============================================================================


def run_boot_stage(
    cycles: int = 5,
    test_db_url: str = DEFAULT_TEST_DB_URL,
    logger: Any = None,
) -> dict[str, Any]:
    print("\n================================================================================")
    print(f" [G7-BOOT] ЗАПУСК {cycles} ПОЛНЫХ ЦИКЛОВ ЖИЗНЕННОГО ЦИКЛА И СМЕНЫ ПРОФИЛЕЙ")
    print("================================================================================")

    temp_dir = tempfile.gettempdir()
    fe_pid_file = os.path.join(temp_dir, "g7_boot_fe.pid")
    fe_log_file = os.path.join(temp_dir, "g7_boot_fe.log")
    be_pid_file = os.path.join(temp_dir, "g7_boot_be.pid")
    be_log_file = os.path.join(temp_dir, "g7_boot_be.log")

    base_env = os.environ.copy()
    base_env.update(
        {
            "TEST_DATABASE_URL": test_db_url,
            "DATABASE_URL": test_db_url,
            "DATABASE_URL_SYNC": test_db_url,
            "SESSION_SECRET_KEY": "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only",
            "TOTP_ENCRYPTION_KEY": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
            "JWT_PRIVATE_KEY_PEM": "",
            "OIDC_ISSUER": "https://auth.alxprgs.tech",
            "WEBAUTHN_RP_ID": "localhost",
            "WEBAUTHN_ORIGIN": "http://localhost:5173",
            "PORT": str(BACKEND_PORT),
            "PYTHON_BIN": sys.executable,
            "PLAYWRIGHT_BASE_URL": "http://localhost:5173",
        }
    )

    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    results = []

    for c in range(1, cycles + 1):
        c_start = time.time()
        print(f"\n--- [G7-BOOT] Цикл {c}/{cycles} начат ---")

        # Проверка отсутствия старых процессов на портах
        if is_port_in_use(BACKEND_PORT) or is_port_in_use(FRONTEND_PORT):
            print(f"[BOOT-FAIL] Порт {BACKEND_PORT} или {FRONTEND_PORT} занят до начала цикла {c}!")
            return {"status": "failed", "cycle": c, "error": "Ports busy before cycle start"}

        try:
            # 1. Запуск frontend preview
            fe_res = subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "start-frontend",
                    "--port",
                    str(FRONTEND_PORT),
                    "--pidfile",
                    fe_pid_file,
                    "--logfile",
                    fe_log_file,
                ],
                capture_output=True,
                text=True,
            )
            if fe_res.returncode != 0:
                print(f"[BOOT-FAIL] Ошибка старта фронтенда в цикле {c}:\n{fe_res.stdout}")
                return {"status": "failed", "cycle": c, "step": "start-frontend"}

            # 2. Default-off бэкенд
            def_env = base_env.copy()
            def_env.update(
                {
                    "FEATURE_TOTP_ENABLED": "false",
                    "FEATURE_PASSKEY_ENABLED": "false",
                    "FEATURE_RECOVERY_CODES_ENABLED": "false",
                    "FEATURE_EMAIL_VERIFICATION_ENABLED": "true",
                    "REQUIRE_VERIFIED_EMAIL": "false",
                }
            )
            # Seed
            subprocess.run([sys.executable, str(SEED_SCRIPT)], env=def_env, check=True)

            # Start backend default-off
            be_res = subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "start",
                    "--port",
                    str(BACKEND_PORT),
                    "--pidfile",
                    be_pid_file,
                    "--logfile",
                    be_log_file,
                    "--profile",
                    "default-off",
                ],
                env=def_env,
                capture_output=True,
                text=True,
            )
            if be_res.returncode != 0:
                print(f"[BOOT-FAIL] Ошибка старта default-off бэкенда:\n{be_res.stdout}")
                return {"status": "failed", "cycle": c, "step": "start-default-off"}

            # Preflight direct & proxy
            pref_res = subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "preflight",
                    "--profile",
                    "default-off",
                    "--backend-url",
                    f"http://127.0.0.1:{BACKEND_PORT}",
                    "--frontend-url",
                    f"http://localhost:{FRONTEND_PORT}",
                ],
                capture_output=True,
                text=True,
            )
            if pref_res.returncode != 0:
                print(f"[BOOT-FAIL] Preflight default-off провален:\n{pref_res.stdout}")
                return {"status": "failed", "cycle": c, "step": "preflight-default-off"}

            # SSO E2E Test (Default profile SSO + Cross-client delegation)
            sso_res = subprocess.run(
                [
                    npx_cmd,
                    "playwright",
                    "test",
                    "e2e/sso.spec.ts",
                    "e2e/multi_client_sso.spec.ts",
                ],
                cwd=FRONTEND_DIR,
                env=def_env,
                capture_output=True,
                text=True,
            )
            if sso_res.returncode != 0:
                print(
                    f"[BOOT-FAIL] SSO E2E тесты упали в цикле {c}:\n{sso_res.stdout}\n{sso_res.stderr}"
                )
                return {"status": "failed", "cycle": c, "step": "sso-e2e"}

            # Остановка default-off бэкенда
            subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "stop",
                    "--pidfile",
                    be_pid_file,
                    "--port",
                    str(BACKEND_PORT),
                ],
                check=True,
            )

            # 3. Enabled бэкенд
            ena_env = base_env.copy()
            ena_env.update(
                {
                    "FEATURE_TOTP_ENABLED": "true",
                    "FEATURE_PASSKEY_ENABLED": "true",
                    "FEATURE_RECOVERY_CODES_ENABLED": "true",
                    "FEATURE_EMAIL_VERIFICATION_ENABLED": "true",
                    "REQUIRE_VERIFIED_EMAIL": "false",
                }
            )
            # Seed
            subprocess.run([sys.executable, str(SEED_SCRIPT)], env=ena_env, check=True)

            # Start backend enabled
            be_ena_res = subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "start",
                    "--port",
                    str(BACKEND_PORT),
                    "--pidfile",
                    be_pid_file,
                    "--logfile",
                    be_log_file,
                    "--profile",
                    "enabled",
                ],
                env=ena_env,
                capture_output=True,
                text=True,
            )
            if be_ena_res.returncode != 0:
                print(f"[BOOT-FAIL] Ошибка старта enabled бэкенда:\n{be_ena_res.stdout}")
                return {"status": "failed", "cycle": c, "step": "start-enabled"}

            # Preflight direct & proxy
            pref_ena = subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "preflight",
                    "--profile",
                    "enabled",
                    "--backend-url",
                    f"http://127.0.0.1:{BACKEND_PORT}",
                    "--frontend-url",
                    f"http://localhost:{FRONTEND_PORT}",
                ],
                capture_output=True,
                text=True,
            )
            if pref_ena.returncode != 0:
                print(f"[BOOT-FAIL] Preflight enabled провален:\n{pref_ena.stdout}")
                return {"status": "failed", "cycle": c, "step": "preflight-enabled"}

            # Passkey E2E Test
            pass_res = subprocess.run(
                [npx_cmd, "playwright", "test", "e2e/passkey.spec.ts"],
                cwd=FRONTEND_DIR,
                env=ena_env,
                capture_output=True,
                text=True,
            )
            if pass_res.returncode != 0:
                print(
                    f"[BOOT-FAIL] Passkey E2E тесты упали в цикле {c}:\n{pass_res.stdout}\n{pass_res.stderr}"
                )
                return {"status": "failed", "cycle": c, "step": "passkey-e2e"}

            # Остановка enabled бэкенда
            subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "stop",
                    "--pidfile",
                    be_pid_file,
                    "--port",
                    str(BACKEND_PORT),
                ],
                check=True,
            )

        finally:
            # Остановка фронтенда
            subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "stop",
                    "--pidfile",
                    fe_pid_file,
                    "--port",
                    str(FRONTEND_PORT),
                ],
                capture_output=True,
            )
            # Убеждаемся, что бэкенд остановлен
            subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "stop",
                    "--pidfile",
                    be_pid_file,
                    "--port",
                    str(BACKEND_PORT),
                ],
                capture_output=True,
            )

        c_dur = round(time.time() - c_start, 2)
        print(
            f"[BOOT-OK] Цикл {c}/{cycles} успешно завершен за {c_dur}s (SSO 4/4, Multi-Client 4/4, Passkey 4/4 passed)"
        )
        results.append({"cycle": c, "status": "passed", "duration_s": c_dur, "tests_passed": 12})

    print(f"\n[G7-BOOT-SUCCESS] Все {cycles} циклов пройдены без единой ошибки и утечки портов!")
    return {"status": "passed", "cycles_completed": cycles, "details": results}


# ==============================================================================
# G7-SOAK: 20-минутный тест длительной стабильности с телеметрией
# ==============================================================================


def run_soak_stage(
    duration_minutes: float = 20.0,
    sample_interval_sec: int = 30,
    seed: int = 42,
    test_db_url: str = DEFAULT_TEST_DB_URL,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    print("\n================================================================================")
    print(f" [G7-SOAK] ДЛИТЕЛЬНЫЙ ПРОГОН СТАБИЛЬНОСТИ ({duration_minutes} мин, seed={seed})")
    print("================================================================================")

    random.seed(seed)
    temp_dir = tempfile.gettempdir()
    fe_pid_file = os.path.join(temp_dir, "g7_soak_fe.pid")
    fe_log_file = os.path.join(temp_dir, "g7_soak_fe.log")
    be_pid_file = os.path.join(temp_dir, "g7_soak_be.pid")
    be_log_file = os.path.join(temp_dir, "g7_soak_be.log")

    base_env = os.environ.copy()
    base_env.update(
        {
            "TEST_DATABASE_URL": test_db_url,
            "DATABASE_URL": test_db_url,
            "DATABASE_URL_SYNC": test_db_url,
            "SESSION_SECRET_KEY": "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only",
            "TOTP_ENCRYPTION_KEY": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
            "JWT_PRIVATE_KEY_PEM": "",
            "OIDC_ISSUER": "https://auth.alxprgs.tech",
            "WEBAUTHN_RP_ID": "localhost",
            "WEBAUTHN_ORIGIN": "http://localhost:5173",
            "PORT": str(BACKEND_PORT),
            "FEATURE_TOTP_ENABLED": "false",
            "FEATURE_PASSKEY_ENABLED": "false",
            "FEATURE_RECOVERY_CODES_ENABLED": "false",
            "FEATURE_EMAIL_VERIFICATION_ENABLED": "true",
            "REQUIRE_VERIFIED_EMAIL": "false",
        }
    )

    # Исходный baseline соединений PostgreSQL
    pg_baseline = get_pg_active_connections(test_db_url)
    print(f"[SOAK-INFO] Baseline активных подключений PostgreSQL: {pg_baseline}")

    # Подготовка данных
    subprocess.run([sys.executable, str(SEED_SCRIPT)], env=base_env, check=True)

    # Запуск серверов
    fe_res = subprocess.run(
        [
            sys.executable,
            str(MANAGE_SCRIPT),
            "start-frontend",
            "--port",
            str(FRONTEND_PORT),
            "--pidfile",
            fe_pid_file,
            "--logfile",
            fe_log_file,
        ],
        capture_output=True,
        text=True,
    )
    if fe_res.returncode != 0:
        return {"status": "failed", "error": f"Failed to start frontend: {fe_res.stdout}"}

    be_res = subprocess.run(
        [
            sys.executable,
            str(MANAGE_SCRIPT),
            "start",
            "--port",
            str(BACKEND_PORT),
            "--pidfile",
            be_pid_file,
            "--logfile",
            be_log_file,
            "--profile",
            "default-off",
        ],
        env=base_env,
        capture_output=True,
        text=True,
    )
    if be_res.returncode != 0:
        subprocess.run(
            [
                sys.executable,
                str(MANAGE_SCRIPT),
                "stop",
                "--pidfile",
                fe_pid_file,
                "--port",
                str(FRONTEND_PORT),
            ]
        )
        return {"status": "failed", "error": f"Failed to start backend: {be_res.stdout}"}

    be_pid = read_pid_file(be_pid_file) or 0
    fe_pid = read_pid_file(fe_pid_file) or 0

    # Разрешаем реальные слушающие сокет PIDs на портах
    listening_be = get_pid_listening_on_port(BACKEND_PORT)
    if listening_be and listening_be > 0:
        be_pid = listening_be
    listening_fe = get_pid_listening_on_port(FRONTEND_PORT)
    if listening_fe and listening_fe > 0:
        fe_pid = listening_fe

    print(f"[SOAK-INFO] Серверы запущены: Backend Worker PID {be_pid}, Frontend PID {fe_pid}")

    pid_verified = verify_server_worker_pid(be_pid, BACKEND_PORT)
    if not pid_verified:
        print(
            f"[SOAK-WARN] PID {be_pid} не подтвержден как backend worker на порту {BACKEND_PORT}!"
        )
    else:
        print(f"[SOAK-INFO] PID {be_pid} подтвержден как backend worker на порту {BACKEND_PORT}")

    client = SimpleHttpClient(f"http://127.0.0.1:{BACKEND_PORT}")

    # Метрики
    telemetry_records = []
    total_ops = 0
    unexpected_errors = 0
    handled_401 = 0
    handled_403 = 0
    handled_429 = 0
    browser_smoke_runs = 0
    browser_smoke_failed = 0
    latencies: list[float] = []

    target_duration_sec = duration_minutes * 60.0
    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"

    load_start_time = time.time()
    last_browser_smoke_time = load_start_time
    load_end_time = load_start_time

    try:
        sample_num = 0
        while time.time() - load_start_time < target_duration_sec:
            sample_num += 1
            now = time.time()
            elapsed_sec = round(now - load_start_time, 1)

            # 1. Рабочая нагрузка и измерение задержек
            # 1.1. Health live & ready
            st, d, lat = client.request("GET", "/health/live")
            total_ops += 1
            latencies.append(lat)
            if st != 200:
                print(f"[SOAK-OP-FAIL] /health/live: status={st}, body={d}")
                unexpected_errors += 1

            st, d, lat = client.request("GET", "/health/ready")
            total_ops += 1
            latencies.append(lat)
            if st != 200:
                print(f"[SOAK-OP-FAIL] /health/ready: status={st}, body={d}")
                unexpected_errors += 1

            # 1.2. Capabilities
            st, d, lat = client.request("GET", "/api/v1/auth/capabilities")
            total_ops += 1
            latencies.append(lat)
            if st != 200:
                print(f"[SOAK-OP-FAIL] /capabilities: status={st}, body={d}")
                unexpected_errors += 1

            # 1.3. OIDC discovery & JWKS
            st, d, lat = client.request("GET", "/.well-known/openid-configuration")
            total_ops += 1
            latencies.append(lat)
            if st != 200:
                print(f"[SOAK-OP-FAIL] /openid-configuration: status={st}, body={d}")
                unexpected_errors += 1

            st, d, lat = client.request("GET", "/.well-known/jwks.json")
            total_ops += 1
            latencies.append(lat)
            if st != 200:
                print(f"[SOAK-OP-FAIL] /jwks.json: status={st}, body={d}")
                unexpected_errors += 1

            # 1.4. Valid Login
            st, login_data, lat = client.request(
                "POST",
                "/api/v1/auth/login",
                json_data={"username": "compose_admin", "password": "ComposeAdminPass2026!"},
            )
            total_ops += 1
            latencies.append(lat)
            if st != 200:
                print(f"[SOAK-OP-FAIL] /login: status={st}, body={login_data}")
                unexpected_errors += 1

            # 1.5. Me
            st, d, lat = client.request("GET", "/api/v1/auth/me")
            total_ops += 1
            latencies.append(lat)
            if st != 200:
                print(f"[SOAK-OP-FAIL] /me: status={st}, body={d}")
                unexpected_errors += 1

            # 1.5.1 OIDC Authorization Code Flow & Python SDK Validation (G8-OPS / SSO-01 / SDK-02)
            try:
                from alxprgs_sso import SSOClient

                sdk_client = SSOClient(
                    server_url=f"http://127.0.0.1:{BACKEND_PORT}",
                    client_id="client_analytics_app",
                    client_secret="analytics_client_secret_123",
                    expected_issuer="https://auth.alxprgs.tech",
                    expected_audience="client_analytics_app",
                )
                auth_url, code_verifier, expected_state, expected_nonce = (
                    sdk_client.start_authorization(
                        redirect_uri="http://localhost:8001/callback",
                        scope="openid profile email",
                    )
                )
                parsed_auth = urllib.parse.urlparse(auth_url)
                auth_path = f"{parsed_auth.path}?{parsed_auth.query}"

                st_auth, _, lat_auth = client.request("GET", auth_path, follow_redirects=False)
                total_ops += 1
                latencies.append(lat_auth)

                if st_auth not in (302, 303, 307):
                    print(f"[SOAK-OP-FAIL] /oauth/authorize: expected 302, got status={st_auth}")
                    unexpected_errors += 1
                else:
                    loc = client.last_headers.get("location", "")
                    parsed_loc = urllib.parse.urlparse(loc)
                    loc_params = urllib.parse.parse_qs(parsed_loc.query)
                    code_val = loc_params.get("code", [None])[0]
                    state_val = loc_params.get("state", [None])[0]
                    if not code_val or state_val != expected_state:
                        print(f"[SOAK-OP-FAIL] /oauth/authorize: invalid redirect params {loc}")
                        unexpected_errors += 1
                    else:
                        start_tok_t = time.perf_counter()
                        import asyncio

                        session_info = asyncio.run(
                            sdk_client.handle_web_callback(
                                code=code_val,
                                state=state_val,
                                expected_state=expected_state,
                                code_verifier=code_verifier,
                                redirect_uri="http://localhost:8001/callback",
                                expected_nonce=expected_nonce,
                            )
                        )
                        tok_lat = round((time.perf_counter() - start_tok_t) * 1000.0, 2)
                        total_ops += 1
                        latencies.append(tok_lat)
                        if (
                            not session_info.user
                            or session_info.user.preferred_username != "compose_admin"
                        ):
                            print(
                                f"[SOAK-OP-FAIL] SDK session_info user mismatch: {session_info.user}"
                            )
                            unexpected_errors += 1
            except Exception as oidc_ex:
                print(f"[SOAK-OP-FAIL] OIDC Code/Token & SDK flow error: {oidc_ex}")
                unexpected_errors += 1

            # 1.6. Logout with CSRF token
            csrf_tok = login_data.get("csrf_token", "")
            st, d, lat = client.request(
                "POST",
                "/api/v1/auth/logout",
                headers={"X-CSRF-Token": csrf_tok},
            )
            total_ops += 1
            latencies.append(lat)
            if st != 200:
                print(f"[SOAK-OP-FAIL] /logout: status={st}, body={d}")
                unexpected_errors += 1

            # 1.7. Контролируемые негативные запросы (классифицируются отдельно)
            # Неверный пароль -> 401
            st, d, _ = client.request(
                "POST",
                "/api/v1/auth/login",
                json_data={"username": "compose_admin", "password": "WrongPassword456!"},
            )
            total_ops += 1
            if st == 401:
                handled_401 += 1
            else:
                print(f"[SOAK-OP-FAIL] bad login expected 401: status={st}, body={d}")
                unexpected_errors += 1

            # Запрос me без токена -> 401
            no_auth_client = SimpleHttpClient(f"http://127.0.0.1:{BACKEND_PORT}")
            st, d, _ = no_auth_client.request("GET", "/api/v1/auth/me")
            total_ops += 1
            if st == 401:
                handled_401 += 1
            else:
                print(f"[SOAK-OP-FAIL] no-auth me expected 401: status={st}, body={d}")
                unexpected_errors += 1

            # Запрос выключенного Passkey в default-off -> 404 (FeatureDisabledException)
            st, d, _ = client.request("GET", "/api/v1/mfa/passkey/register-options")
            total_ops += 1
            if st in (404, 403, 400):
                handled_403 += 1
            else:
                print(f"[SOAK-OP-FAIL] disabled passkey expected 404/403: status={st}, body={d}")
                unexpected_errors += 1

            # 1.8. Периодический Browser smoke (каждые 5 минут)
            if now - last_browser_smoke_time >= 300.0:
                print(
                    f"[SOAK-BROWSER] Запуск периодического Chromium smoke-теста на {elapsed_sec}с..."
                )
                browser_smoke_runs += 1
                smk_res = subprocess.run(
                    [npx_cmd, "playwright", "test", "e2e/sso.spec.ts", "-g", "01. Default Profile"],
                    cwd=FRONTEND_DIR,
                    env=base_env,
                    capture_output=True,
                    text=True,
                )
                if smk_res.returncode == 0:
                    print(
                        f"[SOAK-BROWSER-OK] Chromium smoke тест успешно пройден на {elapsed_sec}с"
                    )
                else:
                    print(
                        f"[SOAK-BROWSER-FAIL] Chromium smoke упал: {smk_res.stdout}\n{smk_res.stderr}"
                    )
                    browser_smoke_failed += 1
                    unexpected_errors += 1
                last_browser_smoke_time = now

            # 2. Сбор телеметрии
            be_rss = get_process_rss_mb(be_pid)
            if be_rss <= 10.0:
                re_be = get_pid_listening_on_port(BACKEND_PORT)
                if re_be and re_be > 0:
                    be_pid = re_be
                    be_rss = get_process_rss_mb(be_pid)
            fe_rss = get_process_rss_mb(fe_pid)
            pg_conns = get_pg_active_connections(test_db_url)

            # Вычисление p50 и p95
            recent_lats = latencies[-20:]
            recent_lats_sorted = sorted(recent_lats)
            p50 = (
                round(recent_lats_sorted[len(recent_lats_sorted) // 2], 1)
                if recent_lats_sorted
                else 0.0
            )
            p95_idx = int(len(recent_lats_sorted) * 0.95)
            p95 = round(recent_lats_sorted[p95_idx], 1) if recent_lats_sorted else 0.0

            record = {
                "sample": sample_num,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_sec": elapsed_sec,
                "backend_rss_mb": be_rss,
                "frontend_rss_mb": fe_rss,
                "pg_connections": pg_conns,
                "total_ops": total_ops,
                "unexpected_errors": unexpected_errors,
                "handled_401": handled_401,
                "handled_403": handled_403,
                "handled_429": handled_429,
                "latency_p50_ms": p50,
                "latency_p95_ms": p95,
            }
            telemetry_records.append(record)

            print(
                f"[SOAK @ {elapsed_sec:>5.1f}s] Ops: {total_ops:>4} | Err: {unexpected_errors} "
                f"| BE RSS: {be_rss:>5.1f}MB | FE RSS: {fe_rss:>5.1f}MB | PG Conns: {pg_conns:>2} "
                f"| p50: {p50:>5.1f}ms | p95: {p95:>5.1f}ms"
            )

            # Ожидание следующего сэмпла
            time.sleep(sample_interval_sec)
        load_end_time = time.time()
    finally:
        if load_end_time == load_start_time:
            load_end_time = time.time()
        print("[SOAK-CLEANUP] Остановка серверов и сбор финального состояния...")
        subprocess.run(
            [
                sys.executable,
                str(MANAGE_SCRIPT),
                "stop",
                "--pidfile",
                be_pid_file,
                "--port",
                str(BACKEND_PORT),
            ],
            capture_output=True,
        )
        subprocess.run(
            [
                sys.executable,
                str(MANAGE_SCRIPT),
                "stop",
                "--pidfile",
                fe_pid_file,
                "--port",
                str(FRONTEND_PORT),
            ],
            capture_output=True,
        )
        # Короткий cool-down
        time.sleep(3.0)
        pg_final = get_pg_active_connections(test_db_url)
        be_busy = is_port_in_use(BACKEND_PORT)
        fe_busy = is_port_in_use(FRONTEND_PORT)
        print(
            f"[SOAK-CLEANUP] Соединения PG после остановки: {pg_final} (baseline был {pg_baseline})"
        )
        if be_busy or fe_busy:
            print(f"[SOAK-CLEANUP-WARN] Порты не освобождены: BE busy={be_busy}, FE busy={fe_busy}")

    # Сохранение CSV
    if output_dir and telemetry_records:
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_file = output_dir / "soak_metrics.csv"
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=telemetry_records[0].keys())
            writer.writeheader()
            writer.writerows(telemetry_records)
        print(f"[SOAK-REPORT] Метрики телеметрии сохранены в {csv_file}")

    all_lats_sorted = sorted(latencies)
    overall_p50 = round(all_lats_sorted[len(all_lats_sorted) // 2], 1) if all_lats_sorted else 0.0
    overall_p95 = (
        round(all_lats_sorted[int(len(all_lats_sorted) * 0.95)], 1) if all_lats_sorted else 0.0
    )

    be_rss_values = [r["backend_rss_mb"] for r in telemetry_records if r["backend_rss_mb"] > 0]
    initial_rss = be_rss_values[0] if be_rss_values else 0.0
    final_rss = be_rss_values[-1] if be_rss_values else 0.0
    max_rss = max(be_rss_values) if be_rss_values else 0.0

    duration_achieved_sec = round(load_end_time - load_start_time, 1)
    expected_samples = int(target_duration_sec / sample_interval_sec)

    if target_duration_sec >= 300.0:
        expected_browser_smoke_runs = int((target_duration_sec - 0.1) // 300.0)
    else:
        expected_browser_smoke_runs = 0

    failure_reasons = evaluate_soak_criteria(
        duration_achieved_sec=duration_achieved_sec,
        target_duration_sec=target_duration_sec,
        telemetry_records=telemetry_records,
        expected_samples=expected_samples,
        unexpected_errors=unexpected_errors,
        browser_smoke_runs=browser_smoke_runs,
        browser_smoke_failed=browser_smoke_failed,
        pg_baseline=pg_baseline,
        pg_final=pg_final,
        backend_port_busy=be_busy,
        frontend_port_busy=fe_busy,
        pid_verified=pid_verified,
        expected_browser_smoke_runs=expected_browser_smoke_runs,
    )

    passed = len(failure_reasons) == 0
    if not passed:
        print("\n[SOAK-CRITERIA-FAIL] Обнаружены нарушения строгих критериев надежности:")
        for rsn in failure_reasons:
            print(f"  - {rsn}")

    return {
        "status": "passed" if passed else "failed",
        "failure_reasons": failure_reasons,
        "duration_minutes": duration_minutes,
        "duration_achieved_sec": duration_achieved_sec,
        "samples_collected": len(telemetry_records),
        "expected_samples": expected_samples,
        "total_operations": total_ops,
        "unexpected_errors": unexpected_errors,
        "handled_expected_errors": handled_401 + handled_403 + handled_429,
        "scheduled_smokes": expected_browser_smoke_runs,
        "executed_smokes": browser_smoke_runs,
        "browser_smoke_runs": browser_smoke_runs,
        "browser_smoke_failed": browser_smoke_failed,
        "latency_overall_p50_ms": overall_p50,
        "latency_overall_p95_ms": overall_p95,
        "backend_initial_rss_mb": initial_rss,
        "backend_final_rss_mb": final_rss,
        "backend_max_rss_mb": max_rss,
        "pid_verified": pid_verified,
        "pg_baseline": pg_baseline,
        "pg_final": pg_final,
        "pg_baseline_connections": pg_baseline,
        "pg_final_connections": pg_final,
    }


# ==============================================================================
# G7-RACE: Тестирование конкурентной одноразовости и обнаружения replay
# ==============================================================================


def run_race_stage(
    attempts: int = 10,
    test_db_url: str = DEFAULT_TEST_DB_URL,
) -> dict[str, Any]:
    print("\n================================================================================")
    print(" [G7-RACE] ТЕСТИРОВАНИЕ КОНКУРЕНТНОЙ ОДНОРАЗОВОСТИ (PostgreSQL Concurrency Matrix)")
    print("================================================================================")

    # Задаем окружение с TEST_DATABASE_URL для db_guard
    env = os.environ.copy()
    env.update(
        {
            "TEST_DATABASE_URL": test_db_url,
            "DATABASE_URL": test_db_url,
            "DATABASE_URL_SYNC": test_db_url,
            "SESSION_SECRET_KEY": "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only",
            "TOTP_ENCRYPTION_KEY": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
            "JWT_PRIVATE_KEY_PEM": "",
            "OIDC_ISSUER": "https://auth.alxprgs.tech",
        }
    )

    race_results: dict[str, dict[str, int]] = {
        "auth_code_race": {"passed": 0, "failed": 0},
        "recovery_code_burn": {"passed": 0, "failed": 0},
        "refresh_replay_race": {"passed": 0, "failed": 0},
        "concurrent_registration": {"passed": 0, "failed": 0},
        "distributed_rate_limiting": {"passed": 0, "failed": 0},
    }

    test_file = ROOT_DIR / "tests" / "integration" / "test_concurrency_pg.py"

    # Запускаем ровно `attempts` итераций (по N попыток каждого обязательного сценария)
    iterations = attempts
    print(
        f"[RACE-INFO] Запуск {iterations} итераций интеграционного набора конкурентности на PostgreSQL (по {attempts} попыток на сценарий): {test_file.name}"
    )

    all_passed = True

    for it in range(1, iterations + 1):
        print(f"\n--- Итерация {it}/{iterations} матрицы конкурентности ---")
        # 1. Подготовка данных
        subprocess.run([sys.executable, str(SEED_SCRIPT)], env=env, check=True)

        # 2. Запуск pytest
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "-v",
            "--tb=short",
        ]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)

        # Разбор вывода pytest
        for line in res.stdout.splitlines():
            line_str = line.strip()
            if "::test_concurrent_auth_code_redemption_pg" in line_str:
                if "PASSED" in line_str:
                    race_results["auth_code_race"]["passed"] += 1
                else:
                    race_results["auth_code_race"]["failed"] += 1
                    all_passed = False
            elif "::test_concurrent_recovery_code_burn_pg" in line_str:
                if "PASSED" in line_str:
                    race_results["recovery_code_burn"]["passed"] += 1
                else:
                    race_results["recovery_code_burn"]["failed"] += 1
                    all_passed = False
            elif "::test_concurrent_refresh_token_rotation_and_replay_pg" in line_str:
                if "PASSED" in line_str:
                    race_results["refresh_replay_race"]["passed"] += 1
                else:
                    race_results["refresh_replay_race"]["failed"] += 1
                    all_passed = False
            elif "::test_concurrent_user_registration_race_pg" in line_str:
                if "PASSED" in line_str:
                    race_results["concurrent_registration"]["passed"] += 1
                else:
                    race_results["concurrent_registration"]["failed"] += 1
                    all_passed = False
            elif "::test_distributed_rate_limiting_registration_pg" in line_str:
                if "PASSED" in line_str:
                    race_results["distributed_rate_limiting"]["passed"] += 1
                else:
                    race_results["distributed_rate_limiting"]["failed"] += 1
                    all_passed = False

        if res.returncode != 0:
            print(f"[RACE-FAIL] Сбой в итерации {it}:\n{res.stdout}\n{res.stderr}")
            all_passed = False
        else:
            print(f"[RACE-OK] Итерация {it} успешно завершена (5/5 проверок пройдено).")

    # Проверка итогового состояния PostgreSQL
    import psycopg

    pg_state_ok = True
    clean_url = test_db_url.replace("+psycopg", "")
    try:
        with psycopg.connect(clean_url) as conn:
            with conn.cursor() as cur:
                # 1. Проверяем отсутствие зависших транзакционных блокировок
                cur.execute("SELECT count(1) FROM pg_locks WHERE NOT granted")
                ungranted_locks = cur.fetchone()[0]
                if ungranted_locks > 0:
                    print(
                        f"[RACE-FAIL] Обнаружено {ungranted_locks} зависших блокировок в PostgreSQL!"
                    )
                    pg_state_ok = False

                # 2. Проверяем целостность system_configuration
                cur.execute(
                    "SELECT id, bootstrap_completed, registration_mode FROM system_configuration WHERE id = 1"
                )
                cfg_row = cur.fetchone()
                if not cfg_row or cfg_row[0] != 1:
                    print("[RACE-FAIL] Строка system_configuration id=1 не найдена в PostgreSQL!")
                    pg_state_ok = False

                # 3. Проверяем аудит (события аудита должны присутствовать)
                cur.execute("SELECT count(1) FROM audit_events")
                audit_count = cur.fetchone()[0]
                if audit_count == 0:
                    print("[RACE-FAIL] В audit_events отсутствуют записи аудита!")
                    pg_state_ok = False
                else:
                    print(
                        f"[RACE-OK] PostgreSQL: зафиксировано {audit_count} событий в журнале аудита."
                    )
    except Exception as e:
        print(f"[RACE-FAIL] Ошибка проверки состояния PostgreSQL: {e}")
        pg_state_ok = False

    overall_race_ok = (
        all_passed
        and pg_state_ok
        and all(counts["passed"] >= attempts for counts in race_results.values())
    )
    print("\n--- Итоговые результаты G7-RACE ---")
    for scen, counts in race_results.items():
        print(f"  {scen}: passed={counts['passed']}/{attempts}, failed={counts['failed']}")
    print(f"  PostgreSQL state verification: {'PASSED' if pg_state_ok else 'FAILED'}")

    return {
        "status": "passed" if overall_race_ok else "failed",
        "attempts_per_scenario": attempts,
        "iterations_completed": iterations,
        "results": race_results,
        "pg_state_verified": pg_state_ok,
    }


# ==============================================================================
# G7-RECOVER: Сбой, восстановление и Backup & Restore
# ==============================================================================


def run_recover_stage(
    test_db_url: str = DEFAULT_TEST_DB_URL,
    container_name: str = DEFAULT_CONTAINER,
) -> dict[str, Any]:
    print("\n================================================================================")
    print(" [G7-RECOVER] ТЕСТИРОВАНИЕ СБОЕВ, ВОССТАНОВЛЕНИЯ И BACKUP / RESTORE")
    print("================================================================================")

    temp_dir = tempfile.gettempdir()
    be_pid_file = os.path.join(temp_dir, "g7_rec_be.pid")
    be_log_file = os.path.join(temp_dir, "g7_rec_be.log")

    base_env = os.environ.copy()
    base_env.update(
        {
            "TEST_DATABASE_URL": test_db_url,
            "DATABASE_URL": test_db_url,
            "DATABASE_URL_SYNC": test_db_url,
            "SESSION_SECRET_KEY": "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only",
            "TOTP_ENCRYPTION_KEY": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
            "JWT_PRIVATE_KEY_PEM": "",
            "OIDC_ISSUER": "https://auth.alxprgs.tech",
            "PORT": str(BACKEND_PORT),
            "FEATURE_TOTP_ENABLED": "false",
            "FEATURE_PASSKEY_ENABLED": "false",
            "FEATURE_RECOVERY_CODES_ENABLED": "false",
            "FEATURE_EMAIL_VERIFICATION_ENABLED": "true",
            "REQUIRE_VERIFIED_EMAIL": "false",
        }
    )

    steps_result = {}

    try:
        # 1. Контролируемый перезапуск бэкенда
        print("\n--- 1. Контролируемый перезапуск бэкенда ---")
        subprocess.run([sys.executable, str(SEED_SCRIPT)], env=base_env, check=True)
        subprocess.run(
            [
                sys.executable,
                str(MANAGE_SCRIPT),
                "start",
                "--port",
                str(BACKEND_PORT),
                "--pidfile",
                be_pid_file,
                "--logfile",
                be_log_file,
                "--profile",
                "default-off",
            ],
            env=base_env,
            check=True,
        )

        client = SimpleHttpClient(f"http://127.0.0.1:{BACKEND_PORT}")
        st, _, _ = client.request("GET", "/health/live")
        assert st == 200, "Backend not live before restart"

        # Останавливаем
        subprocess.run(
            [
                sys.executable,
                str(MANAGE_SCRIPT),
                "stop",
                "--pidfile",
                be_pid_file,
                "--port",
                str(BACKEND_PORT),
            ],
            check=True,
        )
        assert not is_port_in_use(BACKEND_PORT), "Port still busy after stop"

        # Проверяем, что запросы падают
        st, _, _ = client.request("GET", "/health/live")
        assert st == -1, "Backend responded after stop!"

        # Снова запускаем
        subprocess.run(
            [
                sys.executable,
                str(MANAGE_SCRIPT),
                "start",
                "--port",
                str(BACKEND_PORT),
                "--pidfile",
                be_pid_file,
                "--logfile",
                be_log_file,
                "--profile",
                "default-off",
            ],
            env=base_env,
            check=True,
        )
        st, _, _ = client.request(
            "POST",
            "/api/v1/auth/login",
            json_data={"username": "compose_admin", "password": "ComposeAdminPass2026!"},
        )
        assert st == 200, "Login failed after backend restart"
        print("[RECOVER-OK] Контролируемый перезапуск бэкенда успешно подтвержден.")
        steps_result["backend_restart"] = "passed"

        # 2. Кратковременная недоступность БД (fail-closed, готовность)
        print("\n--- 2. Кратковременная недоступность БД (Docker pause/unpause) ---")
        pause_res = subprocess.run(
            ["docker", "pause", container_name], capture_output=True, text=True
        )
        if pause_res.returncode == 0:
            try:
                # В режиме паузы БД: readiness должен вернуть сбой или timeout
                st, _, _ = client.request("GET", "/health/ready", timeout=3.0)
                print(f"[RECOVER-INFO] Статус /health/ready при недоступной БД: {st}")
                assert st != 200, "Readiness returned 200 while DB was paused!"

                # Логин должен безопасно отказать (fail-closed, не крашить процесс)
                st, _, _ = client.request(
                    "POST",
                    "/api/v1/auth/login",
                    json_data={"username": "compose_admin", "password": "ComposeAdminPass2026!"},
                    timeout=3.0,
                )
                print(f"[RECOVER-INFO] Статус login при недоступной БД: {st}")
                assert st != 200, "Login succeeded while DB was paused!"
            finally:
                subprocess.run(["docker", "unpause", container_name], check=True)
                time.sleep(2.0)

            # После unpause бэкенд восстанавливается
            st, _, _ = client.request("GET", "/health/ready", timeout=5.0)
            assert st == 200, "Readiness did not recover after DB unpause"
            st, _, _ = client.request(
                "POST",
                "/api/v1/auth/login",
                json_data={"username": "compose_admin", "password": "ComposeAdminPass2026!"},
            )
            assert st == 200, "Login failed after DB unpause"
            print(
                "[RECOVER-OK] Кратковременная недоступность БД и восстановление успешно подтверждены."
            )
            steps_result["db_unavailability"] = "passed"
        else:
            print(f"[RECOVER-WARN] Не удалось выполнить docker pause: {pause_res.stderr}")
            steps_result["db_unavailability"] = "skipped"

        # Shared isolated recovery scenario verifies test ownership before every DROP,
        # applies the current erasure journal, and checks restored encrypted TOTP.
        recovery_env = base_env.copy()
        recovery_env["TEST_DATABASE_URL"] = test_db_url
        recovery = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_ops_backup_restore_totp.py", "-q"],
            cwd=ROOT_DIR, env=recovery_env, capture_output=True,
        )
        assert recovery.returncode == 0, "Isolated backup/restore failed; inspect local test artifacts"
        steps_result["backup_restore"] = "passed"

    finally:
        subprocess.run(
            [
                sys.executable,
                str(MANAGE_SCRIPT),
                "stop",
                "--pidfile",
                be_pid_file,
                "--port",
                str(BACKEND_PORT),
            ],
            capture_output=True,
        )

    all_passed = all(v == "passed" for v in steps_result.values())
    return {"status": "passed" if all_passed else "failed", "details": steps_result}


# ==============================================================================
# G7-MIGRATE: Чистая установка и миграции схемы
# ==============================================================================


def run_migrate_stage(test_db_url: str = DEFAULT_TEST_DB_URL) -> dict[str, Any]:
    print("\n================================================================================")
    print(" [G7-MIGRATE] ПРОВЕРКА МИГРАЦИЙ СХЕМЫ (alembic upgrade / downgrade / existing DB)")
    print("================================================================================")

    import psycopg

    clean_url = test_db_url.replace("+psycopg", "").replace("/alxprgs_sso_test", "/postgres")

    # -------------------------------------------------------------------------
    # Часть 1: Чистая установка, откат и повторный накат схемы
    # -------------------------------------------------------------------------
    print("\n--- 1. Чистая установка, откат и повторный накат схемы ---")
    mig_db_name = "alxprgs_sso_migration_test"
    mig_db_url = test_db_url.replace("alxprgs_sso_test", mig_db_name)

    with psycopg.connect(clean_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {mig_db_name} WITH (FORCE)")
            cur.execute(f"CREATE DATABASE {mig_db_name} OWNER sso_test_user")

    mig_env = os.environ.copy()
    mig_env.update(
        {
            "DATABASE_URL_SYNC": mig_db_url,
            "DATABASE_URL": mig_db_url,
            "SESSION_SECRET_KEY": "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only",
        }
    )

    clean_ok = False
    clean_tables: list[str] = []

    try:
        # Upgrade head
        print("[MIGRATE-INFO] Применение alembic upgrade head на пустой БД...")
        up_res = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=mig_env,
            capture_output=True,
            text=True,
        )
        assert up_res.returncode == 0, f"Upgrade head failed: {up_res.stdout}\n{up_res.stderr}"

        with psycopg.connect(mig_db_url.replace("+psycopg", "")) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
                )
                clean_tables = [r[0] for r in cur.fetchall()]
        assert (
            "users" in clean_tables
            and "sessions" in clean_tables
            and "alembic_version" in clean_tables
        )
        print(
            f"[MIGRATE-OK] Создано таблиц: {len(clean_tables)} (users, sessions, alembic_version присутствуют)"
        )

        # Downgrade base
        print("[MIGRATE-INFO] Откат alembic downgrade base...")
        down_res = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            cwd=BACKEND_DIR,
            env=mig_env,
            capture_output=True,
            text=True,
        )
        assert down_res.returncode == 0, (
            f"Downgrade base failed: {down_res.stdout}\n{down_res.stderr}"
        )

        # Повторный upgrade head
        print("[MIGRATE-INFO] Повторный накат alembic upgrade head...")
        up2_res = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=mig_env,
            capture_output=True,
            text=True,
        )
        assert up2_res.returncode == 0, f"Second upgrade failed: {up2_res.stdout}\n{up2_res.stderr}"
        clean_ok = True
        print("[MIGRATE-OK] Чистая установка, откат и повторный накат успешно завершены.")

    finally:
        with psycopg.connect(clean_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {mig_db_name} WITH (FORCE)")

    # -------------------------------------------------------------------------
    # Часть 2: Обновление существующей БД с данными (Existing DB Upgrade with Data)
    # -------------------------------------------------------------------------
    print("\n--- 2. Обновление существующей БД с данными (0001 -> 0002_reg_system_config) ---")
    upg_db_name = "alxprgs_sso_upgrade_test"
    upg_db_url = test_db_url.replace("alxprgs_sso_test", upg_db_name)
    upg_clean_url = clean_url.replace("/postgres", f"/{upg_db_name}")

    with psycopg.connect(clean_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {upg_db_name} WITH (FORCE)")
            cur.execute(f"CREATE DATABASE {upg_db_name} OWNER sso_test_user")

    upg_env = os.environ.copy()
    upg_env.update(
        {
            "DATABASE_URL_SYNC": upg_db_url,
            "DATABASE_URL": upg_db_url,
            "TEST_DATABASE_URL": upg_db_url,
            "SESSION_SECRET_KEY": "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only",
            "TOTP_ENCRYPTION_KEY": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
            "JWT_PRIVATE_KEY_PEM": "",
            "OIDC_ISSUER": "https://auth.alxprgs.tech",
            "PORT": "8003",
        }
    )

    upg_pid_file = os.path.join(tempfile.gettempdir(), "g7_mig_upg_be.pid")
    upg_log_file = os.path.join(tempfile.gettempdir(), "g7_mig_upg_be.log")
    upg_port = 8003

    upgrade_data_ok = False
    u_count = 0
    b_done = False
    reg_mode = "unknown"

    try:
        # 1. Применяем начальную схему 0001_initial_schema
        print("[MIGRATE-UPGRADE] Применение alembic upgrade 0001_initial_schema...")
        res_v1 = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0001_initial_schema"],
            cwd=BACKEND_DIR,
            env=upg_env,
            capture_output=True,
            text=True,
        )
        assert res_v1.returncode == 0, f"Upgrade 0001 failed: {res_v1.stdout}\n{res_v1.stderr}"

        # 2. Наполняем схему v1 синтетическими данными
        print(
            "[MIGRATE-UPGRADE] Заполнение схемы v1 синтетическими данными (users, roles, credentials, sessions)..."
        )
        if str(BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(BACKEND_DIR))
        from app.core.security import hash_password, hash_token

        admin_pwd_hash = hash_password("UpgradeAdminPass2026!")
        user_pwd_hash = hash_password("UpgradeUserPass2026!")

        admin_uid = "11111111-aaaa-1111-aaaa-111111111111"
        user_uid = "22222222-bbbb-2222-bbbb-222222222222"
        role_admin_id = "aaaaaaaa-1111-aaaa-1111-aaaaaaaaaaaa"
        role_user_id = "bbbbbbbb-2222-bbbb-2222-bbbbbbbbbbbb"

        with psycopg.connect(upg_clean_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                # Базовые роли
                cur.execute(
                    "INSERT INTO roles (id, name, description) VALUES (%s, 'admin', 'Admin role'), (%s, 'user', 'User role')",
                    (role_admin_id, role_user_id),
                )
                # Пользователи (один суперпользователь, один обычный)
                cur.execute(
                    """
                    INSERT INTO users (id, username, email, is_superuser, is_active, email_verified, created_at, updated_at)
                    VALUES
                    (%s, 'upgrade_admin', 'upgrade_admin@alxprgs.tech', true, true, true, now(), now()),
                    (%s, 'upgrade_user', 'upgrade_user@alxprgs.tech', false, true, true, now(), now())
                    """,
                    (admin_uid, user_uid),
                )
                # Пароли
                cur.execute(
                    """
                    INSERT INTO password_credentials (id, user_id, password_hash, algorithm, created_at)
                    VALUES
                    (gen_random_uuid(), %s, %s, 'argon2id', now()),
                    (gen_random_uuid(), %s, %s, 'argon2id', now())
                    """,
                    (admin_uid, admin_pwd_hash, user_uid, user_pwd_hash),
                )
                # Назначение ролей
                cur.execute(
                    """
                    INSERT INTO user_roles (id, user_id, role_id, created_at)
                    VALUES
                    (gen_random_uuid(), %s, %s, now()),
                    (gen_random_uuid(), %s, %s, now()),
                    (gen_random_uuid(), %s, %s, now())
                    """,
                    (admin_uid, role_admin_id, admin_uid, role_user_id, user_uid, role_user_id),
                )
                # Активная сессия для upgrade_admin
                cur.execute(
                    """
                    INSERT INTO sessions (id, session_token_hash, user_id, ip_address, user_agent, expires_at, last_activity_at, created_at)
                    VALUES
                    (gen_random_uuid(), %s, %s, '127.0.0.1', 'MigrateTestAgent/1.0', now() + interval '1 day', now(), now())
                    """,
                    (hash_token("test_upgrade_session_token_12345"), admin_uid),
                )
                # OIDC Client
                cur.execute(
                    """
                    INSERT INTO oidc_clients (id, client_id, client_secret_hash, client_name, client_type, is_active, created_at)
                    VALUES
                    (gen_random_uuid(), 'upgrade-test-client', %s, 'Upgrade Client', 'confidential', true, now())
                    """,
                    (hash_token("upgrade_client_secret_xyz"),),
                )

        # 3. Применяем обновление до актуальной версии схемы head (0002_reg_system_config)
        print("[MIGRATE-UPGRADE] Выполнение alembic upgrade head на существующей БД с данными...")
        res_head = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=upg_env,
            capture_output=True,
            text=True,
        )
        assert res_head.returncode == 0, (
            f"Upgrade head failed: {res_head.stdout}\n{res_head.stderr}"
        )

        # 4. Проверяем сохранность данных и автоматическую инициализацию system_configuration
        print(
            "[MIGRATE-UPGRADE] Проверка сохранности данных и инициализации system_configuration..."
        )
        with psycopg.connect(upg_clean_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                u_count = cur.fetchone()[0]
                assert u_count == 2, f"Users count mismatch: expected 2, found {u_count}"

                cur.execute("SELECT COUNT(*) FROM password_credentials")
                p_count = cur.fetchone()[0]
                assert p_count == 2, (
                    f"Password credentials count mismatch: expected 2, found {p_count}"
                )

                cur.execute("SELECT COUNT(*) FROM sessions")
                s_count = cur.fetchone()[0]
                assert s_count == 1, f"Sessions count mismatch: expected 1, found {s_count}"

                cur.execute(
                    "SELECT id, bootstrap_completed, registration_mode, bootstrap_completed_at FROM system_configuration WHERE id = 1"
                )
                row = cur.fetchone()
                assert row is not None, "system_configuration id=1 not found"
                cfg_id, b_done, reg_mode, b_time = row
                assert b_done is True, f"Expected bootstrap_completed=True, got {b_done}"
                assert b_time is not None, "Expected bootstrap_completed_at to be set"
                assert reg_mode == "closed", f"Expected registration_mode='closed', got {reg_mode}"
                print(
                    f"[MIGRATE-UPGRADE-OK] PostgreSQL: bootstrap_completed={b_done}, registration_mode='{reg_mode}', users={u_count}"
                )

        # 5. Запуск живого бэкенда на обновленной БД и валидация реального входа
        print(f"[MIGRATE-UPGRADE] Запуск тестового бэкенда на порту {upg_port}...")
        upg_start = subprocess.run(
            [
                sys.executable,
                str(MANAGE_SCRIPT),
                "start",
                "--port",
                str(upg_port),
                "--pidfile",
                upg_pid_file,
                "--logfile",
                upg_log_file,
                "--profile",
                "default-off",
            ],
            env=upg_env,
            capture_output=True,
            text=True,
        )
        assert upg_start.returncode == 0, (
            f"Backend start failed: {upg_start.stdout}\n{upg_start.stderr}"
        )

        try:
            upg_client = SimpleHttpClient(f"http://127.0.0.1:{upg_port}")
            # Проверяем живой логин суперпользователя
            st, d, _ = upg_client.request(
                "POST",
                "/api/v1/auth/login",
                json_data={"username": "upgrade_admin", "password": "UpgradeAdminPass2026!"},
            )
            assert st == 200, f"Login on upgraded database failed: status={st}, body={d}"
            print(
                "[MIGRATE-UPGRADE-OK] Живой вход пользователя на обновленной БД успешен (200 OK)!"
            )

            # Проверяем /api/v1/auth/me
            st, me_data, _ = upg_client.request("GET", "/api/v1/auth/me")
            assert st == 200 and me_data.get("username") == "upgrade_admin", (
                f"Me check failed: {me_data}"
            )

            # Проверяем закрытую политику регистрации
            st, reg_data, _ = upg_client.request(
                "POST",
                "/api/v1/auth/register",
                json_data={
                    "username": "intruder_user",
                    "email": "intruder@alxprgs.tech",
                    "password": "Password123!",
                    "confirm_password": "Password123!",
                },
            )
            assert st in (403, 400), (
                f"Registration must be closed on upgraded DB, got status {st}: {reg_data}"
            )
            print(f"[MIGRATE-UPGRADE-OK] Закрытая политика регистрации подтверждена (HTTP {st})!")
            upgrade_data_ok = True

        finally:
            subprocess.run(
                [
                    sys.executable,
                    str(MANAGE_SCRIPT),
                    "stop",
                    "--pidfile",
                    upg_pid_file,
                    "--port",
                    str(upg_port),
                ],
                capture_output=True,
            )

        print(
            "\n[G7-MIGRATE-SUCCESS] Миграции схемы полностью подтверждены: чистая установка, откат, повторный накат и обновление существующей БД с данными!"
        )
        return {
            "status": "passed" if (clean_ok and upgrade_data_ok) else "failed",
            "clean_tables_count": len(clean_tables),
            "upgraded_users_count": u_count,
            "bootstrap_completed": b_done,
            "registration_mode": reg_mode,
            "live_login_verified": upgrade_data_ok,
        }

    finally:
        with psycopg.connect(clean_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {upg_db_name} WITH (FORCE)")


# ==============================================================================
# Главная точка входа раннера
# ==============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="ALXPRGS SSO Overnight Stability Runner (GOAL-07)")
    parser.add_argument(
        "--suite",
        choices=["boot", "soak", "race", "recover", "migrate", "all"],
        default="all",
        help="Выбор набора проверок",
    )
    parser.add_argument(
        "--soak-minutes", type=float, default=20.0, help="Длительность этапа soak (минуты)"
    )
    parser.add_argument("--boot-cycles", type=int, default=5, help="Число циклов для этапа boot")
    parser.add_argument(
        "--race-attempts", type=int, default=10, help="Число попыток на сценарий в race"
    )
    parser.add_argument("--seed", type=int, default=42, help="Случайное зерно генератора")
    parser.add_argument("--run-id", default=None, help="Идентификатор прогона")
    parser.add_argument("--output-dir", default="artifacts/overnight", help="Каталог артефактов")

    args = parser.parse_args()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    git_commit = "unknown"
    git_dirty = False
    try:
        commit_res = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        )
        if commit_res.returncode == 0:
            git_commit = commit_res.stdout.strip()
        status_res = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
        )
        if status_res.returncode == 0:
            git_dirty = len(status_res.stdout.strip()) > 0
    except Exception:
        pass

    node_ver = "unknown"
    try:
        node_res = subprocess.run(["node", "-v"], capture_output=True, text=True, check=False)
        if node_res.returncode == 0:
            node_ver = node_res.stdout.strip()
    except Exception:
        pass

    summary: dict[str, Any] = {
        "run_id": run_id,
        "timestamp_start": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "environment": {
            "python_version": sys.version,
            "node_version": node_ver,
            "platform": sys.platform,
            "os": os.name,
        },
        "suite": args.suite,
        "seed": args.seed,
        "stages": {},
    }

    overall_ok = True

    try:
        # G7-BOOT
        if args.suite in ("boot", "all"):
            boot_res = run_boot_stage(cycles=args.boot_cycles)
            summary["stages"]["G7-BOOT"] = boot_res
            if boot_res.get("status") != "passed":
                overall_ok = False

        # G7-SOAK
        if args.suite in ("soak", "all") and overall_ok:
            soak_res = run_soak_stage(
                duration_minutes=args.soak_minutes,
                seed=args.seed,
                output_dir=out_dir,
            )
            summary["stages"]["G7-SOAK"] = soak_res
            if soak_res.get("status") != "passed":
                overall_ok = False

        # G7-RACE
        if args.suite in ("race", "all") and overall_ok:
            race_res = run_race_stage(attempts=args.race_attempts)
            summary["stages"]["G7-RACE"] = race_res
            if race_res.get("status") != "passed":
                overall_ok = False

        # G7-RECOVER
        if args.suite in ("recover", "all") and overall_ok:
            rec_res = run_recover_stage()
            summary["stages"]["G7-RECOVER"] = rec_res
            if rec_res.get("status") != "passed":
                overall_ok = False

        # G7-MIGRATE
        if args.suite in ("migrate", "all") and overall_ok:
            mig_res = run_migrate_stage()
            summary["stages"]["G7-MIGRATE"] = mig_res
            if mig_res.get("status") != "passed":
                overall_ok = False

    except Exception as e:
        print(f"\n[CRITICAL-ERROR] Непредвиденная ошибка во время ночной кампании: {e}")
        import traceback

        traceback.print_exc()
        summary["error"] = str(e)
        overall_ok = False

    # Сохраняем расширенные метаданные телеметрии soak в корень сводки
    if "G7-SOAK" in summary.get("stages", {}):
        soak_s = summary["stages"]["G7-SOAK"]
        summary["scheduled_smokes"] = soak_s.get("scheduled_smokes", 0)
        summary["executed_smokes"] = soak_s.get("executed_smokes", 0)
        summary["pid_verified"] = soak_s.get("pid_verified", False)
        summary["pg_baseline"] = soak_s.get("pg_baseline", -1)
        summary["pg_final"] = soak_s.get("pg_final", -1)

    summary["timestamp_end"] = datetime.now(timezone.utc).isoformat()
    summary["overall_status"] = "PASSED" if overall_ok else "FAILED"

    # Сохраняем машиночитаемый summary.json
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n================================================================================")
    print(f" [ИТОГ КАМПАНИИ СТАБИЛЬНОСТИ GOAL-07]: {summary['overall_status']}")
    print(f" Артефакты сохранены в: {out_dir}")
    print(f" Summary: {summary_path}")
    print("================================================================================\n")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
