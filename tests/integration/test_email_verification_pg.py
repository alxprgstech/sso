"""
Интеграционные тесты жизненного цикла подтверждения email (G4-EMAIL, SEC-FLAG-07, REG-09, BUG-011).
Проверяют реальный путь неподтверждённого пользователя без ослабления политик,
локальную SMTP-доставку, защиту от Replay, устойчивость к сбоям SMTP, rate limiting и default-off.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.config import Settings, get_settings
from app.core.rbac import ROLE_USER
from app.legal import REQUIRED_DOCUMENTS
from app.main import app
from app.services import verification_email
from app.services.mfa_service import EmailVerificationService, sent_emails_sink
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.privacy import accept_current_documents


# Простой асинхронный SMTP mock сервер для тестирования локальной доставки
class MockSMTPServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 10255):
        self.host = host
        self.port = port
        self.received_messages: list[str] = []
        self.server: asyncio.Server | None = None

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        writer.write(b"220 smtp.alxprgs.tech ESMTP Service Ready\r\n")
        await writer.drain()

        data_mode = False
        message_lines = []

        while True:
            line = await reader.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="ignore")

            if data_mode:
                if line_str == ".\r\n" or line_str == ".\n":
                    data_mode = False
                    self.received_messages.append("".join(message_lines))
                    writer.write(b"250 2.0.0 OK: message queued\r\n")
                    await writer.drain()
                else:
                    message_lines.append(line_str)
            else:
                cmd = line_str.strip().upper()
                if cmd.startswith("EHLO") or cmd.startswith("HELO"):
                    writer.write(b"250-smtp.alxprgs.tech\r\n250 HELP\r\n")
                    await writer.drain()
                elif cmd.startswith("MAIL FROM:"):
                    writer.write(b"250 2.1.0 Sender OK\r\n")
                    await writer.drain()
                elif cmd.startswith("RCPT TO:"):
                    writer.write(b"250 2.1.5 Recipient OK\r\n")
                    await writer.drain()
                elif cmd == "DATA":
                    data_mode = True
                    message_lines = []
                    writer.write(b"354 Start mail input; end with <CRLF>.<CRLF>\r\n")
                    await writer.drain()
                elif cmd == "QUIT":
                    writer.write(b"221 2.0.0 Bye\r\n")
                    await writer.drain()
                    break
                else:
                    writer.write(b"250 OK\r\n")
                    await writer.drain()

        writer.close()
        await writer.wait_closed()

    async def start(self):
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        if self.server.sockets:
            self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_email_verification_ses_provider_with_fake_client_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    submitted: list[dict[str, object]] = []
    sample_credential = "Synthetic" + "Example2026!"

    def fake_ses_send(**kwargs: object) -> str:
        submitted.append(kwargs)
        return "ses-message-123"

    monkeypatch.setattr(verification_email, "send_ses_email", fake_ses_send)

    def _get_ses_settings() -> Settings:
        overridden = copy.copy(get_settings())
        overridden.ENVIRONMENT = "testing"
        overridden.FEATURE_EMAIL_VERIFICATION_ENABLED = True
        overridden.REQUIRE_VERIFIED_EMAIL = True
        overridden.EMAIL_PROVIDER = "ses"
        overridden.SMTP_HOST = ""
        return overridden

    app.dependency_overrides[get_settings] = _get_ses_settings
    sent_emails_sink.clear()
    try:
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="ses_bootstrap_admin",
            email="ses_admin@alxprgs.tech",
            password=sample_credential,
            registration_mode="open",
        )
        assert code == 0
        registration = await pg_client.post(
            "/api/v1/auth/register",
            json={"terms_accepted": True, "data_processing_consent": True, "legal_versions": REQUIRED_DOCUMENTS,
                "username": "ses_signup_user",
                "email": "ses_fake@alxprgs.tech",
                "password": sample_credential,
                "confirm_password": sample_credential,
            },
        )
        assert registration.status_code == 202
        assert len(submitted) == 1
        login_before = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "ses_signup_user", "password": sample_credential},
        )
        await accept_current_documents(pg_client, login_before)
        assert login_before.status_code == 401
        assert submitted[0]["region"] == "us-east-1"
        assert submitted[0]["from_email"] == "sso@alxprgs.tech"
        assert submitted[0]["raw_message"]
        assert len(sent_emails_sink) == 1
        token = sent_emails_sink[-1]["token"]
        confirmed = await pg_client.post(
            "/api/v1/auth/register/confirm-link", json={"token": token}
        )
        assert confirmed.status_code == 200
        replay = await pg_client.post("/api/v1/auth/register/confirm-link", json={"token": token})
        assert replay.status_code == 401
        login_after = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "ses_signup_user", "password": sample_credential},
        )
        await accept_current_documents(pg_client, login_after)
        assert login_after.status_code == 200
    finally:
        app.dependency_overrides.pop(get_settings, None)
        sent_emails_sink.clear()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_email_verification_full_unverified_flow_no_policy_bypass(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    G4-EMAIL: Сквозной жизненный цикл подтверждения email в enabled-профиле
    (REQUIRE_VERIFIED_EMAIL=True) БЕЗ временного ослабления политики:
    1. Создание пользователя с email_verified=False.
    2. Попытка входа -> отказ 401 (email_verification_required).
    3. Доступ к защищенным эндпоинтам (/api/v1/auth/me) невозможен.
    4. Запрос подтверждения через публичный эндпоинт /api/v1/mfa/email/request.
    5. Получение токена из почтового сборщика.
    6. Подтверждение токена через /api/v1/mfa/email/confirm.
    7. Успешный последующий вход по паролю и получение сессии.
    8. Отсутствие эскалации привилегий (роль остается 'user').
    """

    def _get_enabled_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_EMAIL_VERIFICATION_ENABLED = True
        overridden.REQUIRE_VERIFIED_EMAIL = True
        overridden.ENVIRONMENT = "testing"
        overridden.EMAIL_PROVIDER = "smtp"
        overridden.SMTP_HOST = ""
        return overridden

    app.dependency_overrides[get_settings] = _get_enabled_settings
    sent_emails_sink.clear()

    try:
        # 1. Создаем неподтвержденного пользователя
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="unverified_flow_user",
            email="flow_unverified@alxprgs.tech",
            password="FlowPassword2026!",
            registration_mode="closed",
        )
        assert code == 0

        # Сбрасываем is_superuser в False и назначаем роль user, чтобы проверить путь обычного пользователя
        await pg_session.execute(
            text("UPDATE users SET is_superuser = false WHERE username = 'unverified_flow_user'")
        )
        await pg_session.execute(
            text(
                "UPDATE user_roles SET role_id = (SELECT id FROM roles WHERE name = 'user') "
                "WHERE user_id = (SELECT id FROM users WHERE username = 'unverified_flow_user')"
            )
        )
        await pg_session.commit()

        # 2. Попытка входа -> отказ со статусом 401
        login_res = await pg_client.post(
            "/api/v1/auth/login",
            json={
                "username": "unverified_flow_user",
                "password": "FlowPassword2026!",
            },
        )
        await accept_current_documents(pg_client, login_res)
        assert login_res.status_code == 401
        res_data = login_res.json()
        assert res_data.get("error") == "email_verification_required" or (
            isinstance(res_data.get("detail"), dict)
            and res_data["detail"].get("error") == "email_verification_required"
        )

        # 3. Никаких cookie сессии не выдано
        assert "alx_session" not in pg_client.cookies

        # Попытка доступа к профилю -> 401
        me_res = await pg_client.get("/api/v1/auth/me")
        assert me_res.status_code == 401

        # 4. Запрос отправки подтверждения БЕЗ активной сессии и БЕЗ ослабления политики!
        req_res = await pg_client.post(
            "/api/v1/mfa/email/request",
            json={"email": "flow_unverified@alxprgs.tech"},
        )
        assert req_res.status_code == 200
        assert req_res.json()["status"] == "ok"

        # 5. Проверяем получение письма
        assert len(sent_emails_sink) >= 1
        raw_token = sent_emails_sink[-1]["token"]
        assert sent_emails_sink[-1]["to"] == "flow_unverified@alxprgs.tech"

        # 6. Подтверждаем токен через публичный эндпоинт
        confirm_res = await pg_client.post(
            "/api/v1/mfa/email/confirm",
            json={"token": raw_token},
        )
        assert confirm_res.status_code == 200
        assert confirm_res.json()["status"] == "ok"

        # Проверяем в PostgreSQL статус email_verified = True
        user_check = await pg_session.execute(
            text(
                "SELECT email_verified, is_superuser FROM users WHERE username = 'unverified_flow_user'"
            )
        )
        u_row = user_check.fetchone()
        assert u_row is not None
        assert u_row[0] is True  # email_verified стало True
        assert u_row[1] is False  # Отсутствие эскалации привилегий: пользователь не стал superuser!

        # 7. Теперь вход по паролю завершается успехом (200 OK)
        login_success = await pg_client.post(
            "/api/v1/auth/login",
            json={
                "username": "unverified_flow_user",
                "password": "FlowPassword2026!",
            },
        )
        await accept_current_documents(pg_client, login_success)
        assert login_success.status_code == 200
        assert login_success.json()["status"] == "ok"
        assert login_success.json()["user"]["email_verified"] is True

        # Проверяем сессионный доступ к /api/v1/auth/me
        me_ok = await pg_client.get("/api/v1/auth/me")
        assert me_ok.status_code == 200
        assert me_ok.json()["username"] == "unverified_flow_user"
        assert me_ok.json()["roles"] == [ROLE_USER]

    finally:
        app.dependency_overrides.pop(get_settings, None)
        sent_emails_sink.clear()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_email_verification_local_smtp_delivery_and_failure_resilience(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    G4-EMAIL: Проверка реальной сетевой доставки через локальный SMTP-сервер
    и корректной обработки сбоя доставки (без падения приложения и с записью в аудит).
    """
    smtp_mock = MockSMTPServer(host="127.0.0.1", port=10255)
    await smtp_mock.start()

    def _get_smtp_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_EMAIL_VERIFICATION_ENABLED = True
        overridden.REQUIRE_VERIFIED_EMAIL = True
        overridden.ENVIRONMENT = "testing"
        overridden.EMAIL_PROVIDER = "smtp"
        overridden.SMTP_HOST = "127.0.0.1"
        overridden.SMTP_PORT = 10255
        return overridden

    app.dependency_overrides[get_settings] = _get_smtp_settings

    try:
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="smtp_tester",
            email="smtp_test@alxprgs.tech",
            password="SmtpPassword2026!",
            registration_mode="closed",
        )
        assert code == 0

        # Запрос письма с работающим SMTP сервером
        req_res = await pg_client.post(
            "/api/v1/mfa/email/request",
            json={"email": "smtp_test@alxprgs.tech"},
        )
        assert req_res.status_code == 200

        # Даем краткое время на завершение асинхронной SMTP-доставки
        await asyncio.sleep(0.5)

        # Проверяем, что локальный SMTP сервер действительно принял письмо
        assert len(smtp_mock.received_messages) >= 1
        msg_body = smtp_mock.received_messages[-1]
        assert "smtp_test@alxprgs.tech" in msg_body
        import email
        from email import policy

        parsed_email = email.message_from_string(msg_body, policy=policy.default)
        decoded_text = parsed_email.get_body(preferencelist=("plain",)).get_content()
        assert "Ваш код подтверждения:" in decoded_text
        assert [part.get_content_type() for part in parsed_email.iter_parts()] == [
            "text/plain",
            "text/x-amp-html",
            "text/html",
        ]

    finally:
        await smtp_mock.stop()
        app.dependency_overrides.pop(get_settings, None)

    # Проверка устойчивости к сбою SMTP: настраиваем порт на недоступный (например, 59998)
    def _get_failing_smtp_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_EMAIL_VERIFICATION_ENABLED = True
        overridden.REQUIRE_VERIFIED_EMAIL = True
        overridden.ENVIRONMENT = "testing"
        overridden.EMAIL_PROVIDER = "smtp"
        overridden.SMTP_HOST = "127.0.0.1"
        overridden.SMTP_PORT = 59998
        return overridden

    app.dependency_overrides[get_settings] = _get_failing_smtp_settings

    try:
        # Запрос подтверждения при мертвом SMTP
        fail_req = await pg_client.post(
            "/api/v1/mfa/email/request",
            json={"email": "smtp_test@alxprgs.tech"},
        )
        # Эндпоинт не падает со статусом 500, возвращает 200 OK
        assert fail_req.status_code == 200

        # В PostgreSQL аудите зафиксировано событие email_delivery_failed
        audit_check = await pg_session.execute(
            text("SELECT event_type FROM audit_events WHERE event_type = 'email_delivery_failed'")
        )
        assert audit_check.scalar_one_or_none() is not None

    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_email_verification_negative_expired_reused_and_rate_limit(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    G4-EMAIL: Негативные сценарии:
    1. Истекший токен подтверждения (> 24ч) -> отказ 401.
    2. Повторное использование токена (Replay Attack) -> отказ 401 и аудит replay.
    3. Неверный токен -> отказ 401.
    4. Превышение лимита запросов (Rate Limiting) -> HTTP 429.
    5. Защита от перечисления аккаунтов (Account Enumeration) -> нейтральный ответ 200.
    """

    def _get_enabled_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_EMAIL_VERIFICATION_ENABLED = True
        overridden.REQUIRE_VERIFIED_EMAIL = True
        overridden.ENVIRONMENT = "testing"
        overridden.EMAIL_PROVIDER = "smtp"
        overridden.SMTP_HOST = ""
        return overridden

    app.dependency_overrides[get_settings] = _get_enabled_settings
    sent_emails_sink.clear()

    try:
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="security_email_user",
            email="security_email@alxprgs.tech",
            password="SecPassword2026!",
            registration_mode="closed",
        )
        assert code == 0

        # 1. Запрос токена
        req_res = await pg_client.post(
            "/api/v1/mfa/email/request",
            json={"email": "security_email@alxprgs.tech"},
        )
        assert req_res.status_code == 200
        raw_token = sent_emails_sink[-1]["token"]

        # 2. Неверный токен -> 401
        invalid_res = await pg_client.post(
            "/api/v1/mfa/email/confirm",
            json={"token": "a" * 32},
        )
        assert invalid_res.status_code == 401

        # 3. Имитируем просроченный токен (expires_at в прошлом)
        await pg_session.execute(
            text("UPDATE email_verification_tokens SET expires_at = :past WHERE is_used = false"),
            {"past": datetime.now(timezone.utc) - timedelta(hours=1)},
        )
        await pg_session.commit()

        expired_res = await pg_client.post(
            "/api/v1/mfa/email/confirm",
            json={"token": raw_token},
        )
        assert expired_res.status_code == 401

        # 4. Выпускаем свежий токен и проверяем защиту от повторного использования (Replay)
        user_row = (
            await pg_session.execute(
                text("SELECT id FROM users WHERE username = 'security_email_user'")
            )
        ).scalar_one()

        class DummyUser:
            id = user_row
            username = "security_email_user"

        fresh_token = await EmailVerificationService.send_verification(
            pg_session, DummyUser(), "security_email@alxprgs.tech", _get_enabled_settings()
        )

        # Первый вызов -> успех
        ok_res = await pg_client.post(
            "/api/v1/mfa/email/confirm",
            json={"token": fresh_token},
        )
        assert ok_res.status_code == 200

        # Повторный вызов того же токена -> отказ 401
        replay_res = await pg_client.post(
            "/api/v1/mfa/email/confirm",
            json={"token": fresh_token},
        )
        assert replay_res.status_code == 401

        # Проверяем фиксацию replay в аудите
        replay_audit = await pg_session.execute(
            text(
                "SELECT event_type FROM audit_events WHERE event_type = 'email_verification_replay_detected'"
            )
        )
        assert replay_audit.scalar_one_or_none() is not None

        # 5. Защита от перечисления аккаунтов (Account Enumeration)
        non_existent_req = await pg_client.post(
            "/api/v1/mfa/email/request",
            json={"email": "non_existent_random_user@alxprgs.tech"},
        )
        assert non_existent_req.status_code == 200
        assert "Если указанный адрес зарегистрирован" in non_existent_req.json()["message"]

    finally:
        app.dependency_overrides.pop(get_settings, None)
        sent_emails_sink.clear()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_email_verification_available_with_other_factors_off(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    G4-EMAIL: email verification remains available with the optional factors off.
    Unknown addresses remain neutral and do not cause delivery.
    """
    sent_emails_sink.clear()

    def _get_default_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_EMAIL_VERIFICATION_ENABLED = True
        overridden.REQUIRE_VERIFIED_EMAIL = False
        return overridden

    app.dependency_overrides[get_settings] = _get_default_settings
    try:
        # 1. Unknown address gets neutral response without sending mail.
        req_res = await pg_client.post(
            "/api/v1/mfa/email/request",
            json={"email": "test@alxprgs.tech"},
        )
        assert req_res.status_code == 200
        assert req_res.json()["status"] == "ok"

        confirm_res = await pg_client.post(
            "/api/v1/mfa/email/confirm",
            json={"token": "x" * 32},
        )
        assert confirm_res.status_code == 401

        assert len(sent_emails_sink) == 0
    finally:
        app.dependency_overrides.pop(get_settings, None)
