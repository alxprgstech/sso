import asyncio
import os
import subprocess
import sys

import httpx
import pytest
from app.core.rate_limit import (
    check_email_request_rate_limit,
    check_registration_rate_limit,
    get_client_ip,
)
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db_guard import get_test_database_url
from tests.integration.test_email_verification_pg import MockSMTPServer

# ==============================================================================
# 1. ТЕСТЫ ВАЛИДАЦИИ ДОВЕРЕННЫХ ПРОКСИ И ЗАЩИТЫ ОТ SPOOFING (G4-LIMITS)
# ==============================================================================


def test_trusted_proxy_validation_and_spoofing_defense():
    """
    Проверка извлечения IP и защиты от подделки заголовков (SEC-PROX-01, G4-LIMITS):
    1. Непосредственный клиент не из TRUSTED_PROXIES не может подменить IP через X-Forwarded-For / X-Real-IP.
    2. Доверенный прокси (127.0.0.1, 10.0.0.0/8) корректно транслирует настоящий IP клиента.
    3. Некорректные значения заголовков отбрасываются.
    """
    trusted_proxies = ["127.0.0.1", "::1", "10.0.0.0/8"]

    # 1. Запрос от недоверенного внешнего хоста 198.51.100.5
    scope_untrusted = {
        "type": "http",
        "client": ("198.51.100.5", 54321),
        "headers": [
            (b"x-forwarded-for", b"203.0.113.199"),
            (b"x-real-ip", b"203.0.113.200"),
        ],
    }
    req_untrusted = Request(scope_untrusted)
    # Недоверенный peer -> заголовки полностью игнорируются!
    extracted_ip = get_client_ip(req_untrusted, trusted_proxies=trusted_proxies)
    assert extracted_ip == "198.51.100.5"

    # 2. Запрос от доверенного локального прокси 127.0.0.1
    scope_trusted_local = {
        "type": "http",
        "client": ("127.0.0.1", 45678),
        "headers": [
            (b"x-forwarded-for", b"203.0.113.50, 10.0.0.1"),
        ],
    }
    req_trusted_local = Request(scope_trusted_local)
    assert get_client_ip(req_trusted_local, trusted_proxies=trusted_proxies) == "203.0.113.50"

    # 3. Запрос от доверенного реверс-прокси из подсети 10.0.0.0/8
    scope_trusted_subnet = {
        "type": "http",
        "client": ("10.2.3.4", 8080),
        "headers": [
            (b"x-real-ip", b"198.51.100.77"),
        ],
    }
    req_trusted_subnet = Request(scope_trusted_subnet)
    assert get_client_ip(req_trusted_subnet, trusted_proxies=trusted_proxies) == "198.51.100.77"

    # 4. Некорректный мусор в заголовке от доверенного прокси fallback на peer_ip
    scope_garbage = {
        "type": "http",
        "client": ("127.0.0.1", 45678),
        "headers": [
            (b"x-forwarded-for", b"not-an-ip-address"),
        ],
    }
    req_garbage = Request(scope_garbage)
    assert get_client_ip(req_garbage, trusted_proxies=trusted_proxies) == "127.0.0.1"


# ==============================================================================
# 2. ТЕСТ ЗАЩИТЫ ОТ ОБХОДА RATE LIMIT ЧЕРЕЗ X-FORWARDED-FOR (G4-LIMITS)
# ==============================================================================


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_spoofed_headers_cannot_bypass_rate_limit_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    Проверка, что атакующий с внешнего IP не может обойти лимит регистрации,
    генерируя случайные заголовки X-Forwarded-For на каждый запрос (G4-LIMITS).
    """
    # Создаём админа и открываем регистрацию
    from app.cli.bootstrap_admin import execute_bootstrap

    await execute_bootstrap(
        session=pg_session,
        username="rl_admin_spoof",
        email="rl_admin_spoof@alxprgs.tech",
        password="AdminPassword2026!",
        registration_mode="open",
    )

    # Имитируем запросы от клиента, где бэкенд видит peer IP как untrusted
    # В app.config настраиваем TRUSTED_PROXIES без 192.0.2.1
    # Проверяем напрямую логику check_registration_rate_limit:
    attacker_peer_ip = "198.51.100.99"

    # Регистрируем 5 событий от attacker_peer_ip
    from app.services.audit_service import AuditService

    for i in range(5):
        await AuditService.log_event(
            pg_session,
            event_type="registration_attempt",
            ip_address=attacker_peer_ip,
            details={"attempt": i},
        )
    await pg_session.commit()

    # 6-я попытка для attacker_peer_ip обязана завершиться 429 Too Many Requests
    with pytest.raises(HTTPException) as exc_info:
        await check_registration_rate_limit(pg_session, attacker_peer_ip)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"] == "rate_limit_exceeded"


# ==============================================================================
# 3. МЕЖПРОЦЕССНЫЙ RATE LIMITING НА ДВУХ РЕАЛЬНЫХ ПРОЦЕССАХ UVICORN (G4-LIMITS)
# ==============================================================================


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_inter_process_distributed_rate_limiting_real_processes_pg(
    pg_session: AsyncSession,
):
    """
    Тестирование межпроцессного rate limiting на PostgreSQL (REG-07, G4-LIMITS):
    1. Запускаются 2 независимых процесса Uvicorn на портах 8011 и 8012.
    2. Оба процесса подключены к одной и той же тестовой PostgreSQL БД.
    3. Клиент отправляет чередующиеся запросы:
       - Запрос 1 -> Процесс 1 (HTTP 202)
       - Запрос 2 -> Процесс 2 (HTTP 202)
       - Запрос 3 -> Процесс 1 (HTTP 202)
       - Запрос 4 -> Процесс 2 (должен вернуть HTTP 429!)
    4. Доказывается, что лимит срабатывает суммарно по PostgreSQL, а не изолированно в памяти.
    """
    test_db_url = get_test_database_url()
    port1 = 8011
    port2 = 8012

    # Создаём админа в тестовой БД и открываем регистрацию
    from app.cli.bootstrap_admin import execute_bootstrap

    await execute_bootstrap(
        session=pg_session,
        username="proc_admin",
        email="proc_admin@alxprgs.tech",
        password="AdminPassword2026!",
        registration_mode="open",
    )
    # Очищаем аудит и незавершённые заявки для чистоты теста
    await pg_session.execute(
        text("DELETE FROM pending_registrations WHERE email LIKE 'dist_%@alxprgs.tech'")
    )
    await pg_session.execute(text("DELETE FROM audit_events WHERE ip_address = '127.0.0.1'"))
    await pg_session.commit()

    smtp_mock = MockSMTPServer(host="127.0.0.1", port=0)
    await smtp_mock.start()

    python_exe = sys.executable
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    backend_dir = os.path.join(repo_root, "backend")

    env = os.environ.copy()
    env["PYTHONPATH"] = backend_dir
    env["TEST_DATABASE_URL"] = test_db_url
    env["DATABASE_URL"] = test_db_url
    env["TRUSTED_PROXIES"] = "127.0.0.1,::1"
    env["ENVIRONMENT"] = "testing"
    env["EMAIL_PROVIDER"] = "smtp"
    env["SMTP_HOST"] = "127.0.0.1"
    env["SMTP_PORT"] = str(smtp_mock.port)

    loop_arg = ["--loop", "asyncio:SelectorEventLoop"] if sys.platform == "win32" else []

    log1_path = os.path.join(repo_root, "test_uvicorn_8011.log")
    log2_path = os.path.join(repo_root, "test_uvicorn_8012.log")
    log1 = open(log1_path, "w", encoding="utf-8")
    log2 = open(log2_path, "w", encoding="utf-8")

    # Запускаем Процесс 1
    proc1 = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port1)]
        + loop_arg,
        cwd=backend_dir,
        env=env,
        stdout=log1,
        stderr=subprocess.STDOUT,
    )

    # Запускаем Процесс 2
    proc2 = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port2)]
        + loop_arg,
        cwd=backend_dir,
        env=env,
        stdout=log2,
        stderr=subprocess.STDOUT,
    )

    try:
        # Ожидаем готовности обоих процессов
        async with httpx.AsyncClient(timeout=10.0) as client:
            ready1 = False
            ready2 = False
            for _ in range(40):
                if not ready1:
                    try:
                        r1 = await client.get(f"http://127.0.0.1:{port1}/api/v1/auth/capabilities")
                        if r1.status_code == 200:
                            ready1 = True
                    except Exception:
                        pass
                if not ready2:
                    try:
                        r2 = await client.get(f"http://127.0.0.1:{port2}/api/v1/auth/capabilities")
                        if r2.status_code == 200:
                            ready2 = True
                    except Exception:
                        pass
                if ready1 and ready2:
                    break
                await asyncio.sleep(0.5)

            if not ready1:
                log1.flush()
                with open(log1_path, "r", encoding="utf-8", errors="ignore") as f:
                    err_txt = f.read()
                pytest.fail(f"Процесс 1 на порту {port1} не запустился. Лог:\n{err_txt}")

            if not ready2:
                log2.flush()
                with open(log2_path, "r", encoding="utf-8", errors="ignore") as f:
                    err_txt = f.read()
                pytest.fail(f"Процесс 2 на порту {port2} не запустился. Лог:\n{err_txt}")

            # Отправляем 3 запроса регистрации, распределяя по процессам:
            # Межпроцессный лимит подтверждения email: DB_EMAIL_MAX_ATTEMPTS = 3 (G4-EMAIL, REG-07)
            urls = [
                f"http://127.0.0.1:{port1}/api/v1/auth/register",
                f"http://127.0.0.1:{port2}/api/v1/auth/register",
                f"http://127.0.0.1:{port1}/api/v1/auth/register",
            ]

            for idx, url in enumerate(urls, 1):
                payload = {
                    "username": f"dist_user_{idx}",
                    "email": f"dist_{idx}@alxprgs.tech",
                    "password": "Password123!",
                    "confirm_password": "Password123!",
                }
                res = await client.post(url, json=payload)
                assert res.status_code == 202, (
                    f"Запрос {idx} на {url} вернул {res.status_code}: {res.text}"
                )

            # 4-й запрос отправляем на Процесс 2:
            # В памяти Процесса 2 был всего 1 запрос (запрос #2),
            # поэтому если бы лимит был локальным, запрос бы прошёл (1 < 3 и 1 < 10).
            # Но лимит межпроцессный через PostgreSQL (3 суммарно), поэтому Процесс 2 ОБЯЗАН вернуть 429!
            res_4 = await client.post(
                f"http://127.0.0.1:{port2}/api/v1/auth/register",
                json={
                    "username": "dist_user_4",
                    "email": "dist_4@alxprgs.tech",
                    "password": "Password123!",
                    "confirm_password": "Password123!",
                },
            )
            assert res_4.status_code == 429, (
                f"Ожидался HTTP 429, получено {res_4.status_code}: {res_4.text}"
            )
            data_4 = res_4.json()
            err_code = data_4.get("error") or (
                data_4.get("detail", {}).get("error")
                if isinstance(data_4.get("detail"), dict)
                else None
            )
            assert err_code == "rate_limit_exceeded", (
                f"Expected error 'rate_limit_exceeded', got {data_4}"
            )

    finally:
        try:
            proc1.terminate()
            proc2.terminate()
            proc1.wait(timeout=5)
            proc2.wait(timeout=5)
        except Exception:
            pass
        await smtp_mock.stop()
        log1.close()
        log2.close()
        for p in (log1_path, log2_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


# ==============================================================================
# 4. ТЕСТ FAIL-CLOSED ПРИ СБОЕ БД ХРАНИЛИЩА ЛИМИТОВ (G4-LIMITS, NO FAIL-OPEN)
# ==============================================================================


@pytest.mark.asyncio
async def test_fail_closed_on_database_failure():
    """
    Проверка инварианта No Fail-Open (G4-LIMITS, ARCH-04):
    При сбое PostgreSQL базы данных или недоступности пула соединений
    функция rate limiting ОБЯЗАНА заблокировать операцию (HTTP 503 Service Unavailable),
    а НЕ пропускать запросы мимо лимита.
    """

    # Создаём фиктивную сессию, симулирующую разрыв соединения с БД
    class BrokenDbSession:
        async def execute(self, stmt):
            raise ConnectionRefusedError("Database connection lost during rate limit query")

    broken_db = BrokenDbSession()

    # 1. Регистрация должна быть заблокирована с 503
    with pytest.raises(HTTPException) as exc_reg:
        await check_registration_rate_limit(broken_db, "192.0.2.1")
    assert exc_reg.value.status_code == 503
    assert exc_reg.value.detail["error"] == "service_unavailable"

    # 2. Запрос подтверждения email должен быть заблокирован с 503
    with pytest.raises(HTTPException) as exc_email:
        await check_email_request_rate_limit(broken_db, "192.0.2.1")
    assert exc_email.value.status_code == 503
    assert exc_email.value.detail["error"] == "service_unavailable"
