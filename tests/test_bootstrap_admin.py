import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath("backend"))

from app.cli.bootstrap_admin import bootstrap_admin, execute_bootstrap
from app.core.rbac import ROLE_ADMIN, ROLE_USER
from app.models.system import SystemConfiguration
from app.models.user import PasswordCredential, Role, User, UserRole


@pytest.mark.asyncio
async def test_bootstrap_fresh_success():
    """SETUP-03..SETUP-05, SETUP-07, SETUP-10: Первичный запуск на чистой БД."""
    mock_session = AsyncMock()

    # Сначала проверяем SystemConfiguration
    config = SystemConfiguration(
        id=1,
        bootstrap_completed=False,
        registration_mode="closed",
    )
    admin_role = Role(id=uuid.uuid4(), name=ROLE_ADMIN, description="Admin")
    user_role = Role(id=uuid.uuid4(), name=ROLE_USER, description="User")

    # execute returns:
    # 1. config check -> config
    # 2. existing admins -> []
    # 3. existing user -> None
    # 4. role admin -> admin_role
    # 5. role user -> user_role
    # 6. select Role admin -> admin_role
    res_config = MagicMock()
    res_config.scalar_one_or_none.return_value = config

    res_no_admins = MagicMock()
    res_no_admins.scalars.return_value.all.return_value = []

    res_no_existing_user = MagicMock()
    res_no_existing_user.scalar_one_or_none.return_value = None

    res_role_admin = MagicMock()
    res_role_admin.scalar_one_or_none.return_value = admin_role

    res_role_user = MagicMock()
    res_role_user.scalar_one_or_none.return_value = user_role

    res_select_admin = MagicMock()
    res_select_admin.scalar_one.return_value = admin_role

    mock_session.execute.side_effect = [
        res_config,
        res_no_admins,
        res_no_existing_user,
        res_role_admin,
        res_role_user,
        res_select_admin,
    ]

    added_objects = []
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    code, msg = await execute_bootstrap(
        session=mock_session,
        username="superadmin",
        email="superadmin@alxprgs.tech",
        password="ValidPassword123!",
        registration_mode="closed",
    )

    assert code == 0
    assert "успешно завершена" in msg
    assert config.bootstrap_completed is True
    assert config.registration_mode == "closed"

    # Проверяем созданного администратора
    created_user = next((obj for obj in added_objects if isinstance(obj, User)), None)
    assert created_user is not None
    assert created_user.username == "superadmin"
    assert created_user.email == "superadmin@alxprgs.tech"
    assert created_user.is_superuser is True
    assert created_user.is_active is True
    assert created_user.email_verified is False  # SETUP-10: в default-профиле false

    # Проверяем хеш пароля
    created_cred = next((obj for obj in added_objects if isinstance(obj, PasswordCredential)), None)
    assert created_cred is not None

    # Проверяем назначение роли
    created_ur = next((obj for obj in added_objects if isinstance(obj, UserRole)), None)
    assert created_ur is not None
    assert created_ur.role_id == admin_role.id


@pytest.mark.asyncio
async def test_bootstrap_idempotent_when_already_completed():
    """SETUP-05, SETUP-06: Повторный запуск при завершённом bootstrap безопасен и не меняет систему."""
    mock_session = AsyncMock()

    config = SystemConfiguration(
        id=1,
        bootstrap_completed=True,
        registration_mode="closed",
    )
    res_config = MagicMock()
    res_config.scalar_one_or_none.return_value = config

    res_admins = MagicMock()
    res_admins.scalars.return_value.all.return_value = [
        User(username="existing_admin", is_superuser=True)
    ]

    mock_session.execute.side_effect = [res_config, res_admins]

    code, msg = await execute_bootstrap(
        session=mock_session,
        username="another_admin",
        email="another@alxprgs.tech",
        password="ValidPassword123!",
        registration_mode="open",
    )

    assert code == 0
    assert "уже выполнена ранее" in msg
    assert "идемпотентно" in msg
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_refuses_to_elevate_existing_user():
    """SETUP-06: Отказ в автоматическом повышении прав существующего обычного пользователя."""
    mock_session = AsyncMock()

    config = SystemConfiguration(
        id=1,
        bootstrap_completed=False,
        registration_mode="closed",
    )
    res_config = MagicMock()
    res_config.scalar_one_or_none.return_value = config

    res_no_admins = MagicMock()
    res_no_admins.scalars.return_value.all.return_value = []

    # Существующий обычный пользователь с тем же логином
    existing_user = User(
        id=uuid.uuid4(),
        username="regular_bob",
        email="bob@example.com",
        is_superuser=False,
    )
    res_existing_user = MagicMock()
    res_existing_user.scalar_one_or_none.return_value = existing_user

    mock_session.execute.side_effect = [
        res_config,
        res_no_admins,
        res_existing_user,
    ]

    code, msg = await execute_bootstrap(
        session=mock_session,
        username="regular_bob",
        email="bob@example.com",
        password="ValidPassword123!",
        registration_mode="closed",
    )

    assert code == 1
    assert "уже существует" in msg
    assert "SETUP-06" in msg
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_rejects_short_password():
    """SETUP-03: Пароль менее 8 символов отклоняется."""
    mock_session = AsyncMock()

    config = SystemConfiguration(
        id=1,
        bootstrap_completed=False,
        registration_mode="closed",
    )
    res_config = MagicMock()
    res_config.scalar_one_or_none.return_value = config

    res_no_admins = MagicMock()
    res_no_admins.scalars.return_value.all.return_value = []

    res_no_existing_user = MagicMock()
    res_no_existing_user.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [
        res_config,
        res_no_admins,
        res_no_existing_user,
    ]

    code, msg = await execute_bootstrap(
        session=mock_session,
        username="admin",
        email="admin@alxprgs.tech",
        password="short",
        registration_mode="closed",
    )

    assert code == 1
    assert "не менее 8 символов" in msg


@pytest.mark.asyncio
async def test_bootstrap_non_interactive_without_password_fails():
    """SETUP-09: В неинтерактивном режиме без ADMIN_INITIAL_PASSWORD возвращается понятная ошибка и exit code 1."""
    mock_session = AsyncMock()
    config = SystemConfiguration(id=1, bootstrap_completed=False)
    res_config = MagicMock()
    res_config.scalar_one_or_none.return_value = config
    res_admins = MagicMock()
    res_admins.scalars.return_value.all.return_value = []
    mock_session.execute.side_effect = [res_config, res_admins]

    with patch("sys.stdin.isatty", return_value=False), patch.dict(os.environ, {}, clear=True):
        code = await bootstrap_admin(session=mock_session)
        assert code == 1


@pytest.mark.asyncio
async def test_bootstrap_open_mode_selection():
    """SETUP-03: Выбор открытого режима регистрации при первичной настройке."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    config = SystemConfiguration(id=1, bootstrap_completed=False, registration_mode="closed")
    admin_role = Role(id=uuid.uuid4(), name=ROLE_ADMIN, description="Admin")
    user_role = Role(id=uuid.uuid4(), name=ROLE_USER, description="User")

    res_config = MagicMock()
    res_config.scalar_one_or_none.return_value = config
    res_no_admins = MagicMock()
    res_no_admins.scalars.return_value.all.return_value = []
    res_no_existing_user = MagicMock()
    res_no_existing_user.scalar_one_or_none.return_value = None
    res_role_admin = MagicMock()
    res_role_admin.scalar_one_or_none.return_value = admin_role
    res_role_user = MagicMock()
    res_role_user.scalar_one_or_none.return_value = user_role
    res_select_admin = MagicMock()
    res_select_admin.scalar_one.return_value = admin_role

    mock_session.execute.side_effect = [
        res_config,
        res_no_admins,
        res_no_existing_user,
        res_role_admin,
        res_role_user,
        res_select_admin,
    ]

    code, msg = await execute_bootstrap(
        session=mock_session,
        username="admin_open",
        email="admin_open@alxprgs.tech",
        password="ValidPassword123!",
        registration_mode="open",
    )

    assert code == 0
    assert config.registration_mode == "open"


@pytest.mark.asyncio
async def test_bootstrap_non_interactive_with_env_vars_success():
    """SETUP-03, SETUP-09: В неинтерактивном режиме с корректными env-переменными инициализация успешна."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    config = SystemConfiguration(id=1, bootstrap_completed=False, registration_mode="closed")
    admin_role = Role(id=uuid.uuid4(), name=ROLE_ADMIN, description="Admin")
    user_role = Role(id=uuid.uuid4(), name=ROLE_USER, description="User")

    res_config = MagicMock(scalar_one_or_none=MagicMock(return_value=config))
    res_no_admins = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    )
    res_no_existing_user = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    res_role_admin = MagicMock(scalar_one_or_none=MagicMock(return_value=admin_role))
    res_role_user = MagicMock(scalar_one_or_none=MagicMock(return_value=user_role))
    res_select_admin = MagicMock(scalar_one=MagicMock(return_value=admin_role))

    mock_session.execute.side_effect = [
        res_config,
        res_no_admins,
        res_config,
        res_no_admins,
        res_no_existing_user,
        res_role_admin,
        res_role_user,
        res_select_admin,
    ]

    env_vars = {
        "ADMIN_INITIAL_USERNAME": "env_admin",
        "ADMIN_INITIAL_EMAIL": "env_admin@alxprgs.tech",
        "ADMIN_INITIAL_PASSWORD": "EnvPassword123!",
        "REGISTRATION_MODE": "open",
    }

    with (
        patch("sys.stdin.isatty", return_value=False),
        patch.dict(os.environ, env_vars, clear=True),
    ):
        code = await bootstrap_admin(session=mock_session)
        assert code == 0
        assert config.bootstrap_completed is True
        assert config.registration_mode == "open"
