import base64
import hashlib
import os
import urllib.parse

import httpx
import pytest
from app.cli.bootstrap_admin import execute_bootstrap
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def make_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_discovery_and_jwks_pg(pg_client: httpx.AsyncClient):
    """
    QA-07, SSO-01: Проверка эндпоинтов OpenID Connect Discovery и JWKS.
    - /.well-known/openid-configuration: валидные эндпоинты, response_types_supported, PKCE S256.
    - /.well-known/jwks.json: валидный открытый ключ RSA с алгоритмом RS256.
    """
    # 1. Discovery
    disc_res = await pg_client.get("/.well-known/openid-configuration")
    assert disc_res.status_code == 200
    config = disc_res.json()
    assert "authorization_endpoint" in config
    assert "token_endpoint" in config
    assert "userinfo_endpoint" in config
    assert "jwks_uri" in config
    assert "end_session_endpoint" in config
    assert config["response_types_supported"] == ["code"]
    assert config["code_challenge_methods_supported"] == ["S256"]
    # plain метод не поддерживается
    assert "plain" not in config["code_challenge_methods_supported"]

    # 2. JWKS
    jwks_res = await pg_client.get("/.well-known/jwks.json")
    assert jwks_res.status_code == 200
    jwks = jwks_res.json()
    assert "keys" in jwks
    assert len(jwks["keys"]) >= 1
    key = jwks["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert "n" in key and "e" in key and "kid" in key


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_client_creation_and_redirect_uri_strict_validation_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-07, SSO-02: Строгая проверка redirect_uri без wildcards и поддоменов на PostgreSQL.
    """
    # 1. Создаем админа и авторизуемся
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="admin_client_mgr",
        email="client_mgr@alxprgs.tech",
        password="AdminClientPass2026!",
        registration_mode="closed",
    )
    assert code == 0

    login_res = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "admin_client_mgr", "password": "AdminClientPass2026!"},
    )
    adm_csrf = login_res.json()["csrf_token"]

    # 2. Регистрируем клиента через админ API
    c_res = await pg_client.post(
        "/api/v1/admin/clients",
        headers={"X-CSRF-Token": adm_csrf},
        json={
            "client_name": "Secure Service A",
            "client_type": "confidential",
            "redirect_uris": [
                "https://service-a.alxprgs.tech/oauth/callback",
                "http://127.0.0.1:8080/callback",
            ],
        },
    )
    assert c_res.status_code == 201
    client_data = c_res.json()
    client_id = client_data["client_id"]
    client_secret = client_data["client_secret"]
    assert client_secret is not None

    # 3. Проверяем строгую валидацию redirect_uri на /oauth/authorize
    # 3.1 Несуществующий client_id -> 401
    r_bad_client = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": "nonexistent_client_xyz",
            "redirect_uri": "https://service-a.alxprgs.tech/oauth/callback",
            "response_type": "code",
            "code_challenge": "abc" * 15,
            "code_challenge_method": "S256",
        },
    )
    assert r_bad_client.status_code == 401

    # 3.2 Несовпадающий домен (evil.com) -> 400
    r_evil = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://evil.com/callback",
            "response_type": "code",
            "code_challenge": "abc" * 15,
            "code_challenge_method": "S256",
        },
    )
    assert r_evil.status_code == 400
    assert "redirect_uri" in str(r_evil.json())

    # 3.3 Path traversal / попытка расширить путь -> 400
    r_traversal = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://service-a.alxprgs.tech/oauth/callback/extra",
            "response_type": "code",
            "code_challenge": "abc" * 15,
            "code_challenge_method": "S256",
        },
    )
    assert r_traversal.status_code == 400

    # 3.4 Неподдерживаемый response_type=token -> 400
    r_token_flow = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://service-a.alxprgs.tech/oauth/callback",
            "response_type": "token",
            "code_challenge": "abc" * 15,
            "code_challenge_method": "S256",
        },
    )
    assert r_token_flow.status_code == 400


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_authorization_code_pkce_flow_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-07, SSO-03, SSO-05: Полный Authorization Code Flow + PKCE S256 на PostgreSQL.
    - Выпуск кода в сессии SSO.
    - Проверка сохранения в authorization_codes в БД.
    - Отказ при неверном code_verifier.
    - Успешный обмен на tokens (access, id, refresh).
    - Защита от Replay: повторный обмен того же кода отклоняется.
    """
    # 1. Создаем админа и клиента
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="oidc_user_pkce",
        email="pkce@alxprgs.tech",
        password="OidcPassword2026!",
        registration_mode="closed",
    )
    assert code == 0

    login_res = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "oidc_user_pkce", "password": "OidcPassword2026!"},
    )
    adm_csrf = login_res.json()["csrf_token"]

    c_res = await pg_client.post(
        "/api/v1/admin/clients",
        headers={"X-CSRF-Token": adm_csrf},
        json={
            "client_name": "PKCE App",
            "client_type": "confidential",
            "redirect_uris": ["https://pkce-client.alxprgs.tech/callback"],
        },
    )
    client_id = c_res.json()["client_id"]
    client_secret = c_res.json()["client_secret"]
    redirect_uri = "https://pkce-client.alxprgs.tech/callback"

    # 2. Генерируем валидную пару PKCE S256
    verifier, challenge = make_pkce_pair()

    # 3. Запрос /oauth/authorize (пользователь уже залогинен в pg_client через cookie)
    auth_res = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": "state_secure_12345",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "nonce": "nonce_random_999",
        },
        follow_redirects=False,
    )
    assert auth_res.status_code == 302
    location = auth_res.headers["Location"]
    parsed_loc = urllib.parse.urlparse(location)
    query_params = urllib.parse.parse_qs(parsed_loc.query)
    assert "code" in query_params
    assert query_params["state"][0] == "state_secure_12345"
    auth_code = query_params["code"][0]

    # 4. Проверяем состояние authorization_code в PostgreSQL
    code_hash = hashlib.sha256(auth_code.encode("utf-8")).hexdigest()
    ac_row = await pg_session.execute(
        text(
            "SELECT code_challenge, is_used, client_id, user_id FROM authorization_codes WHERE code_hash = :ch"
        ),
        {"ch": code_hash},
    )
    ac = ac_row.fetchone()
    assert ac is not None
    assert ac[0] == challenge
    assert ac[1] is False  # is_used is False initially

    # 5. Попытка обмена с неверным code_verifier -> 400 invalid_grant
    bad_token_res = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": "wrong_verifier_abcdefghijklmnopqrstuvwxyz12345",
        },
    )
    assert bad_token_res.status_code == 400
    assert bad_token_res.json()["error"] == "invalid_grant"

    # 6. Успешный обмен с правильным code_verifier -> 200 OK
    token_res = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        },
    )
    assert token_res.status_code == 200
    token_data = token_res.json()
    assert "access_token" in token_data
    assert "id_token" in token_data
    assert "refresh_token" in token_data
    assert token_data["token_type"] == "Bearer"
    assert token_data["expires_in"] == 300

    # 7. Проверяем в PostgreSQL, что код помечен как использованный
    ac_used_row = await pg_session.execute(
        text("SELECT is_used FROM authorization_codes WHERE code_hash = :ch"),
        {"ch": code_hash},
    )
    assert ac_used_row.scalar_one() is True

    # 8. Защита от Replay: повторная попытка обменять тот же код -> 400 invalid_grant
    replay_res = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        },
    )
    assert replay_res.status_code == 400
    assert replay_res.json()["error"] == "invalid_grant"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_oidc_userinfo_and_id_token_rejection_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-07, SSO-03, SSO-04: UserInfo эндпоинт и строгий инвариант:
    Запрещено принимать ID Token вместо Access Token.
    """
    # 1. Создаем пользователя и клиента
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="userinfo_tester",
        email="userinfo@alxprgs.tech",
        password="UserinfoPassword123!",
        registration_mode="closed",
    )
    assert code == 0

    login_res = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "userinfo_tester", "password": "UserinfoPassword123!"},
    )
    adm_csrf = login_res.json()["csrf_token"]

    c_res = await pg_client.post(
        "/api/v1/admin/clients",
        headers={"X-CSRF-Token": adm_csrf},
        json={
            "client_name": "UserInfo App",
            "client_type": "public",
            "redirect_uris": ["https://userinfo.alxprgs.tech/callback"],
        },
    )
    client_id = c_res.json()["client_id"]
    redirect_uri = "https://userinfo.alxprgs.tech/callback"

    # Получаем токены через PKCE
    verifier, challenge = make_pkce_pair()
    auth_res = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    auth_code = urllib.parse.parse_qs(urllib.parse.urlparse(auth_res.headers["Location"]).query)[
        "code"
    ][0]

    token_res = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    tokens = token_res.json()
    access_token = tokens["access_token"]
    id_token = tokens["id_token"]

    # 2. Вызов /oauth/userinfo с Access Token -> 200 OK
    ui_res = await pg_client.get(
        "/oauth/userinfo", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert ui_res.status_code == 200
    ui_data = ui_res.json()
    assert ui_data["preferred_username"] == "userinfo_tester"
    assert ui_data["email"] == "userinfo@alxprgs.tech"
    assert "sub" in ui_data

    # 3. Инвариант SSO-03: Вызов /oauth/userinfo с ID Token вместо Access Token -> 401 Unauthorized
    ui_fail = await pg_client.get(
        "/oauth/userinfo", headers={"Authorization": f"Bearer {id_token}"}
    )
    assert ui_fail.status_code == 401
    assert ui_fail.json()["error"] == "invalid_token"
    assert "ID Token" in ui_fail.json()["error_description"]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_refresh_token_rotation_and_replay_family_revocation_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-07, SSO-05: Ротация Refresh Token и Replay Detection с аннулированием всего семейства в PostgreSQL.
    """
    # 1. Создаем пользователя и клиента
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="rotation_user",
        email="rotation@alxprgs.tech",
        password="RotationPassword123!",
        registration_mode="closed",
    )
    assert code == 0

    login_res = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "rotation_user", "password": "RotationPassword123!"},
    )
    adm_csrf = login_res.json()["csrf_token"]

    c_res = await pg_client.post(
        "/api/v1/admin/clients",
        headers={"X-CSRF-Token": adm_csrf},
        json={
            "client_name": "Rotation App",
            "client_type": "confidential",
            "redirect_uris": ["https://rotation.alxprgs.tech/callback"],
        },
    )
    client_id = c_res.json()["client_id"]
    client_secret = c_res.json()["client_secret"]
    redirect_uri = "https://rotation.alxprgs.tech/callback"

    # Получаем исходный refresh token (RT1)
    verifier, challenge = make_pkce_pair()
    auth_res = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert auth_res.status_code == 302
    auth_code = urllib.parse.parse_qs(urllib.parse.urlparse(auth_res.headers["Location"]).query)[
        "code"
    ][0]

    token_res = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        },
    )
    rt1 = token_res.json()["refresh_token"]

    # 2. Ротация токена: клиент отправляет RT1 и получает RT2
    rotate_res_1 = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": rt1,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    assert rotate_res_1.status_code == 200
    rt2 = rotate_res_1.json()["refresh_token"]
    assert rt1 != rt2

    # Проверяем в PostgreSQL, что RT1 отозван
    rt1_db = await pg_session.execute(
        text("SELECT is_revoked FROM refresh_tokens WHERE token_hash = :th"),
        {"th": hashlib.sha256(rt1.encode("utf-8")).hexdigest()},
    )
    assert rt1_db.scalar_one() is True  # is_revoked is True

    # 3. Атака Replay: злоумышленник пытается повторно использовать уже отозванный RT1
    replay_attack_res = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": rt1,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    assert replay_attack_res.status_code == 400
    assert replay_attack_res.json()["error"] == "invalid_grant"

    # 4. Проверяем в PostgreSQL: всё семейство токенов (family_id) должно быть отозвано!
    # Проверяем статус RT2
    rt2_db = await pg_session.execute(
        text("SELECT is_revoked FROM refresh_tokens WHERE token_hash = :th"),
        {"th": hashlib.sha256(rt2.encode("utf-8")).hexdigest()},
    )
    assert rt2_db.scalar_one() is True  # RT2 также отозван!

    # 5. Попытка легитимного клиента использовать RT2 теперь отклоняется
    legit_fail = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": rt2,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    assert legit_fail.status_code == 400
    assert legit_fail.json()["error"] == "invalid_grant"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_seamless_cross_client_sso_and_rp_logout_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    QA-07, SSO-01, SSO-07, SDK-06: Бесшовный Single Sign-On для двух клиентов и RP-Initiated Logout на PostgreSQL.
    """
    # 1. Создаем пользователя
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="sso_wanderer",
        email="wanderer@alxprgs.tech",
        password="WandererPass2026!",
        registration_mode="closed",
    )
    assert code == 0

    # 2. Входим в SSO через логин-форму
    login_res = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "sso_wanderer", "password": "WandererPass2026!"},
    )
    assert login_res.status_code == 200
    adm_csrf = login_res.json()["csrf_token"]

    # 3. Регистрируем Client 1 (Analytics) и Client 2 (Docs)
    c1_res = await pg_client.post(
        "/api/v1/admin/clients",
        headers={"X-CSRF-Token": adm_csrf},
        json={
            "client_name": "Analytics Client",
            "client_type": "public",
            "redirect_uris": ["http://localhost:8001/callback"],
        },
    )
    c1_id = c1_res.json()["client_id"]

    c2_res = await pg_client.post(
        "/api/v1/admin/clients",
        headers={"X-CSRF-Token": adm_csrf},
        json={
            "client_name": "Docs Client",
            "client_type": "public",
            "redirect_uris": ["http://localhost:8002/callback"],
        },
    )
    c2_id = c2_res.json()["client_id"]

    # 4. Клиент 1 инициирует вход через /oauth/authorize -> МГНОВЕННЫЙ 302 без ввода логина/пароля
    v1, ch1 = make_pkce_pair()
    c1_auth = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": c1_id,
            "redirect_uri": "http://localhost:8001/callback",
            "response_type": "code",
            "scope": "openid profile email",
            "state": "s1",
            "code_challenge": ch1,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert c1_auth.status_code == 302
    assert "http://localhost:8001/callback" in c1_auth.headers["Location"]
    code1 = urllib.parse.parse_qs(urllib.parse.urlparse(c1_auth.headers["Location"]).query)["code"][
        0
    ]

    # 5. Клиент 2 инициирует вход через /oauth/authorize -> МГНОВЕННЫЙ 302 без ввода логина/пароля (SSO!)
    v2, ch2 = make_pkce_pair()
    c2_auth = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": c2_id,
            "redirect_uri": "http://localhost:8002/callback",
            "response_type": "code",
            "scope": "openid profile email",
            "state": "s2",
            "code_challenge": ch2,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert c2_auth.status_code == 302
    assert "http://localhost:8002/callback" in c2_auth.headers["Location"]
    code2 = urllib.parse.parse_qs(urllib.parse.urlparse(c2_auth.headers["Location"]).query)["code"][
        0
    ]

    # 6. Оба клиента успешно получают свои токены
    t1_res = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code1,
            "redirect_uri": "http://localhost:8001/callback",
            "client_id": c1_id,
            "code_verifier": v1,
        },
    )
    assert t1_res.status_code == 200
    id_token1 = t1_res.json()["id_token"]

    t2_res = await pg_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code2,
            "redirect_uri": "http://localhost:8002/callback",
            "client_id": c2_id,
            "code_verifier": v2,
        },
    )
    assert t2_res.status_code == 200

    # 7. RP-Initiated Logout: no hint or an unregistered return URI must not
    # consume the SSO session. The valid return URI is registered exactly.
    no_hint = await pg_client.get(
        "/oauth/logout",
        params={"post_logout_redirect_uri": "http://localhost:8001/callback"},
        follow_redirects=False,
    )
    assert no_hint.status_code == 400
    bad_redirect = await pg_client.get(
        "/oauth/logout",
        params={"id_token_hint": id_token1, "post_logout_redirect_uri": "https://outside.example/"},
        follow_redirects=False,
    )
    assert bad_redirect.status_code == 400
    logout_res = await pg_client.get(
        "/oauth/logout",
        params={
            "id_token_hint": id_token1,
            "post_logout_redirect_uri": "http://localhost:8001/callback",
            "state": "logout_state_1",
        },
        follow_redirects=False,
    )
    assert logout_res.status_code == 302
    assert "http://localhost:8001/callback?state=logout_state_1" in logout_res.headers["Location"]

    # 8. Проверяем в PostgreSQL, что сессия SSO удалена
    cnt_sess = await pg_session.execute(text("SELECT count(*) FROM sessions"))
    assert cnt_sess.scalar_one() == 0

    # 9. Теперь повторное обращение от Клиента 2 редиректит на форму входа (/login), а не выдает код
    c2_after_logout = await pg_client.get(
        "/oauth/authorize",
        params={
            "client_id": c2_id,
            "redirect_uri": "http://localhost:8002/callback",
            "response_type": "code",
            "scope": "openid profile email",
            "state": "s3",
            "code_challenge": ch2,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert c2_after_logout.status_code == 302
    assert "/login?return_to=" in c2_after_logout.headers["Location"]
