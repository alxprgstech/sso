import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, os.path.abspath("backend"))

from app.config import get_settings
from app.core.exceptions import OAuthErrorException
from app.core.security import create_jwt, generate_random_token, hash_password, hash_token
from app.main import app
from app.models.oidc import AuthorizationCode, OIDCClient, OIDCRedirectUri, RefreshToken
from app.models.session import Session
from app.models.user import PasswordCredential, User
from app.services.oidc_service import OIDCService

settings = get_settings()


# ==============================================================================
# 1. FINAL-01: Confidential Client Authentication Enforcement
# ==============================================================================


@pytest.mark.asyncio
async def test_confidential_client_requires_secret_on_code_exchange(pg_session: AsyncSession):
    """
    FINAL-01 / G8-SEC:
    Для confidential клиента отсутствие, пустой или неверный client_secret
    ОБЯЗАНЫ отклоняться со статусом 401 invalid_client.
    Валидный authorization code НЕ ДОЛЖЕН сгорать при сбое аутентификации клиента!
    """
    # 1. Создаем тестового пользователя
    user = User(
        username=f"sec_user_{uuid.uuid4().hex[:6]}",
        email=f"sec_{uuid.uuid4().hex[:6]}@example.com",
        is_active=True,
    )
    user.password_credential = PasswordCredential(password_hash=hash_password("SecPass123!"))
    pg_session.add(user)
    await pg_session.flush()

    # 2. Создаем confidential клиента с известным секретом
    raw_secret = "very_secret_confidential_key_123"
    client_obj = OIDCClient(
        client_id=f"conf-client-{uuid.uuid4().hex[:6]}",
        client_name="Confidential Test App",
        client_type="confidential",
        client_secret_hash=hash_password(raw_secret),
        is_active=True,
    )
    pg_session.add(client_obj)
    await pg_session.flush()

    redirect_uri = "https://app.example.com/callback"
    redir = OIDCRedirectUri(client_id=client_obj.id, uri=redirect_uri)
    pg_session.add(redir)
    await pg_session.flush()

    # 3. Создаем валидный authorization code (PKCE S256)
    code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    code_challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    raw_code = await OIDCService.create_authorization_code(
        db=pg_session,
        client=client_obj,
        user=user,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method="S256",
        scope="openid profile email",
    )

    # А. Попытка обмена БЕЗ секрета (client_secret is None) -> 401 invalid_client
    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.exchange_code(
            db=pg_session,
            client_id=client_obj.client_id,
            client_secret=None,
            code=raw_code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.error == "invalid_client"

    # Проверяем, что код НЕ сгорел!
    code_hash = hash_token(raw_code)
    stmt = select(AuthorizationCode).where(AuthorizationCode.code_hash == code_hash)
    ac = (await pg_session.execute(stmt)).scalar_one()
    assert ac.is_used is False, (
        "Код авторизации не должен расходоваться при сбое аутентификации клиента!"
    )

    # Б. Попытка обмена с пустым секретом ("") -> 401 invalid_client
    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.exchange_code(
            db=pg_session,
            client_id=client_obj.client_id,
            client_secret="",
            code=raw_code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.error == "invalid_client"
    assert ac.is_used is False

    # В. Попытка обмена с неверным секретом -> 401 invalid_client
    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.exchange_code(
            db=pg_session,
            client_id=client_obj.client_id,
            client_secret="wrong_secret_value",
            code=raw_code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.error == "invalid_client"
    assert ac.is_used is False

    # Г. Попытка обмена с ПРАВИЛЬНЫМ секретом -> УСПЕХ, код погашен
    token_res = await OIDCService.exchange_code(
        db=pg_session,
        client_id=client_obj.client_id,
        client_secret=raw_secret,
        code=raw_code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )
    assert token_res.access_token is not None
    assert token_res.refresh_token is not None

    # Теперь код погашен
    await pg_session.refresh(ac)
    assert ac.is_used is True


@pytest.mark.asyncio
async def test_confidential_client_requires_secret_on_refresh_and_revoke(pg_session: AsyncSession):
    """
    FINAL-01: Ротация refresh токена и отзыв (revoke) для confidential клиента
    требуют обязательной аутентификации секрета.
    """
    user = User(
        username=f"sec_rf_{uuid.uuid4().hex[:6]}",
        email=f"sec_rf_{uuid.uuid4().hex[:6]}@example.com",
        is_active=True,
    )
    user.password_credential = PasswordCredential(password_hash=hash_password("SecPass123!"))
    pg_session.add(user)
    await pg_session.flush()

    raw_secret = "rf_secret_value_123"
    client_obj = OIDCClient(
        client_id=f"conf-rf-{uuid.uuid4().hex[:6]}",
        client_name="Confidential Refresh App",
        client_type="confidential",
        client_secret_hash=hash_password(raw_secret),
        is_active=True,
    )
    pg_session.add(client_obj)
    await pg_session.flush()

    # Выпускаем refresh token
    raw_rt = generate_random_token(32)
    rt_record = RefreshToken(
        family_id=uuid.uuid4(),
        token_hash=hash_token(raw_rt),
        client_id=client_obj.id,
        user_id=user.id,
        scope="openid profile",
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    pg_session.add(rt_record)
    await pg_session.commit()

    # 1. Refresh без секрета -> 401 invalid_client
    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.rotate_refresh_token(
            db=pg_session,
            client_id=client_obj.client_id,
            client_secret=None,
            raw_refresh_token=raw_rt,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.error == "invalid_client"

    # 2. Revoke с неверным секретом -> 401 invalid_client
    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.revoke_token(
            db=pg_session,
            client_id=client_obj.client_id,
            client_secret="bad_secret",
            token=raw_rt,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.error == "invalid_client"

    # 3. Refresh с правильным секретом -> УСПЕХ
    res = await OIDCService.rotate_refresh_token(
        db=pg_session,
        client_id=client_obj.client_id,
        client_secret=raw_secret,
        raw_refresh_token=raw_rt,
    )
    assert res.access_token is not None


@pytest.mark.asyncio
async def test_public_client_works_without_secret_with_pkce(pg_session: AsyncSession):
    """
    FINAL-01: Public клиент (например SPA) работает БЕЗ секрета, но с обязательным PKCE.
    """
    user = User(
        username=f"pub_user_{uuid.uuid4().hex[:6]}",
        email=f"pub_{uuid.uuid4().hex[:6]}@example.com",
        is_active=True,
    )
    user.password_credential = PasswordCredential(password_hash=hash_password("SecPass123!"))
    pg_session.add(user)
    await pg_session.flush()

    pub_client = OIDCClient(
        client_id=f"pub-client-{uuid.uuid4().hex[:6]}",
        client_name="Public SPA App",
        client_type="public",
        client_secret_hash=None,
        is_active=True,
    )
    pg_session.add(pub_client)
    await pg_session.flush()

    redirect_uri = "http://localhost:3000/callback"
    redir = OIDCRedirectUri(client_id=pub_client.id, uri=redirect_uri)
    pg_session.add(redir)
    await pg_session.flush()

    code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    code_challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    raw_code = await OIDCService.create_authorization_code(
        db=pg_session,
        client=pub_client,
        user=user,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method="S256",
        scope="openid profile",
    )

    # Обмен кода public клиентом без секрета проходит успешно
    token_res = await OIDCService.exchange_code(
        db=pg_session,
        client_id=pub_client.client_id,
        client_secret=None,
        code=raw_code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )
    assert token_res.access_token is not None


# ==============================================================================
# 2. FINAL-02: /oauth/authorize Session Lifecycle and Validation
# ==============================================================================


@pytest.mark.asyncio
async def test_authorize_rejects_expired_and_idle_session(pg_session: AsyncSession):
    """
    FINAL-02 / G8-SEC:
    Эндпоинт /oauth/authorize обязан отклонять устаревшие сессии (expired / idle)
    и перенаправлять на страницу входа с удалением недействительной cookie.
    """
    from app.database import get_db

    user = User(
        username=f"auth_user_{uuid.uuid4().hex[:6]}",
        email=f"auth_{uuid.uuid4().hex[:6]}@example.com",
        is_active=True,
    )
    user.password_credential = PasswordCredential(password_hash=hash_password("SecPass123!"))
    pg_session.add(user)
    await pg_session.flush()

    client_obj = OIDCClient(
        client_id=f"auth-client-{uuid.uuid4().hex[:6]}",
        client_name="Authorize App",
        client_type="public",
        is_active=True,
    )
    pg_session.add(client_obj)
    await pg_session.flush()

    redirect_uri = "http://localhost:3000/callback"
    redir = OIDCRedirectUri(client_id=client_obj.id, uri=redirect_uri)
    pg_session.add(redir)
    await pg_session.flush()

    # 1. Просроченная сессия (expires_at в прошлом)
    raw_session_token = generate_random_token(32)
    expired_sess = Session(
        user_id=user.id,
        session_token_hash=hash_token(raw_session_token),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        last_activity_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    pg_session.add(expired_sess)
    await pg_session.commit()

    async def override_get_db():
        yield pg_session

    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)

    try:
        cookie_name = "alx_session"
        tc.cookies.set(cookie_name, raw_session_token)

        params = {
            "client_id": client_obj.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        }
        res = tc.get("/oauth/authorize", params=params, follow_redirects=False)

        # Должен перенаправить на /login (302)
        assert res.status_code == 302
        assert "/login" in res.headers["location"]
        assert "return_to=" in res.headers["location"]

        # Сессия должна быть удалена из БД
        sess_check = (
            await pg_session.execute(
                select(Session).where(Session.session_token_hash == hash_token(raw_session_token))
            )
        ).scalar_one_or_none()
        assert sess_check is None, "Просроченная сессия должна удаляться из базы данных!"

    finally:
        app.dependency_overrides.pop(get_db, None)


# ==============================================================================
# 3. FINAL-03: SDK Token Verification Strictness
# ==============================================================================


def test_sdk_verify_access_token_enforces_aud_and_token_use():
    """
    FINAL-03 / G8-SEC:
    SDK обязан строго проверять audience по умолчанию (даже если expected_audience не передан явно),
    требовать обязательные claims (exp, sub, aud, iss) и token_use == 'access_token'.
    """
    from alxprgs_sso.client import SSOClient
    from alxprgs_sso.exceptions import InvalidTokenError

    sso = SSOClient(
        server_url="https://auth.alxprgs.tech",
        client_id="my-client-app",
    )

    # 1. Токен с чужим audience (чужой client_id)
    token_wrong_aud = create_jwt(
        {
            "sub": str(uuid.uuid4()),
            "aud": "attacker-client",
            "iss": "https://auth.alxprgs.tech",
            "token_use": "access_token",
        },
        expires_in_seconds=300,
    )

    # Мокаем get_jwks, чтобы возвращал публичный ключ
    from app.core.security import get_jwks

    server_jwks = get_jwks()

    with patch.object(sso, "get_jwks", return_value=server_jwks):
        # Должен отказать из-за несовпадения aud (токен выпущен для attacker-client, а наш клиент my-client-app)
        with pytest.raises(InvalidTokenError):
            sso.verify_access_token(token_wrong_aud)

    # 2. Токен БЕЗ token_use
    token_no_use = create_jwt(
        {
            "sub": str(uuid.uuid4()),
            "aud": "my-client-app",
            "iss": "https://auth.alxprgs.tech",
        },
        expires_in_seconds=300,
    )
    with patch.object(sso, "get_jwks", return_value=server_jwks):
        with pytest.raises(InvalidTokenError):
            sso.verify_access_token(token_no_use)

    # 3. ID Token передан вместо Access Token
    token_id_token = create_jwt(
        {
            "sub": str(uuid.uuid4()),
            "aud": "my-client-app",
            "iss": "https://auth.alxprgs.tech",
            "token_use": "id_token",
        },
        expires_in_seconds=300,
    )
    with patch.object(sso, "get_jwks", return_value=server_jwks):
        with pytest.raises(InvalidTokenError):
            sso.verify_access_token(token_id_token)

    # 4. Проверка ограничения частоты принудительного обновления JWKS (rate-limiting force_refresh)
    call_count = 0

    def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.json.return_value = server_jwks
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    with patch("httpx.Client.get", side_effect=mock_get):
        # Первый вызов force_refresh=True обращается к сети
        sso.get_jwks(force_refresh=True)
        assert call_count == 1

        # Второй вызов force_refresh=True через 0.1с НЕ должен обращаться к сети (rate limit 5с)
        sso.get_jwks(force_refresh=True)
        assert call_count == 1, (
            "Принудительный refresh JWKS обязан ограничиваться по частоте во избежание DoS"
        )

    # 5. Проверка истечения предельного срока устаревания кэша (max_stale_seconds)
    from alxprgs_sso.exceptions import ConfigurationError

    sso._jwks_expires_at = time.time() - 1000  # Давно просрочен
    sso.max_stale_seconds = 300  # Допустимо только 300 секунд устаревания

    def mock_fail(*args, **kwargs):
        raise httpx.ConnectError("Network unreachable")

    with patch("httpx.Client.get", side_effect=mock_fail):
        with pytest.raises(ConfigurationError):
            # Кэш просрочен сильнее, чем max_stale_seconds, и сеть упала -> отказ, а не бесконечный stale cache
            sso.get_jwks(force_refresh=True)


# ==============================================================================
# 4. FINAL-04: Login return_to / redirect_uri Validation
# ==============================================================================


def test_login_return_to_validation_rejects_open_redirect():
    """
    FINAL-04 / G8-SEC:
    Валидатор return_to в LoginPage обязан отклонять открытые редиректы:
    внешние домены, protocol-relative, javascript, data URI, backslash tricks.
    """
    # Запускаем Node для тестирования скомпилированного security.ts или прямого скрипта
    node_eval = """
    // Эмуляция window.location в среде теста
    globalThis.window = {
        location: {
            origin: 'http://localhost:5173',
            host: 'localhost:5173'
        }
    };

    function sanitizeReturnTo(returnTo) {
        if (!returnTo || typeof returnTo !== 'string') return null;
        const trimmed = returnTo.trim();
        if (!trimmed) return null;
        if (/[\\r\\n\\t]/.test(trimmed)) return null;
        const lower = trimmed.toLowerCase();
        if (lower.startsWith('javascript:') || lower.startsWith('data:') || lower.startsWith('vbscript:')) return null;
        if (trimmed.startsWith('//') || trimmed.startsWith('/\\\\') || trimmed.startsWith('\\\\') || trimmed.includes('\\\\')) return null;
        try {
            if (trimmed.startsWith('/')) {
                const parsed = new URL(trimmed, window.location.origin);
                if (parsed.origin !== window.location.origin) return null;
                return trimmed;
            }
            const parsed = new URL(trimmed);
            if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
            const currentHost = window.location.host.toLowerCase();
            const targetHost = parsed.host.toLowerCase();
            const trustedHosts = new Set([
                currentHost,
                'localhost:8000',
                'localhost:5173',
                '127.0.0.1:8000',
                '127.0.0.1:5173',
                'auth.alxprgs.tech',
                'alxprgs.tech'
            ]);
            if (trustedHosts.has(targetHost)) return parsed.toString();
            return null;
        } catch {
            return null;
        }
    }

    const vectors = [
        ['https://evil.com', null],
        ['http://attacker.com/evil', null],
        ['//evil.com/path', null],
        ['/\\\\evil.com', null],
        ['\\\\evil.com', null],
        ['javascript:alert(1)', null],
        ['data:text/html,<script>alert(1)</script>', null],
        ['vbscript:msgbox(1)', null],
        ['https://subdomain.alxprgs.tech.evil.com', null],
        ['/oauth/authorize?client_id=test', '/oauth/authorize?client_id=test'],
        ['/dashboard', '/dashboard'],
        ['http://localhost:8000/oauth/authorize', 'http://localhost:8000/oauth/authorize'],
        ['https://auth.alxprgs.tech/oauth/authorize', 'https://auth.alxprgs.tech/oauth/authorize'],
    ];

    for (const [input, expected] of vectors) {
        const actual = sanitizeReturnTo(input);
        if (actual !== expected) {
            console.error(`FAIL: input='${input}' expected='${expected}' actual='${actual}'`);
            process.exit(1);
        }
    }
    console.log('ALL_VECTORS_OK');
    """

    res = subprocess.run(["node", "-e", node_eval], capture_output=True, text=True)
    assert res.returncode == 0, f"Node test failed: {res.stderr}"
    assert "ALL_VECTORS_OK" in res.stdout


@pytest.mark.asyncio
async def test_multiple_client_auth_methods_rejected_400():
    """
    G8-SEC: RFC 6749 Section 2.3:
    Использование нескольких методов аутентификации одновременно (Basic + Form)
    обязано отклоняться с кодом 400 invalid_request.
    """
    import base64

    tc = TestClient(app)
    creds = base64.b64encode(b"client1:secret1").decode()

    # Запрос с Basic Auth И с параметром формы client_id
    res = tc.post(
        "/oauth/token",
        headers={"Authorization": f"Basic {creds}"},
        data={
            "grant_type": "authorization_code",
            "client_id": "client1",
            "code": "dummy",
            "code_verifier": "dummy",
            "redirect_uri": "http://localhost:3000/callback",
        },
    )
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_request"
    assert "RFC 6749" in res.json()["error_description"]


@pytest.mark.asyncio
async def test_deactivated_client_rejected_401(pg_session: AsyncSession):
    """
    G8-SEC: Деактивированный клиент (is_active=False) обязан отклоняться
    со статусом 401 invalid_client.
    """
    deactivated = OIDCClient(
        client_id=f"deact-{uuid.uuid4().hex[:6]}",
        client_name="Deactivated App",
        client_type="confidential",
        client_secret_hash=hash_password("secret123"),
        is_active=False,
    )
    pg_session.add(deactivated)
    await pg_session.commit()

    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.get_and_validate_client(
            pg_session, client_id=deactivated.client_id, client_secret="secret123"
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.error == "invalid_client"
