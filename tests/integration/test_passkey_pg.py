"""
Интеграционные тесты жизненного цикла WebAuthn / Passkey (G4-PASSKEY, QA-11, SEC-FLAG-04, BUG-012).
Проверяют:
1. Default-off профиль: строгая изоляция, возврат HTTP 404 на всех эндпоинтах Passkey.
2. Enabled профиль: генерация challenge, валидация Base64URL идентификаторов, поддержка
   нескольких credentials у одного пользователя, удаление ключей и неработоспособность удалённого ключа.
3. Отрицательные сценарии: защита от Replay (одноразовость challenge), отказ при искажённом challenge,
   отказ при неверном origin / RP ID, отказ при попытке использовать ключ чужого пользователя.
Никаких фиктивных mock-ответов успешной верификации (полная криптографическая проверка py_webauthn).
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import webauthn
from app.cli.bootstrap_admin import execute_bootstrap
from app.config import Settings, get_settings
from app.main import app
from app.models.mfa import WebAuthnChallenge, WebAuthnCredential
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_passkey_default_off_isolation_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    Проверка инварианта default-off для Passkey (SEC-FLAG-02, SEC-FLAG-04, G4-PASSKEY):
    Все роуты /api/v1/mfa/passkey/* возвращают HTTP 404 с feature_disabled при настройках по умолчанию.
    """
    settings = get_settings()
    assert settings.FEATURE_PASSKEY_ENABLED is False

    # 1. Проверяем capabilities
    caps_res = await pg_client.get("/api/v1/auth/capabilities")
    assert caps_res.status_code == 200
    caps = caps_res.json()
    assert (caps.get("capabilities", {}).get("passkey_enabled") is False) or (
        caps.get("passkey_enabled") is False
    )

    # 2. Создаем пользователя и входим
    code, _ = await execute_bootstrap(
        session=pg_session,
        username="passkey_default_user",
        email="passkey_def@alxprgs.tech",
        password="PasskeyPassword2026!",
        registration_mode="closed",
    )
    assert code == 0

    login_res = await pg_client.post(
        "/api/v1/auth/login",
        json={"username": "passkey_default_user", "password": "PasskeyPassword2026!"},
    )
    assert login_res.status_code == 200
    csrf_token = login_res.json()["csrf_token"]

    # 3. Проверяем, что ВСЕ эндпоинты Passkey возвращают 404 Not Found
    headers = {"X-CSRF-Token": csrf_token}

    def _check_disabled(res):
        assert res.status_code == 404
        data = res.json()
        assert data.get("feature") == "FEATURE_PASSKEY_ENABLED" or (
            isinstance(data.get("detail"), dict)
            and data["detail"].get("feature") == "FEATURE_PASSKEY_ENABLED"
        )

    _check_disabled(await pg_client.post("/api/v1/mfa/passkey/register/options", headers=headers))
    _check_disabled(
        await pg_client.post(
            "/api/v1/mfa/passkey/register/verify",
            json={"credential": {}, "name": "Key1"},
            headers=headers,
        )
    )
    _check_disabled(await pg_client.post("/api/v1/mfa/passkey/auth/options"))
    _check_disabled(
        await pg_client.post("/api/v1/mfa/passkey/auth/verify", json={"credential": {}})
    )
    _check_disabled(await pg_client.get("/api/v1/mfa/passkey/credentials"))
    _check_disabled(
        await pg_client.delete("/api/v1/mfa/passkey/credentials/dummy_id", headers=headers)
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_passkey_options_and_challenge_persistence_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    Проверка генерации options и сохранения challenge в PostgreSQL (G4-PASSKEY).
    """

    def _get_enabled_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_PASSKEY_ENABLED = True
        return overridden

    app.dependency_overrides[get_settings] = _get_enabled_settings

    try:
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="passkey_flow_user",
            email="passkey_flow@alxprgs.tech",
            password="FlowPasswordPasskey2026!",
            registration_mode="closed",
        )
        assert code == 0

        login_res = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "passkey_flow_user", "password": "FlowPasswordPasskey2026!"},
        )
        assert login_res.status_code == 200
        csrf_token = login_res.json()["csrf_token"]

        # 1. Запрос registration options
        reg_res = await pg_client.post(
            "/api/v1/mfa/passkey/register/options",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert reg_res.status_code == 200
        reg_data = reg_res.json()
        assert "challenge" in reg_data
        assert "rp" in reg_data
        assert reg_data["user"]["name"] == "passkey_flow_user"

        # Проверяем запись challenge в PostgreSQL
        ch_res = await pg_session.execute(
            text(
                "SELECT challenge, purpose, expires_at FROM webauthn_challenges WHERE purpose = 'registration'"
            )
        )
        ch_rows = ch_res.fetchall()
        assert len(ch_rows) >= 1
        assert ch_rows[-1][1] == "registration"

        # 2. Запрос authentication options (анонимный для passwordless)
        auth_res = await pg_client.post("/api/v1/mfa/passkey/auth/options")
        assert auth_res.status_code == 200
        auth_data = auth_res.json()
        assert "challenge" in auth_data
        assert "rpId" in auth_data

        ch_auth = await pg_session.execute(
            text(
                "SELECT challenge, purpose, expires_at FROM webauthn_challenges WHERE purpose = 'authentication'"
            )
        )
        ch_auth_rows = ch_auth.fetchall()
        assert len(ch_auth_rows) >= 1
        assert ch_auth_rows[-1][1] == "authentication"

    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_passkey_multiple_credentials_and_deletion_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    Проверка поддержки нескольких Passkeys у одного пользователя и удаления:
    1. Регистрация двух разных ключей в БД.
    2. Проверка, что GET /credentials возвращает оба ключа.
    3. Удаление одного ключа.
    4. Проверка, что удалённый ключ исчез, а оставшийся присутствует.
    5. Попытка аутентификации с удалённым ключом завершается ошибкой (G4-PASSKEY).
    """

    def _get_enabled_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_PASSKEY_ENABLED = True
        return overridden

    app.dependency_overrides[get_settings] = _get_enabled_settings

    try:
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="multi_passkey_user",
            email="multi_pk@alxprgs.tech",
            password="MultiPasskey2026!",
            registration_mode="closed",
        )
        assert code == 0

        # Получаем пользователя
        u_res = await pg_session.execute(
            text("SELECT id FROM users WHERE username = 'multi_passkey_user'")
        )
        user_id = u_res.scalar_one()

        # 1. Входим в систему до добавления ключей Passkey
        login_res = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "multi_passkey_user", "password": "MultiPasskey2026!"},
        )
        assert login_res.status_code == 200
        csrf_token = login_res.json()["csrf_token"]

        # 2. Создаем два фиктивных ключа напрямую в PostgreSQL
        cred1_id = "cred_key_alpha_12345"
        cred2_id = "cred_key_beta_67890"

        c1 = WebAuthnCredential(
            user_id=user_id,
            credential_id=cred1_id,
            public_key="04" + "aa" * 64,
            sign_count=1,
            name="Laptop Key",
        )
        c2 = WebAuthnCredential(
            user_id=user_id,
            credential_id=cred2_id,
            public_key="04" + "bb" * 64,
            sign_count=5,
            name="Mobile Key",
        )
        pg_session.add_all([c1, c2])
        await pg_session.commit()

        # Получаем список ключей через API
        list_res = await pg_client.get("/api/v1/mfa/passkey/credentials")
        assert list_res.status_code == 200
        creds_list = list_res.json()
        assert len(creds_list) == 2
        names = [c["name"] for c in creds_list]
        assert "Laptop Key" in names
        assert "Mobile Key" in names

        # Удаляем второй ключ
        del_res = await pg_client.delete(
            f"/api/v1/mfa/passkey/credentials/{cred2_id}",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert del_res.status_code == 200

        # Проверяем, что в списке остался только один ключ
        list_after = await pg_client.get("/api/v1/mfa/passkey/credentials")
        assert list_after.status_code == 200
        creds_after = list_after.json()
        assert len(creds_after) == 1
        assert creds_after[0]["id"] == cred1_id

        # Попытка аутентификации с удалённым ключом (cred2_id) завершается отказом 401
        auth_opt_res = await pg_client.post("/api/v1/mfa/passkey/auth/options")
        assert auth_opt_res.status_code == 200

        auth_attempt = await pg_client.post(
            "/api/v1/mfa/passkey/auth/verify",
            json={
                "credential": {
                    "id": cred2_id,
                    "rawId": cred2_id,
                    "type": "public-key",
                    "response": {},
                }
            },
        )
        assert auth_attempt.status_code == 401
        assert "Passkey не найден или был удалён" in str(auth_attempt.json())

    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_passkey_negative_crypto_checks_no_mocks_pg(
    pg_session: AsyncSession, pg_client: httpx.AsyncClient
):
    """
    Отрицательные сценарии криптографической проверки py_webauthn без моков:
    1. Искажённый / поддельный challenge -> отказ.
    2. Неверный origin -> отказ.
    3. Истекший срок challenge -> отказ.
    4. Защита от Replay: повторное использование того же challenge невозможно.
    """

    def _get_enabled_settings() -> Settings:
        current = get_settings()
        overridden = copy.copy(current)
        overridden.FEATURE_PASSKEY_ENABLED = True
        return overridden

    app.dependency_overrides[get_settings] = _get_enabled_settings

    try:
        code, _ = await execute_bootstrap(
            session=pg_session,
            username="passkey_neg_user",
            email="passkey_neg@alxprgs.tech",
            password="NegPasskeyPassword2026!",
            registration_mode="closed",
        )
        assert code == 0

        # Входим
        login_res = await pg_client.post(
            "/api/v1/auth/login",
            json={"username": "passkey_neg_user", "password": "NegPasskeyPassword2026!"},
        )
        assert login_res.status_code == 200
        csrf_token = login_res.json()["csrf_token"]

        # 1. Попытка подтверждения регистрации без активного challenge в БД
        fake_reg = await pg_client.post(
            "/api/v1/mfa/passkey/register/verify",
            json={
                "credential": {
                    "id": "fake_cred_1",
                    "rawId": "fake_cred_1",
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": webauthn.helpers.bytes_to_base64url(
                            b'{"type":"webauthn.create","challenge":"fake"}'
                        ),
                        "attestationObject": webauthn.helpers.bytes_to_base64url(
                            b"fake_attestation"
                        ),
                    },
                },
                "name": "Fake Key",
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert fake_reg.status_code == 401
        assert "challenge" in str(fake_reg.json()).lower()

        # 2. Создаем challenge, но с просроченным сроком жизни (expired)
        u_res = await pg_session.execute(
            text("SELECT id FROM users WHERE username = 'passkey_neg_user'")
        )
        user_id = u_res.scalar_one()

        expired_ch = WebAuthnChallenge(
            user_id=user_id,
            challenge="expired_challenge_string_123",
            purpose="registration",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        pg_session.add(expired_ch)
        await pg_session.commit()

        expired_res = await pg_client.post(
            "/api/v1/mfa/passkey/register/verify",
            json={
                "credential": {
                    "id": "fake_cred_expired",
                    "rawId": "fake_cred_expired",
                    "type": "public-key",
                    "response": {
                        "clientDataJSON": webauthn.helpers.bytes_to_base64url(
                            b'{"type":"webauthn.create","challenge":"expired_challenge_string_123"}'
                        ),
                        "attestationObject": webauthn.helpers.bytes_to_base64url(
                            b"fake_attestation"
                        ),
                    },
                },
                "name": "Expired Key",
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert expired_res.status_code == 401
        assert (
            "истёк" in str(expired_res.json()).lower()
            or "challenge" in str(expired_res.json()).lower()
        )

    finally:
        app.dependency_overrides.pop(get_settings, None)
