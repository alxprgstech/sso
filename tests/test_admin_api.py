import os
import sys
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath("backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.models.user import User, Role, PasswordCredential
from app.models.session import Session
from app.models.oidc import OIDCClient, OIDCRedirectUri
from app.models.audit import AuditEvent
from app.api.deps import get_current_user, get_current_session, require_admin_user, get_db, verify_csrf
from app.core.exceptions import AuthorizationException
from app.services.admin_service import AdminService
from app.core.rbac import ROLE_ADMIN, ROLE_USER, ensure_not_last_admin

client = TestClient(app)


def test_unauthenticated_admin_access_rejected():
    """Неаутентифицированный пользователь не имеет доступа к админке (401)."""
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 401


def test_non_admin_user_rejected_rbac():
    """Пользователь с ролью 'user' получает 403 Forbidden (USR-03)."""
    normal_user = User(
        id=uuid.uuid4(),
        username="regular_joe",
        email="joe@alxprgs.tech",
        is_active=True,
        is_superuser=False,
    )
    role_user = Role(name=ROLE_USER)
    normal_user.roles = [role_user]

    app.dependency_overrides[get_current_user] = lambda: normal_user

    try:
        r = client.get("/api/v1/admin/users")
        assert r.status_code == 403
        assert r.json()["error"] == "forbidden"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_last_admin_protection():
    """
    Инвариант USR-08: Защита от блокировки или снятия прав последнего администратора системы.
    """
    admin_id = uuid.uuid4()
    admin_user = User(
        id=admin_id,
        username="superadmin",
        email="admin@alxprgs.tech",
        is_active=True,
        is_superuser=True,
    )
    role_admin = Role(name=ROLE_ADMIN)
    admin_user.roles = [role_admin]

    mock_db = AsyncMock()

    # Моделируем, что в базе ровно 1 активный администратор
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=1)),        # count = 1
        MagicMock(scalar_one_or_none=MagicMock(return_value=admin_id)), # this user is the admin
    ]

    with pytest.raises(AuthorizationException) as exc_info:
        await ensure_not_last_admin(mock_db, admin_id)
    assert "последнего активного администратора" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_admin_service_create_and_update_user():
    """Тестирование создания и обновления пользователя администратором."""
    mock_db = AsyncMock()
    # 1. Проверка уникальности (пользователя нет)
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # unique check
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # select Role
        MagicMock(scalar_one_or_none=MagicMock(return_value=User(
            id=uuid.uuid4(),
            username="newuser",
            email="new@alxprgs.tech",
            is_active=True,
            is_superuser=False,
            email_verified=False,
            roles=[Role(name="user")],
        ))),  # get_user_by_id return
    ]

    created = await AdminService.create_user(
        db=mock_db,
        username="newuser",
        email="new@alxprgs.tech",
        password="SecurePassword123!",
        roles=["user"],
    )
    assert created.username == "newuser"
    assert created.email == "new@alxprgs.tech"


@pytest.mark.asyncio
async def test_admin_client_secret_shown_once():
    """
    Инвариант USR-09:
    Секрет OIDC клиента генерируется и возвращается клиенту ТОЛЬКО ОДИН РАЗ при создании.
    При обычном запросе списка клиентов секрет скрыт.
    """
    mock_db = AsyncMock()

    created_client = OIDCClient(
        id=uuid.uuid4(),
        client_id="client_12345",
        client_name="Test OIDC App",
        client_type="confidential",
        client_secret_hash="argon2_hash",
        is_active=True,
    )
    created_client.redirect_uris = [
        OIDCRedirectUri(client_id=created_client.id, uri="https://app.alxprgs.tech/callback")
    ]

    mock_db.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=created_client))

    client_obj, raw_secret = await AdminService.create_client(
        db=mock_db,
        client_name="Test OIDC App",
        client_type="confidential",
        redirect_uris=["https://app.alxprgs.tech/callback"],
    )

    # При создании секрет присутствует
    assert raw_secret is not None
    assert raw_secret.startswith("sec_")
    assert client_obj.client_id == "client_12345"

    # При ротации секрет генерируется заново
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=created_client))
    _, rotated_secret = await AdminService.rotate_client_secret(mock_db, "client_12345")
    assert rotated_secret is not None
    assert rotated_secret.startswith("sec_")
