import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from tests.helpers.privacy import record_test_consent

sys.path.insert(0, os.path.abspath("backend"))

from app.config import get_settings
from app.core.exceptions import OAuthErrorException
from app.core.security import (
    create_jwt,
    decode_jwt,
    get_jwks,
    hash_password,
    hash_token,
    rotate_active_signing_key,
)
from app.main import app
from app.models.oidc import OIDCClient, OIDCRedirectUri, RefreshToken
from app.models.user import PasswordCredential, Role, User
from app.services.oidc_service import OIDCService

settings = get_settings()


async def _create_test_user_and_client(db, client_type="confidential"):
    user_stmt = select(User).where(User.username == "sso_tester")
    user = (await db.execute(user_stmt)).scalar_one_or_none()
    if not user:
        user = User(
            id=uuid.uuid4(),
            username="sso_tester",
            email="tester@alxprgs.tech",
            email_verified=True,
            is_active=True,
        )
        user.password_credential = PasswordCredential(
            password_hash=hash_password("SuperSecret123!")
        )
        role_stmt = select(Role).where(Role.name == "user")
        role = (await db.execute(role_stmt)).scalar_one_or_none()
        if not role:
            role = Role(name="user", description="Default user")
            db.add(role)
        user.roles.append(role)
        db.add(user)

    client_id = f"test-client-{uuid.uuid4().hex[:8]}"
    secret = "ClientSecret123!" if client_type == "confidential" else None
    client_obj = OIDCClient(
        id=uuid.uuid4(),
        client_id=client_id,
        client_secret_hash=hash_password(secret) if secret else None,
        client_name="Test SSO Client",
        client_type=client_type,
        is_active=True,
    )
    db.add(client_obj)
    await db.flush()

    redirect_uri = "https://app.alxprgs.tech/callback"
    db.add(OIDCRedirectUri(client_id=client_obj.id, uri=redirect_uri))
    await db.commit()
    await record_test_consent(db, user)
    return user, client_obj, secret, redirect_uri


@pytest.mark.asyncio
async def test_sso_discovery_endpoint_contract():
    """Проверка актуальности и соответствия Discovery Endpoint (SSO-01, RFC 8414)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/.well-known/openid-configuration")
        assert res.status_code == 200
        data = res.json()
        assert data["issuer"] == settings.OIDC_ISSUER
        assert "authorization_code" in data["grant_types_supported"]
        assert "refresh_token" in data["grant_types_supported"]
        assert "code" in data["response_types_supported"]
        assert "query" in data["response_modes_supported"]
        assert "S256" in data["code_challenge_methods_supported"]
        assert "openid" in data["scopes_supported"]
        assert "profile" in data["scopes_supported"]
        assert "email" in data["scopes_supported"]
        assert "client_secret_basic" in data["token_endpoint_auth_methods_supported"]
        assert "client_secret_post" in data["token_endpoint_auth_methods_supported"]
        assert "none" in data["token_endpoint_auth_methods_supported"]


@pytest.mark.asyncio
async def test_authorize_scope_validation_negative(pg_session):
    """Отрицательные проверки scope: отсутствие openid и неизвестные scopes отклоняются (400 invalid_scope)."""
    user, client_obj, secret, redirect_uri = await _create_test_user_and_client(pg_session)

    # 1. Отсутствие scope 'openid'
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get(
            "/oauth/authorize",
            params={
                "client_id": client_obj.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "profile email",  # без openid
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
            },
        )
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_scope"

        # 2. Неизвестный/неподдерживаемый scope
        res2 = await client.get(
            "/oauth/authorize",
            params={
                "client_id": client_obj.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid super_admin_write",
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
            },
        )
        assert res2.status_code == 400
        assert res2.json()["error"] == "invalid_scope"


@pytest.mark.asyncio
async def test_scope_claims_filtering_access_token_id_token_userinfo(pg_session):
    """
    Инвариант SSO-04 / FINAL-11:
    Claims email/profile выдаются строго при наличии запрошенного разрешения в scope.
    """
    user, client_obj, secret, redirect_uri = await _create_test_user_and_client(pg_session)

    # Сценарий А: Только scope 'openid'
    tokens_openid = await OIDCService._generate_tokens_for_user(
        db=pg_session,
        user=user,
        client=client_obj,
        scope="openid",
    )
    # Access token payload
    acc_payload_a = decode_jwt(tokens_openid.access_token)
    assert acc_payload_a["sub"] == str(user.id)
    assert "email" not in acc_payload_a
    assert "email_verified" not in acc_payload_a
    assert "preferred_username" not in acc_payload_a

    # ID token payload
    assert tokens_openid.id_token is not None
    id_payload_a = decode_jwt(tokens_openid.id_token)
    assert id_payload_a["sub"] == str(user.id)
    assert "email" not in id_payload_a
    assert "preferred_username" not in id_payload_a

    # UserInfo с токеном 'openid'
    userinfo_a = await OIDCService.get_userinfo(pg_session, tokens_openid.access_token)
    assert userinfo_a.sub == str(user.id)
    assert userinfo_a.email is None
    assert userinfo_a.preferred_username is None

    # Сценарий Б: Scope 'openid email' (без profile)
    tokens_email = await OIDCService._generate_tokens_for_user(
        db=pg_session,
        user=user,
        client=client_obj,
        scope="openid email",
    )
    acc_payload_b = decode_jwt(tokens_email.access_token)
    assert acc_payload_b["email"] == user.email
    assert acc_payload_b["email_verified"] is True
    assert "preferred_username" not in acc_payload_b

    userinfo_b = await OIDCService.get_userinfo(pg_session, tokens_email.access_token)
    assert userinfo_b.email == user.email
    assert userinfo_b.email_verified is True
    assert userinfo_b.preferred_username is None

    # Сценарий В: Scope 'openid profile' (без email)
    tokens_profile = await OIDCService._generate_tokens_for_user(
        db=pg_session,
        user=user,
        client=client_obj,
        scope="openid profile",
    )
    acc_payload_c = decode_jwt(tokens_profile.access_token)
    assert acc_payload_c["preferred_username"] == user.username
    assert "email" not in acc_payload_c

    userinfo_c = await OIDCService.get_userinfo(pg_session, tokens_profile.access_token)
    assert userinfo_c.preferred_username == user.username
    assert userinfo_c.email is None

    # Сценарий Г: Scope 'openid profile email' (полный)
    tokens_full = await OIDCService._generate_tokens_for_user(
        db=pg_session,
        user=user,
        client=client_obj,
        scope="openid profile email",
    )
    acc_payload_d = decode_jwt(tokens_full.access_token)
    assert acc_payload_d["preferred_username"] == user.username
    assert acc_payload_d["email"] == user.email
    userinfo_d = await OIDCService.get_userinfo(pg_session, tokens_full.access_token)
    assert userinfo_d.preferred_username == user.username
    assert userinfo_d.email == user.email


@pytest.mark.asyncio
async def test_refresh_token_family_absolute_lifetime(pg_session):
    """
    Инвариант SSO-05 / FINAL-11:
    Семейство refresh токенов ограничено максимальным абсолютным сроком жизни.
    Ротация не может продлевать жизнь семейства сверх REFRESH_FAMILY_MAX_LIFETIME_SECONDS.
    """
    user, client_obj, secret, redirect_uri = await _create_test_user_and_client(pg_session)

    # 1. Выпускаем начальный refresh token
    tokens = await OIDCService._generate_tokens_for_user(
        db=pg_session,
        user=user,
        client=client_obj,
        scope="openid profile email",
    )
    first_rt = tokens.refresh_token

    # 2. Ротируем штатно — должно пройти успешно
    rot1 = await OIDCService.rotate_refresh_token(
        db=pg_session,
        client_id=client_obj.client_id,
        client_secret=secret,
        raw_refresh_token=first_rt,
    )
    assert rot1.refresh_token is not None

    # 3. Имитируем, что первый токен семейства был создан более 30 дней назад
    # Получаем family_id
    token_hash_rot1 = hash_token(rot1.refresh_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash_rot1)
    rt_obj = (await pg_session.execute(stmt)).scalar_one()

    # Сдвигаем дату создания всех предыдущих токенов семейства далеко в прошлое
    past_time = datetime.now(timezone.utc) - timedelta(
        seconds=settings.REFRESH_FAMILY_MAX_LIFETIME_SECONDS + 100
    )
    await pg_session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == rt_obj.family_id)
        .values(created_at=past_time)
    )
    await pg_session.commit()

    # 4. Попытка ротировать токен просроченного семейства должна отклониться
    with pytest.raises(OAuthErrorException) as exc_info:
        await OIDCService.rotate_refresh_token(
            db=pg_session,
            client_id=client_obj.client_id,
            client_secret=secret,
            raw_refresh_token=rot1.refresh_token,
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.error == "invalid_grant"
    assert "семейств" in exc_info.value.error_description.lower()

    # Проверяем, что вся семья отозвана
    stmt_all = select(RefreshToken.is_revoked).where(RefreshToken.family_id == rt_obj.family_id)
    revoked_statuses = (await pg_session.execute(stmt_all)).scalars().all()
    assert all(revoked_statuses)


@pytest.mark.asyncio
async def test_signing_key_rotation_kid_and_overlap(pg_session):
    """
    Инвариант SSO-06 / FINAL-11:
    Ротация ключей подписи с kid, период перекрытия (одновременная публикация в JWKS),
    прием токенов предыдущего ключа и строгий отказ при неизвестном kid.
    """
    # 1. Запоминаем текущий JWKS
    jwks_initial = get_jwks()
    active_kid = jwks_initial["keys"][0]["kid"]

    # Создаем токен активным ключом
    token_active = create_jwt({"sub": "user-active", "aud": "client-1"}, expires_in_seconds=300)
    decoded_active = decode_jwt(token_active, audience="client-1")
    assert decoded_active["sub"] == "user-active"

    # 2. Выполняем ротацию активного ключа: старый ключ уходит в retired
    new_kid = f"rotated-key-{uuid.uuid4().hex[:6]}"
    rotate_active_signing_key(new_kid=new_kid)

    # 3. JWKS теперь содержит ОБА ключа (активный + предыдущий для периода перекрытия)
    jwks_rotated = get_jwks()
    kids_in_jwks = [k["kid"] for k in jwks_rotated["keys"]]
    assert new_kid in kids_in_jwks
    assert active_kid in kids_in_jwks

    # 4. Токен, подписанный старым ключом, ВСЁ ЕЩЁ успешно декодируется в период перекрытия!
    decoded_old = decode_jwt(token_active, audience="client-1")
    assert decoded_old["sub"] == "user-active"

    # 5. Новый токен подписывается новым kid
    token_new = create_jwt({"sub": "user-new", "aud": "client-1"}, expires_in_seconds=300)
    unverified_header = jwt.get_unverified_header(token_new)
    assert unverified_header["kid"] == new_kid
    decoded_new = decode_jwt(token_new, audience="client-1")
    assert decoded_new["sub"] == "user-new"

    # 6. Токен с неизвестным kid отклоняется (401 invalid_token)
    from cryptography.hazmat.primitives.asymmetric import rsa

    alien_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    alien_token = jwt.encode(
        {"sub": "attacker", "aud": "client-1", "iss": settings.OIDC_ISSUER},
        alien_key,
        algorithm="RS256",
        headers={"kid": "unknown-alien-kid"},
    )
    with pytest.raises(OAuthErrorException) as exc_info:
        decode_jwt(alien_token, audience="client-1")
    assert exc_info.value.status_code == 401
    assert exc_info.value.error == "invalid_token"
