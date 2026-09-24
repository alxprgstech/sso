import base64
import hashlib
import os
import sys
import uuid
from urllib.parse import parse_qs, urlparse
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("packages/python-sdk"))

from fastapi.testclient import TestClient
from app.main import app as sso_app
from app.models.user import User, Role
from app.models.oidc import OIDCClient, OIDCRedirectUri
from app.services.oidc_service import OIDCService
from app.config import get_settings
from app.core.security import get_jwks
from alxprgs_sso import SSOClient, UserClaims, InvalidTokenError

import examples.client1.app as client1_module
import examples.client2.app as client2_module


def test_demo_clients_routes_and_login_redirect():
    """
    Проверка работы демонстрационных клиентов (SDK-06):
    - Client 1 (Analytics): главная страница и редирект на /oauth/authorize;
    - Client 2 (Documentation): главная страница и редирект на /oauth/authorize.
    """
    c1 = TestClient(client1_module.app)
    c2 = TestClient(client2_module.app)

    # 1. Client 1
    r1_index = c1.get("/")
    assert r1_index.status_code == 200
    assert "Портал аналитики" in r1_index.text

    r1_login = c1.get("/login", follow_redirects=False)
    assert r1_login.status_code == 307 or r1_login.status_code == 302
    auth_url_1 = r1_login.headers["Location"]
    assert "client_analytics_app" in auth_url_1
    assert "code_challenge=" in auth_url_1
    assert "code_challenge_method=S256" in auth_url_1

    # 2. Client 2
    r2_index = c2.get("/")
    assert r2_index.status_code == 200
    assert "Портал документации" in r2_index.text

    r2_login = c2.get("/login", follow_redirects=False)
    assert r2_login.status_code == 307 or r2_login.status_code == 302
    auth_url_2 = r2_login.headers["Location"]
    assert "client_docs_app" in auth_url_2
    assert "code_challenge=" in auth_url_2
    assert "code_challenge_method=S256" in auth_url_2


@pytest.mark.asyncio
async def test_seamless_sso_between_two_clients():
    """
    Инвариант SSO-01, SSO-02, SDK-06:
    Бесшовный Single Sign-On между двумя независимыми клиентами (Client 1 и Client 2).
    Пользователь, аутентифицированный в SSO-сервере, получает доступ к обоим сервисам
    без повторного ввода пароля.
    """
    settings = get_settings()

    # 1. Пользователь в базе SSO
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username="sso_explorer",
        email="explorer@alxprgs.tech",
        is_active=True,
        email_verified=True,
    )
    user.roles = [Role(name="user")]

    # 2. Два независимых зарегистрированных OIDC-клиента
    client1_id = "client_analytics_app"
    client1_redirect = "http://localhost:8001/callback"
    oidc_client_1 = OIDCClient(
        id=uuid.uuid4(),
        client_id=client1_id,
        client_name="Analytics Portal",
        client_type="public",
        is_active=True,
    )
    oidc_client_1.redirect_uris = [OIDCRedirectUri(client_id=oidc_client_1.id, uri=client1_redirect)]

    client2_id = "client_docs_app"
    client2_redirect = "http://localhost:8002/callback"
    oidc_client_2 = OIDCClient(
        id=uuid.uuid4(),
        client_id=client2_id,
        client_name="Docs Portal",
        client_type="public",
        is_active=True,
    )
    oidc_client_2.redirect_uris = [OIDCRedirectUri(client_id=oidc_client_2.id, uri=client2_redirect)]

    mock_db = AsyncMock()

    # 3. Инициализируем SDK для обоих клиентов
    sdk1 = SSOClient(server_url=settings.BASE_URL, client_id=client1_id, expected_issuer=settings.OIDC_ISSUER)
    sdk2 = SSOClient(server_url=settings.BASE_URL, client_id=client2_id, expected_issuer=settings.OIDC_ISSUER)
    server_jwks = get_jwks()

    # ---- ШАГ А: Вход в Client 1 через SSO ----
    auth_url_1, code_verifier_1, state_1 = sdk1.generate_authorization_url(
        redirect_uri=client1_redirect,
    )

    # Сервер SSO генерирует одноразовый authorization code для Client 1
    code_1 = await OIDCService.create_authorization_code(
        db=mock_db,
        client=oidc_client_1,
        user=user,
        redirect_uri=client1_redirect,
        scope="openid profile email",
        code_challenge=parse_qs(urlparse(auth_url_1).query)["code_challenge"][0],
        code_challenge_method="S256",
    )
    assert len(code_1) > 20

    # Выпуск токенов для Client 1
    tokens_1 = await OIDCService._generate_tokens_for_user(
        db=mock_db,
        user=user,
        client=oidc_client_1,
        scope="openid profile email",
    )
    assert tokens_1.access_token is not None
    assert tokens_1.id_token is not None

    # ---- ШАГ Б: Бесшовный вход в Client 2 (Cross-client SSO) ----
    # Пользователь переходит на Client 2. SSO-сессия уже активна, пароль повторно не запрашивается.
    auth_url_2, code_verifier_2, state_2 = sdk2.generate_authorization_url(
        redirect_uri=client2_redirect,
    )

    # Сервер SSO моментально генерирует новый авторизационный код для Client 2
    code_2 = await OIDCService.create_authorization_code(
        db=mock_db,
        client=oidc_client_2,
        user=user,
        redirect_uri=client2_redirect,
        scope="openid profile email",
        code_challenge=parse_qs(urlparse(auth_url_2).query)["code_challenge"][0],
        code_challenge_method="S256",
    )
    assert len(code_2) > 20
    assert code_2 != code_1  # Одноразовый независимый код

    # Выпуск токенов для Client 2
    tokens_2 = await OIDCService._generate_tokens_for_user(
        db=mock_db,
        user=user,
        client=oidc_client_2,
        scope="openid profile email",
    )
    assert tokens_2.access_token is not None
    assert tokens_2.id_token is not None

    # Валидация токенов через SDK для обоих клиентов
    with patch.object(SSOClient, "get_jwks", return_value=server_jwks):
        claims_1 = sdk1.verify_access_token(tokens_1.access_token, expected_audience=client1_id)
        assert claims_1.preferred_username == "sso_explorer"
        assert claims_1.sub == str(user_id)

        claims_2 = sdk2.verify_access_token(tokens_2.access_token, expected_audience=client2_id)
        assert claims_2.preferred_username == "sso_explorer"
        assert claims_2.sub == str(user_id)

        # Проверка изоляции audience: токен Client 2 отклоняется Client 1
        with pytest.raises(InvalidTokenError):
            sdk1.verify_access_token(tokens_2.access_token, expected_audience=client1_id)

    # Бесшовный единый вход подтверждён!
