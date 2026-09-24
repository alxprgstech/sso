from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import jwt
from jwt import PyJWKSet

from alxprgs_sso.exceptions import (
    ConfigurationError,
    InvalidTokenError,
    SSOError,
    TokenExpiredError,
)
from alxprgs_sso.models import TokenResponse, UserClaims


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
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwks_cache_ttl_seconds = jwks_cache_ttl_seconds
        self.verify_ssl = verify_ssl
        self.expected_issuer = expected_issuer

        self._cached_jwks: dict[str, Any] | None = None
        self._jwks_expires_at: float = 0.0

    # --------------------------------------------------------------------------
    # JWKS кэширование (SDK-02)
    # --------------------------------------------------------------------------

    def get_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        """
        Синхронное получение JWKS с сервера или из локального кэша.
        """
        now = time.time()
        if not force_refresh and self._cached_jwks and now < self._jwks_expires_at:
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
            if self._cached_jwks:
                return self._cached_jwks
            raise ConfigurationError(f"Не удалось загрузить JWKS из {jwks_url}: {e}")

    async def get_jwks_async(self, force_refresh: bool = False) -> dict[str, Any]:
        """
        Асинхронное получение JWKS с сервера или из локального кэша.
        """
        now = time.time()
        if not force_refresh and self._cached_jwks and now < self._jwks_expires_at:
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
            if self._cached_jwks:
                return self._cached_jwks
            raise ConfigurationError(f"Не удалось загрузить JWKS из {jwks_url}: {e}")

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

        jwks_data = self.get_jwks()
        jwk_set = PyJWKSet.from_dict(jwks_data)

        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as e:
            raise InvalidTokenError(f"Некорректный заголовок JWT: {e}")

        kid = unverified_header.get("kid")
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

        target_issuer = expected_issuer or self.expected_issuer or self.server_url
        decode_options = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iat": True,
            "verify_aud": bool(expected_audience),
            "verify_iss": bool(target_issuer),
        }

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options=decode_options,
                audience=expected_audience or self.client_id,
                issuer=target_issuer,
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError(f"Срок действия токена истёк: {e}")
        except jwt.InvalidTokenError as e:
            raise InvalidTokenError(f"Недействительная подпись или атрибуты токена: {e}")

        # Инвариант SSO-03: Не принимать ID token вместо access token
        token_use = payload.get("token_use")
        if token_use == "id_token":
            raise InvalidTokenError("Недопустимо использовать ID Token в качестве Access Token")

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

    def generate_authorization_url(
        self,
        redirect_uri: str,
        scope: str = "openid profile email",
        state: str | None = None,
    ) -> tuple[str, str, str]:
        """
        Формирует URL перенаправления пользователя на OIDC Authorization Server.
        Генерирует криптографически стойкие PKCE code_verifier и code_challenge (S256).

        Возвращает: (authorization_url, code_verifier, state)
        """
        # Генерация code_verifier по RFC 7636 (от 43 до 128 символов)
        code_verifier = secrets.token_urlsafe(64)[:96]

        # Расчет S256 challenge: BASE64URL(SHA256(ASCII(code_verifier)))
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

        actual_state = state or secrets.token_urlsafe(24)

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": actual_state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        url = f"{self.server_url}/oauth/authorize?{urlencode(params)}"
        return url, code_verifier, actual_state

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
                    err_desc = err_json.get("error_description") or err_json.get("error") or err_body
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
