import httpx
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.core.rbac import ROLE_ADMIN, ROLE_USER
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_full_auth_login_me_logout_pg(pg_session: AsyncSession, pg_client: httpx.AsyncClient):
    """
    QA-06, USR-01, ARCH-03..05: Полный цикл входа, работы с сессией и выхода на PostgreSQL.
    Проверяет установку HttpOnly cookie, заголовок CSRF, эндпоинт /me и завершение сессии.
    """
    # 1. Создаем пользователя через bootstrap
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="alice",
        email="alice@alxprgs.tech",
        password="AliceSecurePassword123!",
        registration_mode="closed",
    )
    assert code == 0

    # 2. Неверный пароль -> 401 invalid_credentials
    r_fail = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "WrongPassword123!"},
    )
    assert r_fail.status_code == 401
    assert r_fail.json()["error"] == "invalid_credentials"

    # Проверяем аудит неудачного входа в PostgreSQL
    audit_fail = await pg_session.execute(
        text("SELECT event_type FROM audit_events WHERE event_type = 'login_failed'")
    )
    assert audit_fail.scalar_one_or_none() is not None

    # 3. Успешный вход -> 200 OK + cookie + CSRF токен
    r_login = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "AliceSecurePassword123!"},
    )
    assert r_login.status_code == 200
    login_data = r_login.json()
    assert login_data["status"] == "ok"
    assert login_data["user"]["username"] == "alice"
    assert "csrf_token" in login_data
    csrf_token = login_data["csrf_token"]
    assert len(csrf_token) == 64

    # Проверяем атрибуты cookie
    session_cookie = pg_client.cookies.get("alx_session")
    assert session_cookie is not None
    # Проверяем наличие сессии в PostgreSQL
    s_res = await pg_session.execute(text("SELECT id FROM sessions"))
    active_sessions = s_res.fetchall()
    assert len(active_sessions) == 1

    # 4. Обращение к /api/v1/auth/me с установленной cookie
    r_me = await pg_client.get("/api/v1/auth/me")
    assert r_me.status_code == 200
    me_data = r_me.json()
    assert me_data["username"] == "alice"
    assert me_data["email"] == "alice@alxprgs.tech"
    assert ROLE_ADMIN in me_data["roles"]

    # 5. Выход /api/v1/auth/logout (мутирующий запрос требует CSRF)
    # 5.1 Без CSRF токена -> 403 Forbidden
    r_logout_no_csrf = await pg_client.post("/api/v1/auth/logout")
    assert r_logout_no_csrf.status_code == 403
    assert "csrf_missing" in str(r_logout_no_csrf.json())

    # 5.1.b С неверным CSRF -> 403 Forbidden
    r_logout_bad_csrf = await pg_client.post(
        "/api/v1/auth/logout",
        headers={
            "X-CSRF-Token": "wrong_csrf_token_value_00000000000000000000000000000000000000000000"
        },
    )
    assert r_logout_bad_csrf.status_code == 403
    assert "csrf_invalid" in str(r_logout_bad_csrf.json())

    # 5.2 С валидным CSRF токеном -> 200 OK
    r_logout = await pg_client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert r_logout.status_code == 200
    assert r_logout.json()["status"] == "ok"

    # 6. Проверяем, что сессия отозвана в PostgreSQL (удалена из таблицы)
    s_revoked = await pg_session.execute(text("SELECT count(*) FROM sessions"))
    assert s_revoked.scalar_one() == 0

    # 7. Последующий запрос к /api/v1/auth/me -> 401
    r_me_after = await pg_client.get("/api/v1/auth/me")
    assert r_me_after.status_code == 401


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_change_password_revokes_other_sessions_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-06, USR-02: Смена пароля отзывает все остальные активные сессии пользователя.
    """
    # 1. Создаем пользователя
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="bob_pwd",
        email="bob_pwd@alxprgs.tech",
        password="OriginalPassword123!",
        registration_mode="closed",
    )
    assert code == 0

    # 2. Логин в Сессии 1
    r_login1 = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "bob_pwd", "password": "OriginalPassword123!"},
    )
    assert r_login1.status_code == 200
    token1 = r_login1.json()["csrf_token"]
    cookie1 = pg_client.cookies.get("alx_session")

    # 3. Эмулируем вторую сессию для того же пользователя
    # Создаем независимый клиент pg_client2
    transport = httpx.ASGITransport(app=pg_client._transport.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client2:
        r_login2 = await client2.post(
            "/api/v1/auth/login",
            json={"username": "bob_pwd", "password": "OriginalPassword123!"},
        )
        assert r_login2.status_code == 200
        cookie2 = client2.cookies.get("alx_session")
        assert cookie1 != cookie2

        # В базе 2 активные сессии
        cnt_res = await pg_session.execute(text("SELECT count(*) FROM sessions"))
        assert cnt_res.scalar_one() == 2

        # 4. В Сессии 1 меняем пароль
        r_chg = await pg_client.post(
            "/api/v1/auth/change-password",
            headers={"X-CSRF-Token": token1},
            json={
                "current_password": "OriginalPassword123!",
                "new_password": "NewSecretPassword2026!",
            },
        )
        assert r_chg.status_code == 200
        assert r_chg.json()["status"] == "ok"

        # 5. Проверяем Сессию 2 -> теперь недействительна (401)
        r_client2_me = await client2.get("/api/v1/auth/me")
        assert r_client2_me.status_code == 401

        # 6. Сессия 1 по-прежнему активна
        r_client1_me = await pg_client.get("/api/v1/auth/me")
        assert r_client1_me.status_code == 200

        # 7. Вход со старым паролем не работает
        r_old_login = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "bob_pwd", "password": "OriginalPassword123!"},
        )
        assert r_old_login.status_code == 401

        # 8. Вход с новым паролем работает
        r_new_login = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "bob_pwd", "password": "NewSecretPassword2026!"},
        )
        assert r_new_login.status_code == 200


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_admin_rbac_and_last_admin_protection_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-06, USR-03, USR-08: Серверный RBAC и защита последнего администратора на PostgreSQL.
    """
    # 1. Создаем первого администратора через bootstrap
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="the_only_admin",
        email="admin@alxprgs.tech",
        password="AdminPassword123!",
        registration_mode="closed",
    )
    assert code == 0

    # 2. Логинимся под администратором
    r_adm_login = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "the_only_admin", "password": "AdminPassword123!"},
    )
    adm_csrf = r_adm_login.json()["csrf_token"]
    admin_id = r_adm_login.json()["user"]["id"]

    # 3. Администратор имеет доступ к /api/v1/admin/users
    r_users = await pg_client.get("/api/v1/admin/users")
    assert r_users.status_code == 200
    assert len(r_users.json()) >= 1

    # 4. Администратор создает обычного пользователя
    r_create = await pg_client.post(
        "/api/v1/admin/users",
        headers={"X-CSRF-Token": adm_csrf},
        json={
            "username": "regular_user_1",
            "email": "regular1@alxprgs.tech",
            "password": "UserPassword123!",
            "roles": [ROLE_USER],
            "is_superuser": False,
        },
    )
    assert r_create.status_code == 201
    normal_id = r_create.json()["id"]

    # 5. Защита USR-08: Попытка заблокировать последнего администратора отклоняется
    r_block_admin = await pg_client.patch(
        f"/api/v1/admin/users/{admin_id}",
        headers={"X-CSRF-Token": adm_csrf},
        json={"is_active": False},
    )
    assert r_block_admin.status_code == 403
    assert "последнего" in str(r_block_admin.json())

    # Попытка снять права суперпользователя с последнего администратора
    r_demote_admin = await pg_client.patch(
        f"/api/v1/admin/users/{admin_id}",
        headers={"X-CSRF-Token": adm_csrf},
        json={"is_superuser": False},
    )
    assert r_demote_admin.status_code == 403

    # 6. Блокировка обычного пользователя разрешена
    r_block_user = await pg_client.patch(
        f"/api/v1/admin/users/{normal_id}",
        headers={"X-CSRF-Token": adm_csrf},
        json={"is_active": False},
    )
    assert r_block_user.status_code == 200
    assert r_block_user.json()["is_active"] is False

    # 7. Обычный пользователь не может получить доступ к эндпоинтам админки (серверный RBAC)
    # Входим обычным пользователем (предварительно активируем его)
    await pg_client.patch(
        f"/api/v1/admin/users/{normal_id}",
        headers={"X-CSRF-Token": adm_csrf},
        json={"is_active": True},
    )

    transport = httpx.ASGITransport(app=pg_client._transport.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as user_client:
        r_user_login = await user_client.post(
            "/api/v1/auth/login",
            json={"username": "regular_user_1", "password": "UserPassword123!"},
        )
        assert r_user_login.status_code == 200

        # Попытка доступа к /api/v1/admin/users -> 403 Forbidden
        r_denied = await user_client.get("/api/v1/admin/users")
        assert r_denied.status_code == 403
        assert r_denied.json()["error"] == "forbidden"
