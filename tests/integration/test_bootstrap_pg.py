import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from app.core.rbac import ROLE_ADMIN
from app.core.security import verify_password
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_bootstrap_fresh_db_postgres(pg_session: AsyncSession):
    """
    QA-03, SETUP-03..SETUP-05: Первичная инициализация на реальной PostgreSQL.
    Создает первого администратора, назначает роли, фиксирует bootstrap_completed=True.
    """
    # 1. На чистой базе сбрасываем bootstrap_completed = false
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed = false, bootstrap_completed_at = NULL WHERE id = 1"
        )
    )
    await pg_session.commit()

    # 2. Выполняем bootstrap первого администратора
    code, msg = await execute_bootstrap(
        session=pg_session,
        username="superadmin",
        email="superadmin@alxprgs.tech",
        password="AdminSecurePassword2026!",
        registration_mode="closed",
    )
    assert code == 0
    assert "успешно создан" in msg or "[SUCCESS]" in msg

    # 3. Проверяем состояние в PostgreSQL
    # Проверяем запись в users
    u_res = await pg_session.execute(
        text(
            "SELECT id, username, email, is_superuser, is_active, email_verified FROM users WHERE username = 'superadmin'"
        )
    )
    user_row = u_res.fetchone()
    assert user_row is not None
    user_id = user_row[0]
    assert user_row[1] == "superadmin"
    assert user_row[2] == "superadmin@alxprgs.tech"
    assert user_row[3] is True  # is_superuser
    assert user_row[4] is True  # is_active
    assert user_row[5] is False  # email_verified=False в default-профиле (SETUP-10)

    # Проверяем хеш пароля (Argon2id)
    p_res = await pg_session.execute(
        text("SELECT password_hash FROM password_credentials WHERE user_id = :uid"),
        {"uid": user_id},
    )
    pwd_hash = p_res.scalar_one()
    assert verify_password("AdminSecurePassword2026!", pwd_hash) is True
    assert verify_password("WrongPassword!", pwd_hash) is False

    # Проверяем роль admin
    r_res = await pg_session.execute(
        text(
            "SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id = r.id WHERE ur.user_id = :uid"
        ),
        {"uid": user_id},
    )
    roles = [r[0] for r in r_res.fetchall()]
    assert ROLE_ADMIN in roles

    # Проверяем system_configuration
    cfg_res = await pg_session.execute(
        text("SELECT bootstrap_completed, registration_mode FROM system_configuration WHERE id = 1")
    )
    cfg_row = cfg_res.fetchone()
    assert cfg_row[0] is True
    assert cfg_row[1] == "closed"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_bootstrap_idempotent_repeat_run_postgres(pg_session: AsyncSession):
    """
    QA-04, SETUP-06: Повторный запуск мастера безопасен и идемпотентен.
    Не изменяет существующего администратора, пароль и настройки.
    """
    # 1. Первый запуск
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed = false, bootstrap_completed_at = NULL WHERE id = 1"
        )
    )
    await pg_session.commit()

    code1, _ = await execute_bootstrap(
        session=pg_session,
        username="admin1",
        email="admin1@alxprgs.tech",
        password="FirstPassword123!",
        registration_mode="closed",
    )
    assert code1 == 0

    # Получаем исходный хеш пароля
    p_res1 = await pg_session.execute(
        text(
            "SELECT pc.password_hash FROM password_credentials pc JOIN users u ON u.id = pc.user_id WHERE u.username = 'admin1'"
        )
    )
    hash_before = p_res1.scalar_one()

    # 2. Повторный запуск с другими учетными данными
    code2, msg2 = await execute_bootstrap(
        session=pg_session,
        username="admin2_attempt",
        email="admin2@alxprgs.tech",
        password="DifferentPassword456!",
        registration_mode="open",
    )
    assert code2 == 0
    assert "уже выполнена ранее" in msg2
    assert "идемпотентно" in msg2

    # 3. Проверяем, что второй пользователь НЕ создан
    u2_res = await pg_session.execute(
        text("SELECT id FROM users WHERE username = 'admin2_attempt'")
    )
    assert u2_res.scalar_one_or_none() is None

    # 4. Проверяем, что пароль первого администратора НЕ изменился
    p_res2 = await pg_session.execute(
        text(
            "SELECT pc.password_hash FROM password_credentials pc JOIN users u ON u.id = pc.user_id WHERE u.username = 'admin1'"
        )
    )
    hash_after = p_res2.scalar_one()
    assert hash_before == hash_after

    # 5. Режим регистрации остался closed
    cfg_res = await pg_session.execute(
        text("SELECT registration_mode FROM system_configuration WHERE id = 1")
    )
    assert cfg_res.scalar_one() == "closed"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_bootstrap_refuses_to_elevate_existing_user_postgres(pg_session: AsyncSession):
    """
    QA-04, SETUP-06: Запрет автоматического повышения прав существующего обычного пользователя.
    """
    # 1. Создаем обычного пользователя без прав администратора
    await pg_session.execute(
        text(
            "INSERT INTO users (id, username, email, is_active, is_superuser, email_verified) "
            "VALUES (gen_random_uuid(), 'normal_user', 'normal@alxprgs.tech', true, false, false)"
        )
    )
    # Сбрасываем флаг bootstrap_completed для эмуляции незавершенной настройки
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed = false, bootstrap_completed_at = NULL WHERE id = 1"
        )
    )
    await pg_session.commit()

    # 2. Пытаемся запустить мастер с совпадающим логином
    code, msg = await execute_bootstrap(
        session=pg_session,
        username="normal_user",
        email="different@alxprgs.tech",
        password="SomePassword123!",
        registration_mode="closed",
    )
    assert code == 1
    assert "Автоматическое повышение прав существующих пользователей запрещено" in msg

    # 3. Проверяем, что пользователь остался обычным (is_superuser = false)
    res = await pg_session.execute(
        text("SELECT is_superuser FROM users WHERE username = 'normal_user'")
    )
    assert res.scalar_one() is False


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "password, message",
    [
        ("short", "от 15 до 128"),
        ("EightChars12!", "от 15 до 128"),
        ("X" * 129, "от 15 до 128"),
        ("password123456789", "слишком распространён"),
    ],
)
async def test_bootstrap_password_validation_postgres(
    pg_session: AsyncSession, password: str, message: str
):
    """
    QA-04, SETUP-03: The common 15–128 policy rejects invalid bootstrap input before writes.
    """
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed = false, bootstrap_completed_at = NULL WHERE id = 1"
        )
    )
    await pg_session.commit()

    code, msg = await execute_bootstrap(
        session=pg_session,
        username="admin_short",
        email="admin_short@alxprgs.tech",
        password=password,
        registration_mode="closed",
    )
    assert code == 1
    assert message in msg
    assert (
        await pg_session.scalar(text("SELECT count(*) FROM users WHERE username = 'admin_short'"))
        == 0
    )
    assert (
        await pg_session.scalar(
            text("SELECT bootstrap_completed FROM system_configuration WHERE id = 1")
        )
        is False
    )
