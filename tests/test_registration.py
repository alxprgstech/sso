import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.legal import REQUIRED_DOCUMENTS

sys.path.insert(0, os.path.abspath("backend"))

from app.api.deps import get_current_user, get_db
from app.config import get_settings
from app.core.rbac import ROLE_USER
from app.core.security import hash_password
from app.main import app
from app.models.system import SystemConfiguration
from app.models.user import PasswordCredential, Role, User
from app.services.auth_service import AuthService
from app.services.system_service import SystemService
from fastapi import HTTPException
from fastapi.testclient import TestClient

client = TestClient(app)
settings = get_settings()


def test_registration_when_closed_rejected():
    """REG-02, REG-03: При closed-режиме прямой запрос регистрации запрещен сервером (403)."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    config = SystemConfiguration(id=1, bootstrap_completed=True, registration_mode="closed")
    mock_result.scalar_one_or_none.return_value = config
    mock_db.execute.return_value = mock_result

    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    try:
        res = client.post(
            "/api/v1/auth/register",
            json={
                "terms_accepted": True,
                "data_processing_consent": True,
                "legal_versions": REQUIRED_DOCUMENTS,
                "username": "newuser",
                "email": "newuser@alxprgs.tech",
                "password": "ValidPassword123!",
                "confirm_password": "ValidPassword123!",
            },
        )
        assert res.status_code == 403
        assert "закрыта" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_registration_when_bootstrap_incomplete_rejected():
    """REG-03: До завершения первичной инициализации регистрация закрыта независимо от режима."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    # bootstrap_completed = False!
    config = SystemConfiguration(id=1, bootstrap_completed=False, registration_mode="open")
    mock_result.scalar_one_or_none.return_value = config
    mock_db.execute.return_value = mock_result

    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    try:
        res = client.post(
            "/api/v1/auth/register",
            json={
                "terms_accepted": True,
                "data_processing_consent": True,
                "legal_versions": REQUIRED_DOCUMENTS,
                "username": "earlyuser",
                "email": "early@alxprgs.tech",
                "password": "ValidPassword123!",
                "confirm_password": "ValidPassword123!",
            },
        )
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_registration_success_open_mode(monkeypatch: pytest.MonkeyPatch):
    """REG-01, REG-04: API возвращает заявку без user_id и без сессии."""
    mock_db = AsyncMock()
    pending = MagicMock(
        id=uuid.uuid4(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        request_details={"ip": "127.0.0.1"},
    )

    async def fake_register(**kwargs):
        assert kwargs["email"] == "valid_user@alxprgs.tech"
        return pending

    monkeypatch.setattr(AuthService, "register_user", fake_register)

    config = SystemConfiguration(id=1, bootstrap_completed=True, registration_mode="open")
    role_user = Role(name=ROLE_USER, description="Standard User")

    # Последовательность запросов:
    # 1. get_registration_mode (SystemConfiguration)
    # 2. check_registration_rate_limit count
    # 3. collision check (User query -> None)
    # 4. get Role user
    # 5. refresh
    res_cfg = MagicMock(scalar_one_or_none=MagicMock(return_value=config))
    res_coll = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    res_role = MagicMock(scalar_one_or_none=MagicMock(return_value=role_user))

    mock_db.execute.side_effect = [
        res_cfg,
        MagicMock(scalar_one=MagicMock(return_value=datetime.now(timezone.utc))),
        MagicMock(scalar_one=MagicMock(return_value=1)),
        res_coll,
        res_role,
    ]

    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    try:
        res = client.post(
            "/api/v1/auth/register",
            json={
                "terms_accepted": True,
                "data_processing_consent": True,
                "legal_versions": REQUIRED_DOCUMENTS,
                "username": "valid_user",
                "email": "valid_user@alxprgs.tech",
                "password": "SecurePassword123!",
                "confirm_password": "SecurePassword123!",
            },
        )
        assert res.status_code == 202
        data = res.json()
        assert data["status"] == "verification_pending"
        assert data["challenge_id"] == str(pending.id)
        assert "user_id" not in data
        mock_db.add.assert_not_called()
        # Сессионный cookie НЕ должен выдаваться (REG-01)
        assert "__Host-alx_session" not in res.cookies
        assert "alx_session" not in res.cookies
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_registration_rejects_privileged_fields():
    """REG-04: Попытка передать роли или флаги суперпользователя отклоняется валидатором (422)."""
    for forbidden_field in [
        {"is_superuser": True},
        {"roles": ["admin"]},
        {"is_active": False},
        {"email_verified": True},
    ]:
        body = {
            "terms_accepted": True,
            "data_processing_consent": True,
            "legal_versions": REQUIRED_DOCUMENTS,
            "username": "hacker",
            "email": "hacker@alxprgs.tech",
            "password": "Password123!",
            "confirm_password": "Password123!",
            **forbidden_field,
        }
        res = client.post("/api/v1/auth/register", json=body)
        assert res.status_code == 422, f"Failed for forbidden field: {forbidden_field}"


def test_registration_validation_errors():
    """REG-05: Валидация паролей, длины и формата email."""
    # 1. Несовпадение паролей
    r1 = client.post(
        "/api/v1/auth/register",
        json={
            "terms_accepted": True,
            "data_processing_consent": True,
            "legal_versions": REQUIRED_DOCUMENTS,
            "username": "user1",
            "email": "u1@alxprgs.tech",
            "password": "Password123!",
            "confirm_password": "DifferentPassword123!",
        },
    )
    assert r1.status_code == 422

    # 2. Слишком короткий пароль (< 8 символов)
    r2 = client.post(
        "/api/v1/auth/register",
        json={
            "terms_accepted": True,
            "data_processing_consent": True,
            "legal_versions": REQUIRED_DOCUMENTS,
            "username": "user2",
            "email": "u2@alxprgs.tech",
            "password": "short",
            "confirm_password": "short",
        },
    )
    assert r2.status_code == 422

    # 3. Некорректный email
    r3 = client.post(
        "/api/v1/auth/register",
        json={
            "terms_accepted": True,
            "data_processing_consent": True,
            "legal_versions": REQUIRED_DOCUMENTS,
            "username": "user3",
            "email": "not-an-email",
            "password": "Password123!",
            "confirm_password": "Password123!",
        },
    )
    assert r3.status_code == 422


def test_registration_collision_conflict_409(monkeypatch: pytest.MonkeyPatch):
    """REG-06: При совпадении логина или email возвращается единая ошибка 409 без раскрытия поля."""
    mock_db = AsyncMock()
    config = SystemConfiguration(id=1, bootstrap_completed=True, registration_mode="open")
    existing_user = User(username="existing", email="existing@alxprgs.tech")

    async def fake_register(**_kwargs):
        raise HTTPException(
            status_code=409,
            detail={"error": "user_already_exists", "detail": "Учётная запись уже существует"},
        )

    monkeypatch.setattr(AuthService, "register_user", fake_register)

    res_cfg = MagicMock(scalar_one_or_none=MagicMock(return_value=config))
    res_coll = MagicMock(scalar_one_or_none=MagicMock(return_value=existing_user))

    mock_db.execute.side_effect = [
        res_cfg,
        MagicMock(scalar_one=MagicMock(return_value=datetime.now(timezone.utc))),
        MagicMock(scalar_one=MagicMock(return_value=1)),
        res_coll,
    ]

    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    try:
        res = client.post(
            "/api/v1/auth/register",
            json={
                "terms_accepted": True,
                "data_processing_consent": True,
                "legal_versions": REQUIRED_DOCUMENTS,
                "username": "existing",
                "email": "existing@alxprgs.tech",
                "password": "Password123!",
                "confirm_password": "Password123!",
            },
        )
        assert res.status_code == 409
        data = res.json()
        assert data["detail"]["error"] == "user_already_exists"
        # Сообщение не раскрывает, какое именно поле совпало
        assert "уже существует" in data["detail"]["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_registration_invalid_origin_rejected():
    """REG-07: Запрос с недоверенным заголовком Origin отклоняется со статусом 403."""
    res = client.post(
        "/api/v1/auth/register",
        json={
            "terms_accepted": True,
            "data_processing_consent": True,
            "legal_versions": REQUIRED_DOCUMENTS,
            "username": "origin_test",
            "email": "origin@alxprgs.tech",
            "password": "Password123!",
            "confirm_password": "Password123!",
        },
        headers={"Origin": "https://malicious-phishing-site.com"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error"] == "invalid_origin"


def test_registration_rate_limiting():
    """REG-07: Межпроцессное ограничение частоты запросов возвращает 429."""
    mock_db = AsyncMock()
    config = SystemConfiguration(id=1, bootstrap_completed=True, registration_mode="open")

    res_cfg = MagicMock(scalar_one_or_none=MagicMock(return_value=config))
    # Лимит превышен: count = 10 (>= 5)

    mock_db.execute.side_effect = [
        res_cfg,
        MagicMock(scalar_one=MagicMock(return_value=datetime.now(timezone.utc))),
        MagicMock(scalar_one=MagicMock(return_value=10)),
    ]

    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    try:
        res = client.post(
            "/api/v1/auth/register",
            json={
                "terms_accepted": True,
                "data_processing_consent": True,
                "legal_versions": REQUIRED_DOCUMENTS,
                "username": "flooder",
                "email": "flood@alxprgs.tech",
                "password": "Password123!",
                "confirm_password": "Password123!",
            },
        )
        assert res.status_code == 429
        assert res.json()["detail"]["error"] == "rate_limit_exceeded"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_system_status_and_mode_toggle():
    """REG-02: Администратор проверяет статус и переключает registration_mode с проверкой пароля."""
    mock_db = AsyncMock()
    admin_user = User(
        id=uuid.uuid4(),
        username="admin",
        email="admin@alxprgs.tech",
        is_superuser=True,
    )
    admin_user.password_credential = PasswordCredential(
        user_id=admin_user.id,
        password_hash=hash_password("AdminSecurePass123!"),
    )

    # 1. Попытка переключения с неверным паролем отклоняется (401)
    with pytest.raises(Exception) as exc_info:
        await SystemService.update_registration_mode(
            db=mock_db,
            admin_user=admin_user,
            admin_password="WrongPassword!",
            new_mode="open",
        )
    assert "Неверный пароль администратора" in str(exc_info.value)

    # 2. Успешное переключение с правильным паролем
    config = SystemConfiguration(
        id=1,
        bootstrap_completed=True,
        registration_mode="closed",
    )
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=config))

    updated_config = await SystemService.update_registration_mode(
        db=mock_db,
        admin_user=admin_user,
        admin_password="AdminSecurePass123!",
        new_mode="open",
    )
    assert updated_config.registration_mode == "open"


def test_capabilities_returns_registration_mode():
    """REG-03: GET /api/v1/auth/capabilities возвращает актуальный registration_mode."""
    mock_db = AsyncMock()
    config = SystemConfiguration(id=1, bootstrap_completed=True, registration_mode="closed")
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=config))

    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    try:
        res = client.get("/api/v1/auth/capabilities")
        assert res.status_code == 200
        data = res.json()
        assert "registration_mode" in data
        assert data["registration_mode"] == "closed"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_regular_user_cannot_access_system_status():
    """REG-02, TEST-UI-01: Обычный пользователь не имеет доступа к управлению системой (403)."""
    regular_user = User(
        id=uuid.uuid4(),
        username="bob",
        email="bob@example.com",
        is_superuser=False,
    )
    regular_user.roles = [Role(name=ROLE_USER, description="User")]

    app.dependency_overrides[get_current_user] = lambda: regular_user
    try:
        res = client.get("/api/v1/admin/system/status")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_unverified_email_blocks_login_when_required():
    """REG-09, TEST-REG-04: При REQUIRE_VERIFIED_EMAIL=true неподтвержденный email блокирует аутентификацию."""
    from unittest.mock import patch

    mock_db = AsyncMock()
    user = User(
        id=uuid.uuid4(),
        username="unverified_user",
        email="unverified@alxprgs.tech",
        is_active=True,
        email_verified=False,
    )
    user.password_credential = PasswordCredential(
        user_id=user.id,
        password_hash=hash_password("UserPass123!"),
    )

    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=user))

    with patch("app.services.auth_service.settings.REQUIRE_VERIFIED_EMAIL", True):
        with pytest.raises(Exception) as exc_info:
            await AuthService.authenticate_user(
                db=mock_db,
                username="unverified_user",
                password="UserPass123!",
            )
    assert "Вход заблокирован: требуется подтверждение" in str(exc_info.value)
