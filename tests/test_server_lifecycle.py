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
from pathlib import Path

import pytest

from scripts import manage_test_server


def test_email_capabilities_require_verified_login(monkeypatch):
    caps = {
        "passkey_enabled": False,
        "totp_enabled": False,
        "recovery_codes_enabled": False,
        "email_verification_enabled": True,
        "require_verified_email": False,
    }
    monkeypatch.setattr(manage_test_server, "fetch_json", lambda *args, **kwargs: caps)
    assert manage_test_server.check_capabilities("http://localhost:8000", "email", "email") is False
    caps["require_verified_email"] = True
    assert manage_test_server.check_capabilities("http://localhost:8000", "email", "email") is True


def test_email_backend_filters_credentials_and_pins_database(tmp_path, monkeypatch):
    from types import SimpleNamespace

    captured = {}
    monkeypatch.setenv("TESTMAIL_API_KEY", "synthetic-testmail")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-aws")
    monkeypatch.setenv("DATABASE_URL", "unrelated-database")
    monkeypatch.setattr(manage_test_server, "is_port_in_use", lambda *args: False)
    monkeypatch.setattr(manage_test_server, "get_pid_listening_on_port", lambda *args: 123)
    monkeypatch.setattr(manage_test_server, "fetch_json", lambda *args, **kwargs: {"status": "ok"})

    def spawn(*args, **kwargs):
        captured.update(kwargs["env"])
        return SimpleNamespace(pid=123, poll=lambda: None)

    monkeypatch.setattr(manage_test_server.subprocess, "Popen", spawn)
    db = "postgresql+psycopg://localhost/alxprgs_sso_test"
    assert (
        manage_test_server.start_server(
            8000,
            str(tmp_path / "pid"),
            str(tmp_path / "log"),
            "email",
            env_vars={"TEST_DATABASE_URL": db, "REQUIRE_VERIFIED_EMAIL": "false"},
        )
        == 0
    )
    assert "TESTMAIL_API_KEY" not in captured
    assert captured["AWS_SECRET_ACCESS_KEY"] == "synthetic-aws"
    assert captured["REQUIRE_VERIFIED_EMAIL"] == "true"
    assert captured["DATABASE_URL"] == db
    assert captured["EMAIL_PROVIDER"] == "ses"


def test_email_backend_requires_explicit_test_database(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(manage_test_server, "is_port_in_use", lambda *args: False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Must fail before spawning backend")

    monkeypatch.setattr(manage_test_server.subprocess, "Popen", forbidden)
    assert (
        manage_test_server.start_server(8000, str(tmp_path / "pid"), str(tmp_path / "log"), "email")
        == 1
    )


def test_email_runner_cleans_up_after_browser_failure(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from scripts import run_e2e_suite
    from tests.helpers import email_test_settings, testmail_cli

    settings = email_test_settings.EmailTestSettings(
        _env_file=None, TESTMAIL_API_KEY="synthetic-runner", TESTMAIL_NAMESPACE="example"
    )
    monkeypatch.setattr(email_test_settings, "load_email_settings", lambda: settings)
    monkeypatch.setattr(testmail_cli, "preflight", lambda settings: None)
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://localhost/alxprgs_sso_test")
    monkeypatch.setenv("TESTMAIL_API_KEY", "synthetic-runner")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-aws")
    monkeypatch.setattr(run_e2e_suite, "ROOT_DIR", str(tmp_path))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs["env"]))
        return SimpleNamespace(
            returncode=1 if "playwright" in command else 0,
            stdout="synthetic-runner OTP 000123",
            stderr="synthetic-aws",
        )

    monkeypatch.setattr(run_e2e_suite.subprocess, "run", run)
    assert run_e2e_suite.run_email_e2e() == 1
    assert len([command for command, _ in calls if "stop" in command]) == 2
    backend_env = next(env for command, env in calls if "start" in command)
    frontend_env = next(env for command, env in calls if "start-frontend" in command)
    assert "TESTMAIL_API_KEY" not in backend_env
    assert "AWS_SECRET_ACCESS_KEY" not in frontend_env
    output = capsys.readouterr().out
    assert (
        "synthetic-runner" not in output
        and "000123" not in output
        and "synthetic-aws" not in output
    )


def test_stop_refuses_foreign_listener_before_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pidfile = tmp_path / "owned.pid"
    pidfile.write_text("101", encoding="utf-8")
    monkeypatch.setattr(manage_test_server, "get_pid_listening_on_port", lambda *args: 202)

    def forbidden_kill(*args: object, **kwargs: object) -> None:
        raise AssertionError("A foreign listener must never be killed")

    monkeypatch.setattr(manage_test_server.subprocess, "run", forbidden_kill)
    assert manage_test_server.stop_server(str(pidfile), port=54321) == 1
    assert pidfile.read_text(encoding="utf-8") == "101"


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
            "email_verification_enabled": True,
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


@pytest.mark.parametrize("failure_stage", range(5))
def test_browser_campaign_fails_closed_and_cleans_up(failure_stage, monkeypatch):
    """Unit orchestration: seed/start/preflight/browser/stop failure cannot pass."""
    from scripts import run_e2e_suite as runner

    calls = []
    cleanups = []

    def command(cmd, cwd=None, env=None):
        calls.append((cmd, env))
        return 7 if len(calls) - 1 == failure_stage else 0

    monkeypatch.setattr(runner, "run_cmd", command)
    monkeypatch.setattr(runner, "ensure_frontend_build", lambda: 0)
    monkeypatch.setattr(runner, "start_browser_frontend", lambda paths: 0)
    monkeypatch.setattr(runner, "cleanup_browser_campaign", cleanups.append)
    result = runner.run_e2e("all")
    assert result != 0
    assert len(cleanups) == 1
    assert len(calls) == failure_stage + 1
    assert calls[0][1]["FEATURE_PASSKEY_ENABLED"] == "false"
    if failure_stage >= 3:
        browser_command = calls[3][0]
        assert "e2e/appearance.spec.ts" in browser_command
        assert "e2e/privacy.spec.ts" in browser_command


def test_browser_campaign_profiles_preserve_flags_and_required_suites():
    from scripts.run_e2e_suite import browser_profiles

    profiles = browser_profiles("all", {"SMTP_HOST": "127.0.0.1"})
    assert [profile.name for profile in profiles] == ["default-off", "enabled"]
    assert profiles[0].env["FEATURE_TOTP_ENABLED"] == "false"
    assert profiles[1].env["FEATURE_TOTP_ENABLED"] == "true"
    for profile in profiles:
        assert profile.env["FEATURE_EMAIL_VERIFICATION_ENABLED"] == "true"
        assert profile.env["SMTP_HOST"] == "127.0.0.1"
        assert "e2e/privacy.spec.ts" in profile.specs
    assert "e2e/passkey.spec.ts" in profiles[1].specs


def test_browser_environment_pins_redirects_to_its_own_frontend(monkeypatch):
    from scripts.run_e2e_suite import browser_environment

    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    env = browser_environment()
    assert env["FRONTEND_URL"] == "http://localhost:5173"
    assert env["PLAYWRIGHT_BASE_URL"] == env["FRONTEND_URL"]
    assert env["WEBAUTHN_ORIGIN"] == env["FRONTEND_URL"]
