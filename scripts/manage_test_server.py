"""
ALXPRGS SSO - Скрипт надежного управления процессами тестового сервера и preflight проверки (G6-RUNTIME, G6-PREFLIGHT).
Обеспечивает:
1. Запуск uvicorn с фиксацией реального PID процесса (без промежуточных subshell).
2. Ожидание готовности /health/live с fail-fast выводом логов при сбое.
3. Fail-fast preflight валидацию capabilities напрямую бэкенда и через frontend proxy.
4. Надежную остановку процесса (SIGTERM -> SIGKILL) с верификацией освобождения сокета порта.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except (socket.error, ConnectionRefusedError, OSError):
            return False


def fetch_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "SSO-Lifecycle-Manager/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def check_capabilities(
    target_url: str,
    expected_profile: str,
    label: str,
    retries: int = 3,
) -> bool:
    endpoint = f"{target_url.rstrip('/')}/api/v1/auth/capabilities"
    data = None
    for attempt in range(retries):
        try:
            data = fetch_json(endpoint, timeout=10.0)
            break
        except Exception as e:
            if attempt == retries - 1:
                print(
                    f"[PREFLIGHT-FAIL] {label}: Ошибка запроса capabilities по адресу {endpoint}: {e}"
                )
                return False
            time.sleep(1.0)

    caps = data.get("capabilities", data)
    passkey = caps.get("passkey_enabled")
    totp = caps.get("totp_enabled")
    recovery = caps.get("recovery_codes_enabled")
    email = caps.get("email_verification_enabled")

    print(
        f"[PREFLIGHT-INFO] {label} ({endpoint}) capabilities: "
        f"passkey={passkey}, totp={totp}, recovery={recovery}, email={email}"
    )

    if expected_profile == "default-off":
        if passkey is not False or totp is not False or recovery is not False or email is not False:
            print(
                f"[PREFLIGHT-FAIL] {label}: Ожидался профиль default-off (все флаги False), "
                f"но получено: passkey={passkey}, totp={totp}, recovery={recovery}, email={email}"
            )
            return False
    elif expected_profile == "enabled":
        if passkey is not True:
            print(
                f"[PREFLIGHT-FAIL] {label}: Ожидался профиль enabled (passkey=True), "
                f"но получено: passkey={passkey}"
            )
            return False
    return True


def start_server(
    port: int,
    pidfile: str,
    logfile: str,
    profile: str,
    env_vars: dict[str, str] | None = None,
    host: str = "127.0.0.1",
    timeout: int = 15,
) -> int:
    if is_port_in_use(port, host):
        print(f"[START-ERROR] Порт {port} уже занят другим процессом перед запуском!")
        return 1

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    backend_dir = os.path.join(root_dir, "backend")

    os.makedirs(os.path.dirname(os.path.abspath(pidfile)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(logfile)), exist_ok=True)

    loop_arg = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
    runner_code = (
        "import sys, asyncio; "
        "(asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()) if sys.platform == 'win32' else None); "
        "import uvicorn; "
        f"uvicorn.run('app.main:app', host='{host}', port={port}, app_dir=r'{backend_dir}', log_level='info', loop='{loop_arg}')"
    )
    cmd = [sys.executable, "-c", runner_code]

    merged_env = os.environ.copy()
    if profile == "default-off":
        merged_env["FEATURE_TOTP_ENABLED"] = "false"
        merged_env["FEATURE_PASSKEY_ENABLED"] = "false"
        merged_env["FEATURE_RECOVERY_CODES_ENABLED"] = "false"
        merged_env["FEATURE_EMAIL_VERIFICATION_ENABLED"] = "false"
        merged_env["REQUIRE_VERIFIED_EMAIL"] = "false"
    elif profile == "enabled":
        merged_env["FEATURE_TOTP_ENABLED"] = "true"
        merged_env["FEATURE_PASSKEY_ENABLED"] = "true"
        merged_env["FEATURE_RECOVERY_CODES_ENABLED"] = "true"
        merged_env["FEATURE_EMAIL_VERIFICATION_ENABLED"] = "true"
        merged_env["REQUIRE_VERIFIED_EMAIL"] = "false"

    if "TEST_DATABASE_URL" in merged_env:
        merged_env["DATABASE_URL"] = merged_env["TEST_DATABASE_URL"]
        merged_env["DATABASE_URL_SYNC"] = merged_env["TEST_DATABASE_URL"]

    if env_vars:
        merged_env.update(env_vars)

    log_handle = open(logfile, "w", encoding="utf-8")
    extra_flags = 0
    if sys.platform == "win32":
        # На Windows CREATE_NEW_PROCESS_GROUP изолирует группу процессов
        extra_flags = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        cmd,
        cwd=root_dir,
        env=merged_env,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        close_fds=True,
        creationflags=extra_flags,
    )

    with open(pidfile, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))

    print(f"[START] Запущен сервер (PID {proc.pid}, порт {port}, профиль {profile})")

    # Ждём /health/live
    start_time = time.time()
    health_url = f"http://{host}:{port}/health/live"
    live = False
    while time.time() - start_time < timeout:
        if proc.poll() is not None:
            print(
                f"[START-ERROR] Процесс сервера (PID {proc.pid}) аварийно завершился с кодом {proc.returncode}!"
            )
            log_handle.flush()
            with open(logfile, "r", encoding="utf-8", errors="replace") as rf:
                print("--- ЛОГ СЕРВЕРА ---\n" + rf.read())
            return 1

        try:
            res = fetch_json(health_url, timeout=1.0)
            if res.get("status") == "ok":
                live = True
                break
        except Exception:
            time.sleep(0.5)

    if not live:
        print(f"[START-ERROR] Таймаут ожидания готовности {health_url} ({timeout}с)!")
        log_handle.flush()
        with open(logfile, "r", encoding="utf-8", errors="replace") as rf:
            print("--- ЛОГ СЕРВЕРА ---\n" + rf.read())
        return 1

    print(f"[START-OK] Сервер (PID {proc.pid}) успешно запущен и отвечает на {health_url}")
    return 0


def stop_server(
    pidfile: str, port: int | None = None, host: str = "127.0.0.1", timeout: int = 5
) -> int:
    if not os.path.exists(pidfile):
        print(f"[STOP-WARN] PID-файл {pidfile} не найден.")
        if port and is_port_in_use(port, host):
            print(f"[STOP-WARN] Порт {port} всё ещё занят, хотя pidfile отсутствует!")
            return 1
        return 0

    with open(pidfile, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        print(f"[STOP-WARN] PID-файл {pidfile} пуст.")
        return 0

    pid = int(content)
    print(f"[STOP] Остановка процесса сервера (PID {pid})...")

    # Отправляем сигнал завершения
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        except Exception as e:
            print(f"[STOP-WARN] Ошибка taskkill PID {pid}: {e}")
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            print(f"[STOP-WARN] Ошибка kill SIGTERM PID {pid}: {e}")

    # Ждём завершения процесса
    start_time = time.time()
    while time.time() - start_time < timeout:
        if sys.platform == "win32":
            res = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True
            )
            if str(pid) not in res.stdout:
                break
        else:
            try:
                os.kill(pid, 0)
                time.sleep(0.3)
            except ProcessLookupError:
                break

    # Если задан порт, проверяем освобождение сокета
    if port:
        port_free = False
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not is_port_in_use(port, host):
                port_free = True
                break
            time.sleep(0.3)

        if not port_free:
            print(f"[STOP-ERROR] Порт {port} НЕ был освобожден после остановки PID {pid}!")
            return 1

    try:
        os.remove(pidfile)
    except OSError:
        pass

    print(
        f"[STOP-OK] Сервер (PID {pid}) успешно остановлен"
        + (f", порт {port} свободен" if port else "")
    )
    return 0


def start_frontend(
    port: int = 5173,
    host: str = "127.0.0.1",
    pidfile: str = "/tmp/frontend.pid",
    logfile: str = "/tmp/frontend.log",
    backend_url: str = "http://localhost:8000",
    timeout: int = 25,
) -> int:
    if is_port_in_use(port, host):
        print(f"[START-ERROR] Порт фронтенда {port} уже занят!")
        return 1

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    frontend_dir = os.path.join(root_dir, "frontend")
    vite_bin = os.path.join(frontend_dir, "node_modules", "vite", "bin", "vite.js")

    os.makedirs(os.path.dirname(os.path.abspath(pidfile)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(logfile)), exist_ok=True)

    cmd = ["node", vite_bin, "preview", "--host", host, "--port", str(port)]
    merged_env = os.environ.copy()
    merged_env["VITE_BACKEND_TARGET"] = backend_url

    log_handle = open(logfile, "w", encoding="utf-8")
    extra_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

    proc = subprocess.Popen(
        cmd,
        cwd=frontend_dir,
        env=merged_env,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        close_fds=True,
        creationflags=extra_flags,
    )

    with open(pidfile, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))

    print(
        f"[START-FRONTEND] Запущен процесс фронтенда (PID {proc.pid}, порт {port}, backend {backend_url})"
    )

    start_time = time.time()
    url = f"http://{host}:{port}/"
    live = False
    while time.time() - start_time < timeout:
        if proc.poll() is not None:
            print(f"[START-ERROR] Фронтенд (PID {proc.pid}) аварийно завершился!")
            return 1
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    live = True
                    break
        except Exception:
            time.sleep(0.5)

    if not live:
        print(f"[START-ERROR] Таймаут ожидания фронтенда по адресу {url} ({timeout}с)!")
        return 1

    print(f"[START-OK] Фронтенд готов по адресу {url}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Управление тестовым сервером ALXPRGS SSO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = subparsers.add_parser("start", help="Запустить uvicorn сервер")
    p_start.add_argument("--port", type=int, default=8000)
    p_start.add_argument("--host", default="127.0.0.1")
    p_start.add_argument("--pidfile", default="/tmp/backend.pid")
    p_start.add_argument("--logfile", default="/tmp/backend.log")
    p_start.add_argument("--profile", choices=["default-off", "enabled"], required=True)
    p_start.add_argument("--timeout", type=int, default=15)

    # start-frontend
    p_start_fe = subparsers.add_parser("start-frontend", help="Запустить frontend preview сервер")
    p_start_fe.add_argument("--port", type=int, default=5173)
    p_start_fe.add_argument("--host", default="127.0.0.1")
    p_start_fe.add_argument("--pidfile", default="/tmp/frontend.pid")
    p_start_fe.add_argument("--logfile", default="/tmp/frontend.log")
    p_start_fe.add_argument("--backend-url", default="http://localhost:8000")
    p_start_fe.add_argument("--timeout", type=int, default=25)

    # stop
    p_stop = subparsers.add_parser("stop", help="Остановить сервер")
    p_stop.add_argument("--pidfile", default="/tmp/backend.pid")
    p_stop.add_argument("--port", type=int, default=None)
    p_stop.add_argument("--host", default="127.0.0.1")
    p_stop.add_argument("--timeout", type=int, default=5)

    # preflight
    p_preflight = subparsers.add_parser("preflight", help="Проверить capabilities")
    p_preflight.add_argument("--profile", choices=["default-off", "enabled"], required=True)
    p_preflight.add_argument("--backend-url", required=True)
    p_preflight.add_argument("--frontend-url", default=None)

    args = parser.parse_args()

    if args.command == "start":
        return start_server(
            port=args.port,
            pidfile=args.pidfile,
            logfile=args.logfile,
            profile=args.profile,
            host=args.host,
            timeout=args.timeout,
        )
    elif args.command == "start-frontend":
        return start_frontend(
            port=args.port,
            host=args.host,
            pidfile=args.pidfile,
            logfile=args.logfile,
            backend_url=args.backend_url,
            timeout=args.timeout,
        )
    elif args.command == "stop":
        return stop_server(
            pidfile=args.pidfile,
            port=args.port,
            host=args.host,
            timeout=args.timeout,
        )
    elif args.command == "preflight":
        ok_backend = check_capabilities(args.backend_url, args.profile, "Direct Backend")
        ok_frontend = True
        if args.frontend_url:
            ok_frontend = check_capabilities(args.frontend_url, args.profile, "Frontend Proxy")
        return 0 if (ok_backend and ok_frontend) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
