from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKSet

from alxprgs_sso.exceptions import (
    ConfigurationError,
    InvalidTokenError,
    SSOError,
    TokenExpiredError,
)
from alxprgs_sso.models import TokenResponse, UserClaims, WebSessionInfo


class SSOClient:
    """
    Основной клиент взаимодействия с сервером ALXPRGS SSO.
    """

    def __init__(
        self,
        server_url: str,
        client_id: str,
        client_secret: str | None = None,
        jwks_cache_ttl_seconds: int = 3600,
        verify_ssl: bool = True,
        expected_issuer: str | None = None,
        expected_audience: str | None = None,
        max_stale_seconds: int = 300,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwks_cache_ttl_seconds = jwks_cache_ttl_seconds
        self.verify_ssl = verify_ssl
        self.expected_issuer = expected_issuer
        self.expected_audience = expected_audience
        self.max_stale_seconds = max_stale_seconds

        self._cached_jwks: dict[str, Any] | None = None
        self._jwks_expires_at: float = 0.0
        self._last_force_refresh_at: float = 0.0
        self._min_force_refresh_interval: float = 5.0

    # --------------------------------------------------------------------------
    # JWKS кэширование (SDK-02)
    # --------------------------------------------------------------------------

    def get_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        """
        Синхронное получение JWKS с сервера или из локального кэша (SDK-02).
        Поддерживает ограниченный период устаревания кэша и rate-limiting force_refresh.
        """
        now = time.time()
        if force_refresh:
            if now - self._last_force_refresh_at < self._min_force_refresh_interval:
                if self._cached_jwks and now < (self._jwks_expires_at + self.max_stale_seconds):
                    return self._cached_jwks
            self._last_force_refresh_at = now
        elif self._cached_jwks and now < self._jwks_expires_at:
            return self._cached_jwks

        jwks_url = f"{self.server_url}/.well-known/jwks.json"
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=10.0) as client:
                resp = client.get(jwks_url)
                resp.raise_for_status()
                data = resp.json()
                self._cached_jwks = data
                self._jwks_expires_at = now + self.jwks_cache_ttl_seconds
                return data
        except Exception as e:
            if self._cached_jwks and now < (self._jwks_expires_at + self.max_stale_seconds):
                return self._cached_jwks
            raise ConfigurationError(f"Не удалось загрузить JWKS из {jwks_url}: {e}")

    async def get_jwks_async(self, force_refresh: bool = False) -> dict[str, Any]:
        """
        Асинхронное получение JWKS с сервера или из локального кэша (SDK-02).
        """
        now = time.time()
        if force_refresh:
            if now - self._last_force_refresh_at < self._min_force_refresh_interval:
                if self._cached_jwks and now < (self._jwks_expires_at + self.max_stale_seconds):
                    return self._cached_jwks
            self._last_force_refresh_at = now
        elif self._cached_jwks and now < self._jwks_expires_at:
            return self._cached_jwks

        jwks_url = f"{self.server_url}/.well-known/jwks.json"
        try:
            async with httpx.AsyncClient(verify=self.verify_ssl, timeout=10.0) as client:
                resp = await client.get(jwks_url)
                resp.raise_for_status()
                data = resp.json()
                self._cached_jwks = data
                self._jwks_expires_at = now + self.jwks_cache_ttl_seconds
                return data
        except Exception as e:
            if self._cached_jwks and now < (self._jwks_expires_at + self.max_stale_seconds):
                return self._cached_jwks
            raise ConfigurationError(f"Не удалось загрузить JWKS из {jwks_url}: {e}")

    def _get_signing_key(self, token_or_header: str | dict[str, Any]) -> Any:
        if isinstance(token_or_header, str):
            try:
                unverified_header = jwt.get_unverified_header(token_or_header)
            except Exception as e:
                raise InvalidTokenError(f"Некорректный заголовок JWT: {e}")
        else:
            unverified_header = token_or_header

        kid = unverified_header.get("kid")
        jwks_data = self.get_jwks()
        jwk_set = PyJWKSet.from_dict(jwks_data)

        signing_key = None
        for key in jwk_set.keys:
            if key.key_id == kid or not kid:
                signing_key = key
                break

        if not signing_key:
            # Возможно, ключи были ротированы: попробуем обновить кэш JWKS
            jwks_data = self.get_jwks(force_refresh=True)
            jwk_set = PyJWKSet.from_dict(jwks_data)
            for key in jwk_set.keys:
                if key.key_id == kid:
                    signing_key = key
                    break

        if not signing_key:
            raise InvalidTokenError(f"Ключ подписи с kid='{kid}' не найден в JWKS сервера")
        return signing_key

    # --------------------------------------------------------------------------
    # Валидация токенов (SDK-02, SSO-03)
    # --------------------------------------------------------------------------

    def verify_access_token(
        self,
        token: str,
        expected_audience: str | None = None,
        expected_issuer: str | None = None,
    ) -> UserClaims:
        """
        Валидирует Access Token:
        - Проверяет заголовок и находит ключ kid в JWKS;
        - Проверяет RS256 подпись;
        - Проверяет exp / nbf / iss / aud;
        - Отклоняет ID Token в качестве Access Token (инвариант SSO-03).
        """
        if not token or not isinstance(token, str):
            raise InvalidTokenError("Токен отсутствует или имеет неверный формат")

        signing_key = self._get_signing_key(token)

        target_issuer = expected_issuer or self.expected_issuer or self.server_url
        target_audience = expected_audience or self.expected_audience or self.client_id
        decode_options: Any = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iat": True,
            "verify_aud": True,
            "verify_iss": bool(target_issuer),
            "require": ["exp", "sub", "aud", "iss"],
        }

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options=decode_options,
                audience=target_audience,
                issuer=target_issuer,
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError(f"Срок действия токена истёк: {e}")
        except jwt.InvalidTokenError as e:
            raise InvalidTokenError(f"Недействительная подпись или атрибуты токена: {e}")

        # Инвариант SSO-03 / G8-SEC: Строго требовать access_token (ID Token и токены без token_use запрещены)
        token_use = payload.get("token_use")
        if token_use != "access_token":
            if token_use == "id_token":
                raise InvalidTokenError("Недопустимо использовать ID Token в качестве Access Token")
            raise InvalidTokenError(
                f"Недопустимый token_use='{token_use}'. Токен не является валидным Access Token"
            )

        return UserClaims(
            sub=str(payload.get("sub", "")),
            preferred_username=str(payload.get("preferred_username", "")),
            email=payload.get("email"),
            email_verified=bool(payload.get("email_verified", False)),
            roles=list(payload.get("roles", [])),
        )

    # --------------------------------------------------------------------------
    # Авторизационный поток Web Application (SDK-04, PKCE S256)
    # --------------------------------------------------------------------------

    def start_authorization(
        self,
        redirect_uri: str,
        scope: str = "openid profile email",
        state: str | None = None,
        nonce: str | None = None,
    ) -> tuple[str, str, str, str]:
        """
        Формирует URL перенаправления пользователя на OIDC Authorization Server (SDK-03, RFC 7636).
        Генерирует PKCE code_verifier, S256 code_challenge, state для защиты от CSRF
        и nonce для криптографической привязки ID токена к сессии браузера.

        Возвращает: (authorization_url, code_verifier, state, nonce)
        """
        code_verifier = secrets.token_urlsafe(64)[:96]
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

        actual_state = state or secrets.token_urlsafe(24)
        actual_nonce = nonce or secrets.token_urlsafe(24)

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": actual_state,
            "nonce": actual_nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        url = f"{self.server_url}/oauth/authorize?{urlencode(params)}"
        return url, code_verifier, actual_state, actual_nonce

    def generate_authorization_url(
        self,
        redirect_uri: str,
        scope: str = "openid profile email",
        state: str | None = None,
    ) -> tuple[str, str, str]:
        """
        Устаревший метод для обратной совместимости. Рекомендуется использовать start_authorization().
        """
        auth_url, verifier, state_val, _ = self.start_authorization(
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
        )
        return auth_url, verifier, state_val

    def verify_id_token(
        self,
        id_token: str,
        expected_nonce: str | None = None,
    ) -> dict[str, Any]:
        """
        Валидирует OIDC ID Token (OpenID Connect Core 1.0, SDK-03):
        - Проверка подписи асимметричным ключом RSA через JWKS;
        - Проверка срока действия exp, nbf, iat;
        - Проверка token_use == 'id_token';
        - Проверка соответствия nonce ожидаемому значению из сессии браузера.
        """
        if not id_token or not isinstance(id_token, str):
            raise InvalidTokenError("ID токен отсутствует или имеет неверный формат")

        signing_key = self._get_signing_key(id_token)

        decode_options: Any = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iat": True,
            "verify_aud": True,
            "verify_iss": True,
            "require": ["exp", "sub", "aud", "iss"],
        }
        target_issuer = self.expected_issuer or (
            self.server_url
            if self.server_url.startswith("https://") or "auth.alxprgs.tech" in self.server_url
            else None
        )
        try:
            payload = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                options=decode_options,
                audience=self.client_id,
                issuer=target_issuer,
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError(f"Срок действия ID токена истёк: {e}")
        except jwt.InvalidTokenError as e:
            raise InvalidTokenError(f"Недействительный ID токен: {e}")

        if payload.get("token_use") != "id_token":
            raise InvalidTokenError("Токен не является валидным ID Token (token_use != 'id_token')")

        if expected_nonce is not None:
            token_nonce = payload.get("nonce")
            if not token_nonce or not secrets.compare_digest(token_nonce, expected_nonce):
                raise InvalidTokenError(
                    "Значение claim 'nonce' в ID токене не совпадает с ожидаемым"
                )

        return payload

    async def handle_web_callback(
        self,
        code: str,
        state: str,
        expected_state: str,
        code_verifier: str,
        redirect_uri: str,
        expected_nonce: str | None = None,
    ) -> WebSessionInfo:
        """
        Завершает авторизационный callback веб-приложения (SDK-03/06):
        1. Сверяет state с ожидаемым для защиты от CSRF.
        2. Обменивает authorization code и code_verifier на токены.
        3. Валидирует полученный ID Token и значение nonce.
        4. Валидирует Access Token и извлекает типизированные UserClaims.
        """
        if not secrets.compare_digest(state, expected_state):
            raise InvalidTokenError("Неверный параметр state: возможна попытка CSRF-атаки")

        tokens = await self.exchange_code_for_tokens(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )

        id_token_claims = None
        if tokens.id_token:
            id_token_claims = self.verify_id_token(
                id_token=tokens.id_token,
                expected_nonce=expected_nonce,
            )

        claims = self.verify_access_token(tokens.access_token)

        return WebSessionInfo(
            user=claims,
            access_token=tokens.access_token,
            id_token=tokens.id_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
            id_token_claims=id_token_claims,
        )

    def create_logout_url(
        self,
        post_logout_redirect_uri: str | None = None,
        state: str | None = None,
    ) -> str:
        """
        Формирует URL выхода RP-Initiated Logout (SSO-07).
        """
        base = f"{self.server_url}/oauth/logout"
        params: dict[str, str] = {}
        if post_logout_redirect_uri:
            params["post_logout_redirect_uri"] = post_logout_redirect_uri
        if state:
            params["state"] = state
        if params:
            return f"{base}?{urlencode(params)}"
        return base

    async def exchange_code_for_tokens(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> TokenResponse:
        """
        Обменивает авторизационный код и code_verifier на Access/ID/Refresh токены.
        """
        token_url = f"{self.server_url}/oauth/token"
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "client_id": self.client_id,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=15.0) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code != 200:
                err_body = resp.text
                try:
                    err_json = resp.json()
                    err_desc = (
                        err_json.get("error_description") or err_json.get("error") or err_body
                    )
                except Exception:
                    err_desc = err_body
                raise SSOError(f"Ошибка обмена кода авторизации: {err_desc}")

            payload = resp.json()
            return TokenResponse(**payload)

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """
        Выполняет ротацию Refresh Token.
        """
        token_url = f"{self.server_url}/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=15.0) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code != 200:
                raise SSOError(f"Ошибка обновления токена: {resp.text}")
            return TokenResponse(**resp.json())

    async def revoke_token(self, token: str, token_type_hint: str = "refresh_token") -> bool:
        """
        Отзыв токена по RFC 7009.
        """
        revoke_url = f"{self.server_url}/oauth/revoke"
        data = {
            "token": token,
            "token_type_hint": token_type_hint,
            "client_id": self.client_id,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=10.0) as client:
            resp = await client.post(revoke_url, data=data)
            return resp.status_code == 200
