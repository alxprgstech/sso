import httpx
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.core.rbac import ROLE_ADMIN, ROLE_USER
from app.core.security import verify_password
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_registration_closed_mode_rejected_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-05, REG-02, REG-03: При закрытом режиме (closed) прямой запрос регистрации отклоняется со статусом 403 Forbidden.
    Проверяется также факт отсутствия создания пользователя и фиксация события аудита.
    """
    # 1. Устанавливаем режим 'closed' и завершенный bootstrap
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed = true, registration_mode = 'closed' WHERE id = 1"
        )
    )
    await pg_session.commit()

    # 2. Выполняем попытку регистрации
    resp = await pg_client.post(
        "/api/v1/auth/register",
        json={
            "username": "rejected_user",
            "email": "rejected@alxprgs.tech",
            "password": "SecurePassword2026!",
            "confirm_password": "SecurePassword2026!",
        },
    )
    assert resp.status_code == 403
    assert "закрыта" in str(resp.json())

    # 3. Проверяем в PostgreSQL, что пользователь НЕ создан
    u_res = await pg_session.execute(text("SELECT id FROM users WHERE username = 'rejected_user'"))
    assert u_res.scalar_one_or_none() is None

    # 4. Проверяем фиксацию события аудита в PostgreSQL
    audit_res = await pg_session.execute(
        text(
            "SELECT event_type FROM audit_events WHERE event_type = 'registration_rejected_closed'"
        )
    )
    assert audit_res.scalar_one_or_none() is not None


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_registration_bootstrap_incomplete_rejected_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-05, REG-03, SETUP-05: До завершения первичной инициализации регистрация закрыта независимо от режима.
    """
    # 1. Устанавливаем bootstrap_completed = False, даже если registration_mode = 'open'
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed = false, registration_mode = 'open' WHERE id = 1"
        )
    )
    await pg_session.commit()

    resp = await pg_client.post(
        "/api/v1/auth/register",
        json={
            "username": "early_bird",
            "email": "early@alxprgs.tech",
            "password": "SecurePassword2026!",
            "confirm_password": "SecurePassword2026!",
        },
    )
    assert resp.status_code == 403
    assert "закрыта" in str(resp.json())


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_registration_success_open_mode_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-05, REG-01, REG-04, TEST-REG-01: Успешная регистрация в режиме 'open'.
    Проверяет:
    - Создание обычного пользователя с ролью 'user' и is_superuser=False.
    - email_verified=False в default-профиле.
    - Хеширование пароля Argon2id.
    - Отсутствие автоматической сессионной cookie (REG-04: явный последующий вход).
    - Возможность успешного входа после регистрации и отсутствие прав администратора.
    """
    # 1. Включаем открытый режим
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed = true, registration_mode = 'open' WHERE id = 1"
        )
    )
    await pg_session.commit()

    # 2. Выполняем регистрацию
    resp = await pg_client.post(
        "/api/v1/auth/register",
        json={
            "username": "charlie_reg",
            "email": "charlie@alxprgs.tech",
            "password": "CharliePassword2026!",
            "confirm_password": "CharliePassword2026!",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "ok"
    assert data["username"] == "charlie_reg"
    assert data["email"] == "charlie@alxprgs.tech"
    new_user_id = data["user_id"]

    # 3. Проверяем инвариант REG-04: cookie сессии НЕ должна устанавливаться автоматически
    assert "alx_session" not in pg_client.cookies

    # 4. Проверяем состояние созданной записи в PostgreSQL
    u_res = await pg_session.execute(
        text(
            "SELECT username, email, is_superuser, is_active, email_verified FROM users WHERE id = :uid"
        ),
        {"uid": new_user_id},
    )
    user_row = u_res.fetchone()
    assert user_row is not None
    assert user_row[0] == "charlie_reg"
    assert user_row[1] == "charlie@alxprgs.tech"
    assert user_row[2] is False  # is_superuser == False
    assert user_row[3] is True  # is_active == True
    assert user_row[4] is False  # email_verified == False в default-профиле

    # Проверяем роль user
    r_res = await pg_session.execute(
        text(
            "SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id = r.id WHERE ur.user_id = :uid"
        ),
        {"uid": new_user_id},
    )
    roles = [r[0] for r in r_res.fetchall()]
    assert ROLE_USER in roles
    assert ROLE_ADMIN not in roles

    # Проверяем хеш пароля Argon2id
    p_res = await pg_session.execute(
        text("SELECT password_hash FROM password_credentials WHERE user_id = :uid"),
        {"uid": new_user_id},
    )
    pwd_hash = p_res.scalar_one()
    assert verify_password("CharliePassword2026!", pwd_hash) is True

    # Проверяем запись события аудита user_registered в PostgreSQL
    audit_res = await pg_session.execute(
        text(
            "SELECT event_type FROM audit_events WHERE event_type = 'user_registered' AND user_id = :uid"
        ),
        {"uid": new_user_id},
    )
    assert audit_res.scalar_one_or_none() is not None

    # 5. Новый пользователь входит через /login
    login_resp = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "charlie_reg", "password": "CharliePassword2026!"},
    )
    assert login_resp.status_code == 200
    assert "csrf_token" in login_resp.json()

    # 6. Проверяем /me
    me_resp = await pg_client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "charlie_reg"
    assert me_resp.json()["roles"] == [ROLE_USER]

    # 7. Обычный пользователь не имеет доступа к админке -> 403 Forbidden
    adm_resp = await pg_client.get("/api/v1/admin/users")
    assert adm_resp.status_code == 403


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_registration_duplicate_collisions_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-05, REG-03, TEST-REG-03: Защита от перечисления пользователей при коллизиях.
    При совпадении username или email сервер возвращает нейтральный 409 Conflict без раскрытия конкретного поля.
    """
    # 1. Включаем открытый режим
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed = true, registration_mode = 'open' WHERE id = 1"
        )
    )
    await pg_session.commit()

    # Создаем первого пользователя
    r1 = await pg_client.post(
        "/api/v1/auth/register",
        json={
            "username": "existing_user",
            "email": "existing@alxprgs.tech",
            "password": "Password1234!",
            "confirm_password": "Password1234!",
        },
    )
    assert r1.status_code == 201

    # Попытка 1: тот же username, другой email -> 409 Conflict
    r_dup_uname = await pg_client.post(
        "/api/v1/auth/register",
        json={
            "username": "existing_user",
            "email": "different_email@alxprgs.tech",
            "password": "Password1234!",
            "confirm_password": "Password1234!",
        },
    )
    assert r_dup_uname.status_code == 409
    err_uname = r_dup_uname.json()["detail"]
    assert err_uname["error"] == "user_already_exists"
    assert "уже существует" in err_uname["detail"]
    # Проверяем отсутствие утечки
    assert "username" not in str(err_uname).lower()
    assert "логин" not in str(err_uname).lower()

    # Попытка 2: другой username, тот же email -> 409 Conflict
    r_dup_email = await pg_client.post(
        "/api/v1/auth/register",
        json={
            "username": "different_user",
            "email": "existing@alxprgs.tech",
            "password": "Password1234!",
            "confirm_password": "Password1234!",
        },
    )
    assert r_dup_email.status_code == 409
    err_email = r_dup_email.json()["detail"]
    assert err_email == err_uname  # Ответы абсолютно идентичны!

    # Попытка 3: email с другим регистром -> 409 Conflict
    r_dup_case = await pg_client.post(
        "/api/v1/auth/register",
        json={
            "username": "another_user",
            "email": "ExIsTiNg@alxprgs.tech",
            "password": "Password1234!",
            "confirm_password": "Password1234!",
        },
    )
    assert r_dup_case.status_code == 409


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_admin_toggle_registration_mode_with_reauth_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-05, REG-02, REG-05, TEST-REG-02: Административное управление режимом регистрации с re-auth паролем.
    - Проверка текущего статуса /api/v1/admin/system/status.
    - Отклонение без пароля или с неверным паролем.
    - Успешное переключение в 'open' и аудит.
    - Проверка, что после смены режима саморегистрация сразу работает.
    """
    # 1. Создаем администратора через bootstrap
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="admin_toggler",
        email="admin_toggler@alxprgs.tech",
        password="MasterAdminPassword123!",
        registration_mode="closed",
    )
    assert code == 0

    # 2. Входим администратором
    login_res = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "admin_toggler", "password": "MasterAdminPassword123!"},
    )
    assert login_res.status_code == 200
    csrf_token = login_res.json()["csrf_token"]

    # 3. Проверяем системный статус
    st_res = await pg_client.get("/api/v1/admin/system/status")
    assert st_res.status_code == 200
    assert st_res.json()["registration_mode"] == "closed"
    assert st_res.json()["bootstrap_completed"] is True

    # 4. Попытка переключить режим с неверным паролем -> 401 Unauthorized
    fail_toggle = await pg_client.post(
        "/api/v1/admin/system/registration-mode",
        headers={"X-CSRF-Token": csrf_token},
        json={"mode": "open", "current_admin_password": "WrongPassword!"},
    )
    assert fail_toggle.status_code == 401

    # Режим в БД не изменился
    cfg_check = await pg_session.execute(
        text("SELECT registration_mode FROM system_configuration WHERE id = 1")
    )
    assert cfg_check.scalar_one() == "closed"

    # 5. Успешное переключение режима с корректным паролем
    ok_toggle = await pg_client.post(
        "/api/v1/admin/system/registration-mode",
        headers={"X-CSRF-Token": csrf_token},
        json={"mode": "open", "current_admin_password": "MasterAdminPassword123!"},
    )
    assert ok_toggle.status_code == 200
    assert ok_toggle.json()["registration_mode"] == "open"

    # Режим в БД изменился на 'open'
    cfg_open = await pg_session.execute(
        text("SELECT registration_mode FROM system_configuration WHERE id = 1")
    )
    assert cfg_open.scalar_one() == "open"

    # Проверяем аудит в PostgreSQL
    audit_toggle = await pg_session.execute(
        text("SELECT event_type FROM audit_events WHERE event_type = 'registration_mode_changed'")
    )
    assert audit_toggle.scalar_one_or_none() is not None

    # 6. Проверяем, что capabilities теперь возвращает registration_mode = "open"
    cap_res = await pg_client.get("/api/v1/auth/capabilities")
    assert cap_res.status_code == 200
    assert cap_res.json()["registration_mode"] == "open"
