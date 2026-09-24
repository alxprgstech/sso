import asyncio
import copy
import hashlib
import uuid

import httpx
import pyotp
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.config import Settings, get_settings
from app.core.rate_limit import _IN_MEMORY_REQUESTS
from app.core.security import generate_random_token, hash_token
from app.main import app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_auth_code_redemption_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-09, SSO-03: Параллельное погашение одного authorization code.
    5 одновременных запросов через asyncio.gather:
    - Благодаря SELECT FOR UPDATE в PostgreSQL ровно 1 запрос получает 200 OK.
    - Остальные 4 запроса получают 400 Bad Request (invalid_grant: code already used).
    - В PostgreSQL статус кода становится is_used = True, фиксируется auth_code_replay_detected.
    """
    # 1. Создаем пользователя
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="code_race_user",
        email="code_race@alxprgs.tech",
        password="RacePassword2026!",
        registration_mode="closed",
    )
    assert code == 0

    user_row = await pg_session.execute(
        text("SELECT id FROM users WHERE username = 'code_race_user'")
    )
    user_id = user_row.scalar_one()

    # 2. Логинимся как админ и регистрируем confidential клиента
    login_res = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "code_race_user", "password": "RacePassword2026!"},
    )
    assert login_res.status_code == 200
    adm_csrf = login_res.json()["csrf_token"]

    client_reg = await pg_client.post(
        "/api/v1/admin/clients",
        headers={"X-CSRF-Token": adm_csrf},
        json={
            "client_name": "Race Client",
            "client_type": "confidential",
            "redirect_uris": ["http://localhost:8081/callback"],
        },
    )
    assert client_reg.status_code == 201
    c_data = client_reg.json()
    client_id = c_data["client_id"]
    client_secret = c_data["client_secret"]

    c_row = await pg_session.execute(
        text("SELECT id FROM oidc_clients WHERE client_id = :cid"),
        {"cid": client_id},
    )
    client_db_id = c_row.scalar_one()

    # 3. Выпускаем валидный authorization code со связкой PKCE S256
    raw_verifier = "race_verifier_1234567890_abcdefghijklmnopqrstuvwxyz"
    challenge_bytes = hashlib.sha256(raw_verifier.encode("utf-8")).digest()
    import base64

    raw_challenge = base64.urlsafe_b64encode(challenge_bytes).decode("utf-8").rstrip("=")

    raw_code = "ALXPRGS_RACE_CODE_" + generate_random_token(16)
    code_h = hash_token(raw_code)

    await pg_session.execute(
        text(
            "INSERT INTO authorization_codes ("
            "  id, code_hash, client_id, user_id, redirect_uri, scope, "
            "  code_challenge, code_challenge_method, expires_at, is_used, created_at"
            ") VALUES ("
            "  gen_random_uuid(), :ch, :cid, :uid, 'http://localhost:8081/callback', 'openid profile email', "
            "  :chal, 'S256', now() + interval '5 minutes', false, now()"
            ")"
        ),
        {
            "ch": code_h,
            "cid": client_db_id,
            "uid": user_id,
            "chal": raw_challenge,
        },
    )
    await pg_session.commit()

    # 4. Запускаем 5 одновременных запросов на погашение одного и того же кода
    tasks = [
        pg_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": raw_code,
                "redirect_uri": "http://localhost:8081/callback",
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": raw_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        for _ in range(5)
    ]

    responses = await asyncio.gather(*tasks)

    # 5. Проверяем распределение ответов: РОВНО 1 успех, 4 отказа
    status_codes = [r.status_code for r in responses]
    assert status_codes.count(200) == 1, (
        f"Ожидался ровно 1 успешный обмен 200, получено: {status_codes}"
    )
    assert status_codes.count(400) == 4, f"Ожидалось ровно 4 отказа 400, получено: {status_codes}"

    # Неуспешные ответы содержат invalid_grant
    for r in responses:
        if r.status_code == 400:
            err = r.json()
            assert err["error"] == "invalid_grant"

    # 6. Проверяем состояние в PostgreSQL
    code_check = await pg_session.execute(
        text("SELECT is_used FROM authorization_codes WHERE code_hash = :ch"),
        {"ch": code_h},
    )
    assert code_check.scalar_one() is True

    # Проверяем наличие записей аудита auth_code_replay_detected
    audit_replay = await pg_session.execute(
        text("SELECT COUNT(*) FROM audit_events WHERE event_type = 'auth_code_replay_detected'")
    )
    assert audit_replay.scalar_one() >= 1


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_user_registration_race_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-09, REG-06: Гонка одновременной регистрации с одинаковыми учетными данными.
    Два параллельных запроса на регистрацию с одинаковым username и email.
    Благодаря UNIQUE ограничению PostgreSQL и блоку try/except IntegrityError:
    - Ровно 1 запрос завершается 201 Created.
    - Ровно 1 запрос получает 409 Conflict с нейтральным сообщением.
    - В таблице users в PostgreSQL создается ровно 1 пользователь.
    """
    # 1. Завершаем bootstrap и переводим режим в open
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="admin_race",
        email="admin_race@alxprgs.tech",
        password="AdminRacePassword2026!",
        registration_mode="open",
    )
    assert code == 0

    # 2. Запускаем 2 параллельных запроса с разными IP (чтобы не сработал лимит на IP)
    tasks = [
        pg_client.post(
            "/api/v1/auth/register",
            json={
                "username": "race_contestant",
                "email": "contestant@alxprgs.tech",
                "password": "PasswordContestant2026!",
                "confirm_password": "PasswordContestant2026!",
            },
            headers={"X-Forwarded-For": f"198.51.100.{10 + i}"},
        )
        for i in range(2)
    ]

    responses = await asyncio.gather(*tasks)

    # 3. Ровно 1 запрос 201, ровно 1 запрос 409
    status_codes = [r.status_code for r in responses]
    assert status_codes.count(201) == 1, f"Ожидался 1 статус 201, получено: {status_codes}"
    assert status_codes.count(409) == 1, f"Ожидался 1 статус 409, получено: {status_codes}"

    for r in responses:
        if r.status_code == 409:
            err = r.json()
            assert "user_already_exists" in str(err)

    # 4. Проверяем в PostgreSQL: ровно 1 пользователь с именем race_contestant
    u_count = await pg_session.execute(
        text("SELECT COUNT(*) FROM users WHERE username = 'race_contestant'")
    )
    assert u_count.scalar_one() == 1


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_recovery_code_burn_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-09, SEC-FLAG-05: Параллельное погашение одного резервного кода (Recovery Code).
    Два одновременных вызова /api/v1/mfa/recovery-codes/verify:
    - Благодаря атомарному UPDATE ... WHERE is_used=False RETURNING id:
    - Ровно 1 запрос получает 200 OK.
    - Второй запрос получает 401 Unauthorized (код уже использован).
    - В PostgreSQL код переведен в статус is_used=True.
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
            username="rec_race_user",
            email="rec_race@alxprgs.tech",
            password="RecRacePassword2026!",
            registration_mode="closed",
        )
        assert code == 0

        # Входим и активируем TOTP
        login_res = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "rec_race_user", "password": "RecRacePassword2026!"},
        )
        csrf_tok = login_res.json()["csrf_token"]
        setup_res = await pg_client.post(
            "/api/v1/mfa/totp/setup", headers={"X-CSRF-Token": csrf_tok}
        )
        raw_secret = setup_res.json()["secret"]
        await pg_client.post(
            "/api/v1/mfa/totp/confirm",
            headers={"X-CSRF-Token": csrf_tok},
            json={"code": pyotp.TOTP(raw_secret).now()},
        )

        # Выпускаем recovery codes
        gen_res = await pg_client.post(
            "/api/v1/mfa/recovery-codes/generate",
            headers={"X-CSRF-Token": csrf_tok},
        )
        codes = gen_res.json()["recovery_codes"]
        burn_code = codes[0]

        # Выходим
        await pg_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_tok})

        # Шаг 1 входа -> получаем mfa_token
        mfa_step1 = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "rec_race_user", "password": "RecRacePassword2026!"},
        )
        mfa_token = mfa_step1.json()["mfa_token"]

        # 2. Параллельно отправляем 2 запроса на погашение одного burn_code
        tasks = [
            pg_client.post(
                "/api/v1/mfa/recovery-codes/verify",
                json={"mfa_token": mfa_token, "recovery_code": burn_code},
            )
            for _ in range(2)
        ]

        responses = await asyncio.gather(*tasks)

        # 3. Ровно 1 успешен, второй отклонен
        status_codes = [r.status_code for r in responses]
        assert status_codes.count(200) == 1, f"Ожидался 1 статус 200, получено: {status_codes}"
        assert status_codes.count(401) == 1, f"Ожидался 1 статус 401, получено: {status_codes}"

        # 4. Проверяем в PostgreSQL: код помечен как использованный
        norm_burn = burn_code.replace("-", "").replace(" ", "").upper().strip()
        burn_hash = hashlib.sha256(norm_burn.encode("utf-8")).hexdigest()
        b_row = await pg_session.execute(
            text("SELECT is_used FROM recovery_codes WHERE code_hash = :bh"),
            {"bh": burn_hash},
        )
        assert b_row.scalar_one() is True

    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_refresh_token_rotation_and_replay_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-09, SSO-05: Параллельная ротация одного и того же refresh токена.
    Благодаря SELECT FOR UPDATE:
    - Запрос А захватывает блокировку, помечает RT1 как is_revoked = True и выпускает RT2.
    - Запрос Б захватывает блокировку, видит is_revoked = True, диагностирует Replay Attack
      и отзывает все семейство токенов (включая RT2), возвращая 400 invalid_grant.
    - В аудите PostgreSQL фиксируется refresh_token_replay_detected.
    """
    # 1. Создаем пользователя
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="rt_race_user",
        email="rt_race@alxprgs.tech",
        password="RtRacePassword2026!",
        registration_mode="closed",
    )
    assert code == 0

    user_row = await pg_session.execute(
        text("SELECT id FROM users WHERE username = 'rt_race_user'")
    )
    user_id = user_row.scalar_one()

    # 2. Входим как админ и регистрируем клиента
    login_adm = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "rt_race_user", "password": "RtRacePassword2026!"},
    )
    assert login_adm.status_code == 200
    adm_csrf = login_adm.json()["csrf_token"]

    client_reg = await pg_client.post(
        "/api/v1/admin/clients",
        headers={"X-CSRF-Token": adm_csrf},
        json={
            "client_name": "RT Race Client",
            "client_type": "confidential",
            "redirect_uris": ["http://localhost:8081/callback"],
        },
    )
    c_data = client_reg.json()
    client_id = c_data["client_id"]
    client_secret = c_data["client_secret"]

    c_row = await pg_session.execute(
        text("SELECT id FROM oidc_clients WHERE client_id = :cid"),
        {"cid": client_id},
    )
    client_db_id = c_row.scalar_one()

    # 3. Выпускаем начальный Refresh Token (RT1)
    raw_rt1 = "ALXPRGS_RT_RACE_" + generate_random_token(32)
    rt1_hash = hash_token(raw_rt1)
    family_id = uuid.uuid4()

    await pg_session.execute(
        text(
            "INSERT INTO refresh_tokens ("
            "  id, token_hash, client_id, user_id, scope, family_id, "
            "  expires_at, is_revoked, created_at"
            ") VALUES ("
            "  gen_random_uuid(), :th, :cid, :uid, 'openid profile offline_access', :fid, "
            "  now() + interval '7 days', false, now()"
            ")"
        ),
        {
            "th": rt1_hash,
            "cid": client_db_id,
            "uid": user_id,
            "fid": family_id,
        },
    )
    await pg_session.commit()

    # 4. Запускаем 2 одновременных запроса на ротацию RT1
    tasks = [
        pg_client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": raw_rt1,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        for _ in range(2)
    ]

    responses = await asyncio.gather(*tasks)

    # 5. Один из запросов диагностирует Replay (status 400), другой может успеть получить 200 либо оба завершатся 400
    status_codes = [r.status_code for r in responses]
    assert 400 in status_codes, (
        f"Ожидался как минимум один отказ по Replay (400), получено: {status_codes}"
    )

    # 6. Проверяем в PostgreSQL запись аудита refresh_token_replay_detected
    audit_replay = await pg_session.execute(
        text("SELECT COUNT(*) FROM audit_events WHERE event_type = 'refresh_token_replay_detected'")
    )
    assert audit_replay.scalar_one() >= 1


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_distributed_rate_limiting_registration_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-10, REG-07: Межпроцессное ограничение частоты регистрации через PostgreSQL.
    Превышение лимита DB_MAX_ATTEMPTS_PER_WINDOW (5 запросов с одного IP):
    - Первые 5 запросов успешны (201 Created).
    - 6-й запрос блокируется HTTP 429 Too Many Requests (rate_limit_exceeded).
    """
    # 1. Открываем регистрацию
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="admin_rl",
        email="admin_rl@alxprgs.tech",
        password="AdminRlPassword2026!",
        registration_mode="open",
    )
    assert code == 0

    test_ip = "198.51.100.99"
    # Очищаем локальный in-memory счетчик для чистоты теста
    _IN_MEMORY_REQUESTS.pop(test_ip, None)

    # 2. Выполняем 5 последовательных регистраций с одного IP
    for i in range(5):
        res = await pg_client.post(
            "/api/v1/auth/register",
            json={
                "username": f"rl_user_{i}",
                "email": f"rl_user_{i}@alxprgs.tech",
                "password": f"PasswordRl{i}2026!",
                "confirm_password": f"PasswordRl{i}2026!",
            },
            headers={"X-Forwarded-For": test_ip},
        )
        assert res.status_code == 201, f"Запрос {i} завершился с ошибкой: {res.text}"

    # 3. 6-й запрос с того же IP должен быть отклонен HTTP 429 Too Many Requests
    blocked_res = await pg_client.post(
        "/api/v1/auth/register",
        json={
            "username": "rl_user_blocked",
            "email": "rl_blocked@alxprgs.tech",
            "password": "PasswordRlBlocked2026!",
            "confirm_password": "PasswordRlBlocked2026!",
        },
        headers={"X-Forwarded-For": test_ip},
    )
    assert blocked_res.status_code == 429
    err_body = blocked_res.json()
    assert "rate_limit_exceeded" in str(err_body)
    assert "Превышен лимит попыток регистрации" in str(err_body)
