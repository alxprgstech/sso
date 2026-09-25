"""
Инфраструктурные регрессионные тесты жизненного цикла тестового сервера и preflight проверок (G6-RUNTIME, G6-PREFLIGHT).
Проверяют:
1. Запуск и надежная остановка процесса с освобождением порта (без зомби-процессов).
2. Защита от запуска при уже занятом порте (PortInUse fail-fast).
3. Preflight проверка capabilities: успешное прохождение при совпадении профиля.
4. Preflight проверка capabilities: немедленный отказ при несовпадении профиля (fail-fast).
"""

import os
import socket
import subprocess
import sys
import tempfile

import pytest


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_port_already_in_use_fail_fast():
    """Проверка, что старт немедленно завершается с ошибкой, если порт уже занят."""
    port = get_free_port()
    # Занимаем порт сокетом
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))
        s.listen(1)

        # Пытаемся запустить сервер на том же порту
        res = subprocess.run(
            [
                sys.executable,
                "scripts/manage_test_server.py",
                "start",
                "--port",
                str(port),
                "--pidfile",
                os.path.join(tempfile.gettempdir(), f"test_in_use_{port}.pid"),
                "--logfile",
                os.path.join(tempfile.gettempdir(), f"test_in_use_{port}.log"),
                "--profile",
                "default-off",
            ],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 1
        assert "уже занят" in res.stdout


def test_preflight_capabilities_mismatch_fail_fast():
    """Проверка, что preflight завершается с кодом 1, если capabilities не совпадают с ожидаемым профилем."""
    # Имитируем URL, возвращающий default-off, но запрашиваем проверку 'enabled'
    # Используем unit-уровень без необходимости реального сервера
    import unittest.mock

    from scripts.manage_test_server import check_capabilities

    mock_caps = {
        "capabilities": {
            "passkey_enabled": False,
            "totp_enabled": False,
            "recovery_codes_enabled": False,
            "email_verification_enabled": False,
        }
    }

    with unittest.mock.patch("scripts.manage_test_server.fetch_json", return_value=mock_caps):
        # 1. default-off ожидает default-off -> успех
        assert check_capabilities("http://localhost:8000", "default-off", "Test Backend") is True
        # 2. enabled ожидает enabled, но получил default-off -> отказ
        assert check_capabilities("http://localhost:8000", "enabled", "Test Backend") is False


def test_real_server_lifecycle_and_port_release():
    """
    Реальный запуск и остановка тестового сервера uvicorn:
    1. Запуск на свободном порту.
    2. Проверка, что порт занят и /health/live отвечает.
    3. Preflight capabilities default-off -> True.
    4. Остановка сервера через manage_test_server.py stop.
    5. Проверка, что порт ГАРАНТИРОВАННО освобожден и сокет закрыт.
    """
    port = get_free_port()
    pidfile = os.path.join(tempfile.gettempdir(), f"sso_test_server_{port}.pid")
    logfile = os.path.join(tempfile.gettempdir(), f"sso_test_server_{port}.log")

    try:
        # 1. Запуск
        start_res = subprocess.run(
            [
                sys.executable,
                "scripts/manage_test_server.py",
                "start",
                "--port",
                str(port),
                "--pidfile",
                pidfile,
                "--logfile",
                logfile,
                "--profile",
                "default-off",
                "--timeout",
                "15",
            ],
            capture_output=True,
            text=True,
        )
        assert start_res.returncode == 0, f"Start failed: {start_res.stdout}\n{start_res.stderr}"
        assert os.path.exists(pidfile)

        # 2. Preflight
        pref_res = subprocess.run(
            [
                sys.executable,
                "scripts/manage_test_server.py",
                "preflight",
                "--profile",
                "default-off",
                "--backend-url",
                f"http://127.0.0.1:{port}",
            ],
            capture_output=True,
            text=True,
        )
        assert pref_res.returncode == 0, f"Preflight failed: {pref_res.stdout}"

        # 3. Preflight с неверным профилем 'enabled' должен упасть
        pref_wrong = subprocess.run(
            [
                sys.executable,
                "scripts/manage_test_server.py",
                "preflight",
                "--profile",
                "enabled",
                "--backend-url",
                f"http://127.0.0.1:{port}",
            ],
            capture_output=True,
            text=True,
        )
        assert pref_wrong.returncode == 1

    finally:
        # 4. Остановка
        stop_res = subprocess.run(
            [
                sys.executable,
                "scripts/manage_test_server.py",
                "stop",
                "--pidfile",
                pidfile,
                "--port",
                str(port),
            ],
            capture_output=True,
            text=True,
        )
        assert stop_res.returncode == 0

        # 5. Проверяем, что порт свободен
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            with pytest.raises((socket.error, ConnectionRefusedError, OSError)):
                s.connect(("127.0.0.1", port))


def test_frontend_missing_build_fail_fast():
    """Проверка, что start-frontend немедленно завершается с ошибкой, если dist/index.html отсутствует."""
    empty_dir = tempfile.mkdtemp()
    port = get_free_port()
    pidfile = os.path.join(tempfile.gettempdir(), f"sso_fe_missing_{port}.pid")
    logfile = os.path.join(tempfile.gettempdir(), f"sso_fe_missing_{port}.log")

    res = subprocess.run(
        [
            sys.executable,
            "scripts/manage_test_server.py",
            "start-frontend",
            "--port",
            str(port),
            "--pidfile",
            pidfile,
            "--logfile",
            logfile,
            "--frontend-dir",
            empty_dir,
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "Сборка фронтенда не найдена" in res.stdout
    assert "npm run build" in res.stdout
    assert not os.path.exists(pidfile)


def test_frontend_port_already_in_use_fail_fast():
    """Проверка, что start-frontend немедленно завершается с ошибкой, если порт уже занят."""
    port = get_free_port()
    pidfile = os.path.join(tempfile.gettempdir(), f"sso_fe_inuse_{port}.pid")
    logfile = os.path.join(tempfile.gettempdir(), f"sso_fe_inuse_{port}.log")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))
        s.listen(1)

        res = subprocess.run(
            [
                sys.executable,
                "scripts/manage_test_server.py",
                "start-frontend",
                "--port",
                str(port),
                "--pidfile",
                pidfile,
                "--logfile",
                logfile,
            ],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 1
        assert "уже занят" in res.stdout
        assert not os.path.exists(pidfile)


def test_frontend_early_crash_diagnostic_log():
    """
    Проверка, что при аварийном завершении процесса фронтенда (Vite preview)
    выводится код возврата процесса и хвост лога ошибки.
    """
    # Создаем фиктивный frontend-dir с dist/index.html (чтобы пройти preflight),
    # но node_modules/vite/bin/vite.js заменяем на скрипт с немедленным выходом с кодом 42 и сообщением в stderr
    temp_fe = tempfile.mkdtemp()
    os.makedirs(os.path.join(temp_fe, "dist"), exist_ok=True)
    with open(os.path.join(temp_fe, "dist", "index.html"), "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><body>Test</body></html>")

    vite_bin_dir = os.path.join(temp_fe, "node_modules", "vite", "bin")
    os.makedirs(vite_bin_dir, exist_ok=True)
    vite_fake_js = os.path.join(vite_bin_dir, "vite.js")
    with open(vite_fake_js, "w", encoding="utf-8") as f:
        f.write("console.error('Fatal crash test: synthetic vite error'); process.exit(42);\n")

    port = get_free_port()
    pidfile = os.path.join(tempfile.gettempdir(), f"sso_fe_crash_{port}.pid")
    logfile = os.path.join(tempfile.gettempdir(), f"sso_fe_crash_{port}.log")

    res = subprocess.run(
        [
            sys.executable,
            "scripts/manage_test_server.py",
            "start-frontend",
            "--port",
            str(port),
            "--pidfile",
            pidfile,
            "--logfile",
            logfile,
            "--frontend-dir",
            temp_fe,
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "аварийно завершился с кодом 42" in res.stdout
    assert "ЛОГ ФРОНТЕНДА (хвост)" in res.stdout
    assert "Fatal crash test: synthetic vite error" in res.stdout


def test_real_frontend_lifecycle_and_port_release():
    """Реальный запуск и остановка frontend preview сервера с верификацией HTTP ответа и освобождения порта."""
    root_fe = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
    dist_index = os.path.join(root_fe, "dist", "index.html")
    if not os.path.exists(dist_index):
        # Собираем если отсутствует
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        bld = subprocess.run([npm_cmd, "run", "build"], cwd=root_fe)
        if bld.returncode != 0:
            pytest.skip("frontend/dist не собран и npm run build не удался")

    port = get_free_port()
    pidfile = os.path.join(tempfile.gettempdir(), f"sso_fe_{port}.pid")
    logfile = os.path.join(tempfile.gettempdir(), f"sso_fe_{port}.log")

    try:
        start_res = subprocess.run(
            [
                sys.executable,
                "scripts/manage_test_server.py",
                "start-frontend",
                "--port",
                str(port),
                "--pidfile",
                pidfile,
                "--logfile",
                logfile,
                "--timeout",
                "15",
            ],
            capture_output=True,
            text=True,
        )
        assert start_res.returncode == 0, (
            f"Start frontend failed: {start_res.stdout}\n{start_res.stderr}"
        )
        assert os.path.exists(pidfile)

        # Проверяем живой HTTP-ответ от preview сервера
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3.0) as resp:
            assert resp.status == 200
            content = resp.read().decode("utf-8")
            assert "<!DOCTYPE html>" in content or "<html" in content

    finally:
        stop_res = subprocess.run(
            [
                sys.executable,
                "scripts/manage_test_server.py",
                "stop",
                "--pidfile",
                pidfile,
                "--port",
                str(port),
            ],
            capture_output=True,
            text=True,
        )
        assert stop_res.returncode == 0

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            with pytest.raises((socket.error, ConnectionRefusedError, OSError)):
                s.connect(("127.0.0.1", port))
