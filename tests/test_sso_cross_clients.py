import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("packages/python-sdk"))

from alxprgs_sso import InvalidTokenError, SSOClient
from app.config import get_settings
from app.core.security import get_jwks
from app.models.oidc import OIDCClient, OIDCRedirectUri
from app.models.user import Role, User
from app.services.oidc_service import OIDCService
from fastapi.testclient import TestClient

import examples.client1.app as client1_module
import examples.client2.app as client2_module


def test_demo_clients_routes_and_login_redirect(monkeypatch: pytest.MonkeyPatch):
    """
    Проверка работы демонстрационных клиентов (SDK-06):
    - Client 1 (Analytics): главная страница и редирект на /oauth/authorize;
    - Client 2 (Documentation): главная страница и редирект на /oauth/authorize.
    """
    monkeypatch.setenv("DEMO_ALLOW_HTTP_LOCALHOST", "1")
    c1 = TestClient(client1_module.app, base_url="http://localhost")
    c2 = TestClient(client2_module.app, base_url="http://localhost")

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
async def test_oidc_service_issues_isolated_codes_for_two_clients_unit():
    """
    Unit-проверка выдачи отдельных codes/tokens для двух клиентов с mock DB.
    Реальный вход без повторного пароля проверяется только browser E2E.
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
    oidc_client_1.redirect_uris = [
        OIDCRedirectUri(client_id=oidc_client_1.id, uri=client1_redirect)
    ]

    client2_id = "client_docs_app"
    client2_redirect = "http://localhost:8002/callback"
    oidc_client_2 = OIDCClient(
        id=uuid.uuid4(),
        client_id=client2_id,
        client_name="Docs Portal",
        client_type="public",
        is_active=True,
    )
    oidc_client_2.redirect_uris = [
        OIDCRedirectUri(client_id=oidc_client_2.id, uri=client2_redirect)
    ]

    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    # 3. Инициализируем SDK для обоих клиентов
    sdk1 = SSOClient(
        server_url=settings.BASE_URL, client_id=client1_id, expected_issuer=settings.OIDC_ISSUER
    )
    sdk2 = SSOClient(
        server_url=settings.BASE_URL, client_id=client2_id, expected_issuer=settings.OIDC_ISSUER
    )
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

    # Здесь проверены лишь сервисные операции; браузерная SSO-сессия не создавалась.


def test_client_web_session_cookie_lifecycle_and_csrf(monkeypatch: pytest.MonkeyPatch):
    """
    Инварианты SDK-06, SSO-01, FINAL-09:
    Тестирование полного жизненного цикла веб-сессии в демонстрационном клиенте:
    1. Инициация входа /login с непрозрачной cookie flow.
    2. Отклонение callback без cookie или с несовпадающим state (защита от CSRF).
    3. Успешный callback с установкой HttpOnly непрозрачной сессионной cookie.
    4. Доступ к защищенному маршруту /dashboard по сессионной cookie.
    5. Завершение сессии /logout с очисткой cookie и редиректом на сервер авторизации.
    """
    from alxprgs_sso.models import UserClaims, WebSessionInfo

    monkeypatch.setenv("DEMO_ALLOW_HTTP_LOCALHOST", "1")
    c1 = TestClient(client1_module.app, base_url="http://localhost")

    # 1. /login
    login_res = c1.get("/login", follow_redirects=False)
    assert login_res.status_code == 302
    assert "demo_client_analytics_app_flow" in login_res.cookies

    # Распарсим state из URL
    location = login_res.headers["Location"]
    parsed_url = urlparse(location)
    query_params = parse_qs(parsed_url.query)
    expected_state = query_params["state"][0]

    # 2. Попытка CSRF: несовпадающий state
    csrf_res = c1.get(f"/callback?code=mock_code&state=fake_state_{uuid.uuid4().hex}")
    assert csrf_res.status_code == 400
    assert "Invalid" in csrf_res.text

    # Попытка запроса без cookie сессии авторизации
    c1_no_cookie = TestClient(client1_module.app, base_url="http://localhost")
    no_cookie_res = c1_no_cookie.get(f"/callback?code=mock_code&state={expected_state}")
    assert no_cookie_res.status_code == 400
    assert "Invalid" in no_cookie_res.text

    # A mismatched callback consumes the flow. A new browser flow is needed.
    new_login = c1.get("/login", follow_redirects=False)
    expected_state = parse_qs(urlparse(new_login.headers["Location"]).query)["state"][0]

    # 3. Успешный callback с валидным state и непрозрачной cookie
    mock_session_info = WebSessionInfo(
        user=UserClaims(
            sub="user_12345",
            preferred_username="test_analyst",
            email="analyst@alxprgs.tech",
            email_verified=True,
            roles=["analyst", "user"],
        ),
        access_token="mock_access_token",
        id_token="mock_id_token",
        expires_in=3600,
        id_token_claims={"sub": "user_12345", "aud": "client_analytics_app"},
    )

    with patch.object(
        client1_module.sso_client,
        "handle_web_callback",
        new=AsyncMock(return_value=mock_session_info),
    ):
        callback_res = c1.get(
            f"/callback?code=valid_code&state={expected_state}",
            follow_redirects=False,
        )
        assert callback_res.status_code == 302
        assert callback_res.headers["Location"] == "/dashboard"
        assert "demo_client_analytics_app_session" in callback_res.cookies

        # 4. Проверяем /dashboard с полученной сессионной cookie
        dashboard_res = c1.get("/dashboard")
        assert dashboard_res.status_code == 200
        assert "test_analyst" in dashboard_res.text
        assert "analyst@alxprgs.tech" in dashboard_res.text

        # 5. Replay and forged cookies cannot restore the server-side session.
        assert c1.get(f"/callback?code=valid_code&state={expected_state}").status_code == 400
        forged = TestClient(client1_module.app, base_url="http://localhost")
        forged.cookies.set("demo_client_analytics_app_session", "forged")
        assert forged.get("/api/me").status_code == 401

        # 6. Local logout requires CSRF and revokes server-side access.
        session_id = c1.cookies["demo_client_analytics_app_session"]
        csrf = client1_module.sessions.get_session(session_id).csrf
        assert c1.post("/logout", data={"csrf": "wrong"}).status_code == 403
        logout_res = c1.post("/logout", data={"csrf": csrf}, follow_redirects=False)
        assert logout_res.status_code == 303
        c1.cookies.set("demo_client_analytics_app_session", session_id)
        assert c1.get("/api/me").status_code == 401
