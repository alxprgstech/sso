import copy
import hashlib
import uuid

import httpx
import pyotp
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.config import Settings, get_settings
from app.main import app
from app.services.mfa_service import sent_emails_sink
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.privacy import accept_current_documents
from tests.helpers.reauthentication import MutationRequest, RequestAuthorization, authorized_request


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_default_off_profile_capabilities_and_404_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-08, SEC-FLAG-01, SEC-FLAG-02: Три отложенных фактора выключены.
    Прямые вызовы эндпоинтов MFA возвращают 404 feature_disabled.
    """

    def _get_default_off_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_TOTP_ENABLED = False
        overridden.FEATURE_PASSKEY_ENABLED = False
        overridden.FEATURE_RECOVERY_CODES_ENABLED = False
        overridden.FEATURE_EMAIL_VERIFICATION_ENABLED = True
        overridden.REQUIRE_VERIFIED_EMAIL = False
        return overridden

    app.dependency_overrides[get_settings] = _get_default_off_settings
    try:
        # 1. Проверяем capabilities
        cap_res = await pg_client.get("/api/v1/auth/capabilities")
        assert cap_res.status_code == 200
        caps = cap_res.json()
        assert caps["totp_enabled"] is False
        assert caps["passkey_enabled"] is False
        assert caps["recovery_codes_enabled"] is False
        assert caps["email_verification_enabled"] is True

        # 2. Создаем пользователя и входим
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="mfa_disabled_user",
            email="mfa_dis@alxprgs.tech",
            password="PasswordDisabled2026!",
            registration_mode="closed",
        )
        assert code == 0

        login_res = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "mfa_disabled_user", "password": "PasswordDisabled2026!"},
        )
        await accept_current_documents(pg_client, login_res)
        assert login_res.status_code == 200
        csrf_token = login_res.json()["csrf_token"]

        # 3. Прямые вызовы всех MFA эндпоинтов возвращают 404 Not Found (SEC-FLAG-02)
        # 3.1 TOTP setup
        totp_setup = await pg_client.post(
            "/api/v1/mfa/totp/setup",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert totp_setup.status_code == 404
        assert totp_setup.json()["error"] == "feature_disabled"

        # 3.2 Recovery codes generate
        rec_gen = await pg_client.post(
            "/api/v1/mfa/recovery-codes/generate",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert rec_gen.status_code == 404
        assert rec_gen.json()["error"] == "feature_disabled"

        # 3.3 Passkey register options
        passkey_opt = await pg_client.post(
            "/api/v1/mfa/passkey/register/options",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert passkey_opt.status_code == 404
        assert passkey_opt.json()["error"] == "feature_disabled"

        # 3.4 Email request is always available. Use an unknown address without a session.
        pg_client.cookies.clear()
        email_req = await pg_client.post(
            "/api/v1/mfa/email/request",
            json={"email": "unknown@alxprgs.tech"},
        )
        assert email_req.status_code == 200
        assert email_req.json()["status"] == "ok"
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_default_off_no_silent_bypass_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-08, SEC-FLAG-04: Инвариант предотвращения скрытого понижения класса защиты (No Silent Bypass).
    Если у пользователя в БД есть настроенный MFA фактор (TOTP), но на сервере флаг выключен:
    вход по одному только паролю строго блокируется (login_blocked_mfa_disabled), обход запрещен.
    """
    # 1. Создаем пользователя
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="mfa_legacy_user",
        email="legacy@alxprgs.tech",
        password="LegacyPassword2026!",
        registration_mode="closed",
    )
    assert code == 0

    # Получаем id пользователя
    u_res = await pg_session.execute(
        text("SELECT id FROM users WHERE username = 'mfa_legacy_user'")
    )
    uid = u_res.scalar_one()

    # 2. Эмулируем запись в totp_credentials с is_confirmed = True
    await pg_session.execute(
        text(
            "INSERT INTO totp_credentials (id, user_id, encrypted_secret, is_confirmed, created_at) "
            "VALUES (gen_random_uuid(), :uid, 'dummy_encrypted_secret', true, now())"
        ),
        {"uid": uid},
    )
    await pg_session.commit()

    # 3. Пользователь пытается войти по паролю в default-профиле (где FEATURE_TOTP_ENABLED=False)
    # Попытка должна быть ЗАБЛОКИРОВАНА со статусом 401
    login_res = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "mfa_legacy_user", "password": "LegacyPassword2026!"},
    )
    await accept_current_documents(pg_client, login_res)
    assert login_res.status_code == 401
    assert "второго фактора" in str(login_res.json())

    # 4. Проверяем в PostgreSQL запись аудита login_blocked_mfa_disabled
    audit_res = await pg_session.execute(
        text(
            "SELECT event_type FROM audit_events WHERE event_type = 'login_blocked_mfa_disabled' AND user_id = :uid"
        ),
        {"uid": uid},
    )
    assert audit_res.scalar_one_or_none() is not None


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_enabled_profile_totp_lifecycle_encrypted_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-08, SEC-FLAG-03, USR-04: Полный жизненный цикл TOTP при включенном флаге:
    - Шифрование секретов в PostgreSQL с отдельным ключом TOTP_ENCRYPTION_KEY (открытый ключ в БД не хранится).
    - Валидация одноразового кода через RFC 6238 pyotp.
    - Активация is_confirmed=True.
    """

    # Включаем профиль FEATURE_TOTP_ENABLED
    def _get_enabled_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_TOTP_ENABLED = True
        return overridden

    app.dependency_overrides[get_settings] = _get_enabled_settings

    try:
        # 1. Создаем пользователя и входим
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="totp_tester",
            email="totp_tester@alxprgs.tech",
            password="TotpPassword2026!",
            registration_mode="closed",
        )
        assert code == 0

        login_res = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "totp_tester", "password": "TotpPassword2026!"},
        )
        await accept_current_documents(pg_client, login_res)
        csrf_token = login_res.json()["csrf_token"]
        uid = login_res.json()["user"]["id"]

        # 2. Вызываем /api/v1/mfa/totp/setup -> получаем секрет и URI
        setup_res = await authorized_request(
            pg_client,
            MutationRequest("POST", "/api/v1/mfa/totp/setup"),
            RequestAuthorization("TotpPassword2026!", {"X-CSRF-Token": csrf_token}),
        )
        assert setup_res.status_code == 200
        setup_data = setup_res.json()
        assert "secret" in setup_data
        assert "otpauth_url" in setup_data
        raw_secret = setup_data["secret"]

        # 3. Инвариант безопасности: в PostgreSQL секрет зашифрован
        totp_row = await pg_session.execute(
            text(
                "SELECT encrypted_secret, is_confirmed FROM totp_credentials WHERE user_id = :uid"
            ),
            {"uid": uuid.UUID(uid)},
        )
        stored = totp_row.fetchone()
        assert stored is not None
        assert stored[0] != raw_secret  # Секрет зашифрован (не равен сырому)
        assert stored[1] is False  # Пока не подтвержден

        # 4. Попытка подтвердить неверным кодом -> 400 или 401
        fail_confirm = await authorized_request(
            pg_client,
            MutationRequest("POST", "/api/v1/mfa/totp/confirm", json_body={"code": "000000"}),
            RequestAuthorization("TotpPassword2026!", {"X-CSRF-Token": csrf_token}),
        )
        assert fail_confirm.status_code in (400, 401)

        # 5. Подтверждение валидным TOTP кодом
        totp_gen = pyotp.TOTP(raw_secret)
        valid_code = totp_gen.now()

        ok_confirm = await authorized_request(
            pg_client,
            MutationRequest("POST", "/api/v1/mfa/totp/confirm", json_body={"code": valid_code}),
            RequestAuthorization("TotpPassword2026!", {"X-CSRF-Token": csrf_token}),
        )
        assert ok_confirm.status_code == 200
        assert ok_confirm.json()["status"] == "ok"

        # 6. Проверяем статус в PostgreSQL
        totp_updated = await pg_session.execute(
            text("SELECT is_confirmed FROM totp_credentials WHERE user_id = :uid"),
            {"uid": uuid.UUID(uid)},
        )
        assert totp_updated.scalar_one() is True

        # Аудит totp_enabled
        audit_res = await pg_session.execute(
            text(
                "SELECT event_type FROM audit_events WHERE event_type = 'totp_enabled' AND user_id = :uid"
            ),
            {"uid": uuid.UUID(uid)},
        )
        assert audit_res.scalar_one_or_none() is not None

    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_enabled_profile_recovery_codes_dependency_and_burn_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-08, SEC-FLAG-05, USR-05: Резервные коды (Recovery codes):
    - Строгая зависимость от активного TOTP (SEC-FLAG-05).
    - Выпуск 10 кодов, сохранение в PostgreSQL в виде необратимых хешей SHA-256.
    - Одноразовое погашение кода на шаге входа.
    - Защита от Replay: повторное использование сгоревшего кода отклоняется.
    """

    def _get_enabled_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_TOTP_ENABLED = True
        overridden.FEATURE_RECOVERY_CODES_ENABLED = True
        return overridden

    app.dependency_overrides[get_settings] = _get_enabled_settings

    try:
        # 1. Создаем пользователя
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="recovery_tester",
            email="rec_tester@alxprgs.tech",
            password="RecPassword2026!",
            registration_mode="closed",
        )
        assert code == 0

        login_res = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "recovery_tester", "password": "RecPassword2026!"},
        )
        await accept_current_documents(pg_client, login_res)
        csrf_token = login_res.json()["csrf_token"]
        uid = uuid.UUID(login_res.json()["user"]["id"])

        # 2. Инвариант SEC-FLAG-05: попытка генерации recovery codes БЕЗ активного TOTP отклоняется
        fail_gen = await authorized_request(
            pg_client,
            MutationRequest("POST", "/api/v1/mfa/recovery-codes/generate"),
            RequestAuthorization("RecPassword2026!", {"X-CSRF-Token": csrf_token}),
        )
        assert fail_gen.status_code in (400, 403)
        assert "TOTP" in str(fail_gen.json())

        # 3. Активируем TOTP
        setup_res = await authorized_request(
            pg_client,
            MutationRequest("POST", "/api/v1/mfa/totp/setup"),
            RequestAuthorization("RecPassword2026!", {"X-CSRF-Token": csrf_token}),
        )
        raw_secret = setup_res.json()["secret"]
        await authorized_request(
            pg_client,
            MutationRequest(
                "POST", "/api/v1/mfa/totp/confirm", json_body={"code": pyotp.TOTP(raw_secret).now()}
            ),
            RequestAuthorization("RecPassword2026!", {"X-CSRF-Token": csrf_token}),
        )

        # 4. Теперь генерируем резервные коды -> 10 кодов
        gen_res = await authorized_request(
            pg_client,
            MutationRequest("POST", "/api/v1/mfa/recovery-codes/generate"),
            RequestAuthorization(
                "RecPassword2026!",
                {"X-CSRF-Token": csrf_token},
                factor={
                    "method": "totp",
                    "code": pyotp.TOTP(raw_secret).at(__import__("time").time() + 30),
                },
            ),
        )
        assert gen_res.status_code == 200
        codes = gen_res.json()["recovery_codes"]
        assert len(codes) == 10

        # 5. Проверяем в PostgreSQL: сохранено 10 хешей, открытых кодов нет
        rc_db = await pg_session.execute(
            text("SELECT code_hash, is_used FROM recovery_codes WHERE user_id = :uid"),
            {"uid": uid},
        )
        rc_rows = rc_db.fetchall()
        assert len(rc_rows) == 10
        for r in rc_rows:
            assert r[0] not in codes  # Хеш, а не открытый код!
            assert r[1] is False  # is_used is False initially

        # 6. Выходим из сессии
        await pg_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_token})

        # 7. Первый шаг входа по паролю -> mfa_required
        mfa_step1 = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "recovery_tester", "password": "RecPassword2026!"},
        )
        await accept_current_documents(pg_client, mfa_step1)
        assert mfa_step1.status_code == 200
        step1_data = mfa_step1.json()
        assert step1_data.get("mfa_required") is True
        assert "mfa_token" in step1_data
        mfa_token = step1_data["mfa_token"]
        assert "recovery_code" in step1_data["available_methods"]

        # 8. Второй шаг: погашение первого резервного кода (codes[0])
        burn_code = codes[0]
        step2_res = await pg_client.post(
            "/api/v1/mfa/recovery-codes/verify",
            json={"mfa_token": mfa_token, "recovery_code": burn_code},
        )
        assert step2_res.status_code == 200
        assert step2_res.json()["status"] == "ok"
        # Сессия установлена
        assert "alx_session" in pg_client.cookies

        # 9. Проверяем в PostgreSQL: код помечен как сгоревший (is_used = True)
        norm_burn = burn_code.replace("-", "").replace(" ", "").upper().strip()
        burn_hash = hashlib.sha256(norm_burn.encode("utf-8")).hexdigest()
        burned_check = await pg_session.execute(
            text("SELECT is_used, used_at FROM recovery_codes WHERE code_hash = :bh"),
            {"bh": burn_hash},
        )
        burned_row = burned_check.fetchone()
        assert burned_row is not None
        assert burned_row[0] is True  # is_used is True
        assert burned_row[1] is not None  # used_at is recorded

        # 10. Replay Attack: попытка повторно использовать тот же код
        # Инициируем новый шаг 1
        mfa_step1_rep = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "recovery_tester", "password": "RecPassword2026!"},
        )
        await accept_current_documents(pg_client, mfa_step1_rep)
        mfa_token_rep = mfa_step1_rep.json()["mfa_token"]

        replay_step2 = await pg_client.post(
            "/api/v1/mfa/recovery-codes/verify",
            json={"mfa_token": mfa_token_rep, "recovery_code": burn_code},
        )
        assert replay_step2.status_code == 401
        assert "использованный" in str(replay_step2.json())

    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_enabled_profile_email_verification_and_enforcement_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-08, SEC-FLAG-07, REG-09: Подтверждение email и принудительное требование (REQUIRE_VERIFIED_EMAIL=true):
    - При REQUIRE_VERIFIED_EMAIL=True неподтвержденный пользователь блокируется на входе.
    - Выпуск токена подтверждения в локальный sink (без реальной отправки писем, SEC-FLAG-07).
    - Атомарное подтверждение email через /api/v1/mfa/email/confirm.
    - Успешный последующий вход.
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

    try:
        # 1. Создаем пользователя с email_verified = False
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="unverified_user",
            email="unverified@alxprgs.tech",
            password="UnverifiedPassword2026!",
            registration_mode="closed",
        )
        assert code == 0

        # 2. Инвариант REG-09: вход блокируется со статусом 401
        login_blocked = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "unverified_user", "password": "UnverifiedPassword2026!"},
        )
        await accept_current_documents(pg_client, login_blocked)
        assert login_blocked.status_code == 401
        assert "подтверждение адреса" in str(login_blocked.json())

        # Аудит login_blocked_unverified_email в PostgreSQL
        audit_res = await pg_session.execute(
            text(
                "SELECT event_type FROM audit_events WHERE event_type = 'login_blocked_unverified_email'"
            )
        )
        assert audit_res.scalar_one_or_none() is not None

        # 3. Запрашиваем токен подтверждения email напрямую БЕЗ входа и БЕЗ ослабления политики (G4-EMAIL)
        sent_emails_sink.clear()
        req_res = await pg_client.post(
            "/api/v1/mfa/email/request",
            json={"email": "unverified@alxprgs.tech"},
        )
        assert req_res.status_code == 200

        # 4. Проверяем локальный сборщик писем (mock sink, SEC-FLAG-07)
        assert len(sent_emails_sink) >= 1
        raw_email_token = sent_emails_sink[-1]["token"]
        assert sent_emails_sink[-1]["to"] == "unverified@alxprgs.tech"

        # 5. Проверяем запись в PostgreSQL email_verification_tokens
        tok_hash = hashlib.sha256(raw_email_token.encode("utf-8")).hexdigest()
        tok_db = await pg_session.execute(
            text("SELECT is_used FROM email_verification_tokens WHERE token_hash = :th"),
            {"th": tok_hash},
        )
        assert tok_db.scalar_one() is False

        # 6. Подтверждаем email через публичный эндпоинт
        confirm_res = await pg_client.post(
            "/api/v1/mfa/email/confirm",
            json={"token": raw_email_token},
        )
        assert confirm_res.status_code == 200
        assert confirm_res.json()["status"] == "ok"

        # 7. Проверяем в PostgreSQL: users.email_verified стало True
        u_status = await pg_session.execute(
            text("SELECT email_verified FROM users WHERE username = 'unverified_user'")
        )
        assert u_status.scalar_one() is True

        # 8. Теперь вход успешно разрешен даже при REQUIRE_VERIFIED_EMAIL=True!
        login_ok = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "unverified_user", "password": "UnverifiedPassword2026!"},
        )
        await accept_current_documents(pg_client, login_ok)
        assert login_ok.status_code == 200
        assert login_ok.json()["status"] == "ok"

    finally:
        app.dependency_overrides.pop(get_settings, None)
        sent_emails_sink.clear()
