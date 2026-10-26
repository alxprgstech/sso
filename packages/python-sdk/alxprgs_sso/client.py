from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKSet

from alxprgs_sso.exceptions import (
    ConfigurationError,
    InvalidTokenError,
    SSOError,
    StepUpAuthenticationError,
    StepUpBindingError,
    StepUpExpiredError,
    StepUpPolicyError,
    StepUpRejectedError,
    StepUpReplayError,
    StepUpUnavailableError,
    TokenExpiredError,
)
from alxprgs_sso.models import (
    StepUpProof,
    StepUpProofClaims,
    StepUpRequest,
    TokenResponse,
    UserClaims,
    WebSessionInfo,
)
from alxprgs_sso.token_profiles import validate_claims

STEP_UP_ASSURANCE = {
    "reauth_basic": ({"pwd"}, {"hwk"}),
    "reauth_mfa": ({"hwk"}, {"pwd", "otp"}),
    "reauth_strict": ({"pwd", "hwk"},),
    "reauth_password_mfa": ({"pwd", "otp"}, {"pwd", "hwk"}),
}
STEP_UP_ACTIONS = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
PAYLOAD_HASH = re.compile(r"^[0-9a-f]{64}$")


class SSOClient:
    """
    Основной клиент взаимодействия с сервером ALXPRGS SSO.
    """

    JWKS_MAX_BYTES = 65536
    # NumericDate is integral; allow only a bounded callback transit interval for
    # max_age=0. The OP still must perform fresh authentication for this request.
    FRESH_AUTH_TRANSIT_SECONDS = 5

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
        transport_profile: str = "strict",
    ) -> None:
        if transport_profile not in {"strict", "local"} or verify_ssl is not True:
            raise ConfigurationError("HTTPS certificate verification is mandatory")
        if (
            not isinstance(server_url, str)
            or any(character.isspace() or ord(character) < 32 for character in server_url)
            or "\\" in server_url
        ):
            raise ConfigurationError("Invalid SSO server URL")
        try:
            parsed = urlsplit(server_url)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError:
            raise ConfigurationError("Invalid SSO server URL") from None
        if (
            not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("Invalid SSO server URL")
        local = hostname.lower() == "localhost"
        try:
            local = local or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and transport_profile == "local" and local
        ):
            raise ConfigurationError(
                "SSO requires HTTPS; local HTTP requires an explicit loopback profile"
            )
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

    def _stale_jwks(self, now: float) -> dict[str, Any] | None:
        if self._cached_jwks and now < self._jwks_expires_at + self.max_stale_seconds:
            return self._cached_jwks
        return None

    def _cached_for_request(self, now: float, force: bool) -> dict[str, Any] | None:
        if not force:
            return self._cached_jwks if now < self._jwks_expires_at else None
        if now - self._last_force_refresh_at < self._min_force_refresh_interval:
            cached = self._stale_jwks(now)
            if cached:
                return cached
        self._last_force_refresh_at = now
        return None

    def _append_jwks_chunk(self, body: bytearray, chunk: bytes) -> None:
        body.extend(chunk)
        if len(body) > self.JWKS_MAX_BYTES:
            raise ValueError("JWKS exceeds response limit")

    def _cache_jwks_body(self, body: bytearray, now: float) -> dict[str, Any]:
        data = json.loads(body)
        self._parse_jwks(data)
        self._cached_jwks = data
        self._jwks_expires_at = now + self.jwks_cache_ttl_seconds
        return data

    def _jwks_unavailable(self, now: float) -> dict[str, Any]:
        cached = self._stale_jwks(now)
        if cached:
            return cached
        raise ConfigurationError("Не удалось загрузить JWKS") from None

    def get_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch bounded JWKS with the same cache and force-refresh limits."""
        now = time.time()
        cached = self._cached_for_request(now, force_refresh)
        if cached:
            return cached
        try:
            with httpx.Client(verify=True, timeout=10.0) as client:
                with client.stream("GET", f"{self.server_url}/.well-known/jwks.json") as resp:
                    resp.raise_for_status()
                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        self._append_jwks_chunk(body, chunk)
                return self._cache_jwks_body(body, now)
        except Exception:
            return self._jwks_unavailable(now)

    async def get_jwks_async(self, force_refresh: bool = False) -> dict[str, Any]:
        """Asynchronously fetch JWKS under the identical bounded cache policy."""
        now = time.time()
        cached = self._cached_for_request(now, force_refresh)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
                async with client.stream("GET", f"{self.server_url}/.well-known/jwks.json") as resp:
                    resp.raise_for_status()
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        self._append_jwks_chunk(body, chunk)
                return self._cache_jwks_body(body, now)
        except Exception:
            return self._jwks_unavailable(now)

    def _get_signing_key(self, token_or_header: str | dict[str, Any]) -> Any:
        if isinstance(token_or_header, str):
            if len(token_or_header) > 16384:
                raise InvalidTokenError("Превышен допустимый размер JWT")
            try:
                unverified_header = jwt.get_unverified_header(token_or_header)
            except Exception:
                raise InvalidTokenError("Некорректный заголовок JWT") from None
        else:
            unverified_header = token_or_header

        kid = unverified_header.get("kid")
        if (
            not isinstance(kid, str)
            or not 1 <= len(kid) <= 128
            or unverified_header.get("alg") != "RS256"
        ):
            raise InvalidTokenError("В заголовке JWT отсутствует обязательный kid")
        jwks_data = self.get_jwks()
        jwk_set = self._parse_jwks(jwks_data)

        signing_key = None
        for key in jwk_set.keys:
            if key.key_id == kid:
                signing_key = key
                break

        if not signing_key:
            # Возможно, ключи были ротированы: попробуем обновить кэш JWKS
            jwks_data = self.get_jwks(force_refresh=True)
            jwk_set = self._parse_jwks(jwks_data)
            for key in jwk_set.keys:
                if key.key_id == kid:
                    signing_key = key
                    break

        if not signing_key:
            raise InvalidTokenError("Ключ подписи с указанным kid не найден в JWKS сервера")
        return signing_key

    async def _get_signing_key_async(self, token_or_header: str | dict[str, Any]) -> Any:
        """Async variant used by the transaction proof flow."""
        if isinstance(token_or_header, str):
            if len(token_or_header) > 16384:
                raise InvalidTokenError("Превышен допустимый размер JWT")
            try:
                unverified_header = jwt.get_unverified_header(token_or_header)
            except Exception:
                raise InvalidTokenError("Некорректный заголовок JWT") from None
        else:
            unverified_header = token_or_header
        kid = unverified_header.get("kid")
        if (
            not isinstance(kid, str)
            or not 1 <= len(kid) <= 128
            or unverified_header.get("alg") != "RS256"
        ):
            raise InvalidTokenError("В заголовке JWT отсутствует обязательный kid")
        jwks_data = await self.get_jwks_async()
        signing_key = self._signing_key_by_id(jwks_data, kid)
        if signing_key is None:
            jwks_data = await self.get_jwks_async(force_refresh=True)
            signing_key = self._signing_key_by_id(jwks_data, kid)
        if signing_key is None:
            raise InvalidTokenError("Ключ подписи с указанным kid не найден в JWKS сервера")
        return signing_key

    def _signing_key_by_id(self, data: dict[str, Any], kid: str) -> Any | None:
        jwk_set = self._parse_jwks(data)
        for key in jwk_set.keys:
            if key.key_id == kid:
                return key
        return None

    @staticmethod
    def _parse_jwks(data: dict[str, Any]) -> PyJWKSet:
        try:
            entries = data["keys"]
            if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
                raise ValueError("Invalid key count")
            identifiers = [entry["kid"] for entry in entries]
            if any(
                not isinstance(kid, str) or not 1 <= len(kid) <= 128 for kid in identifiers
            ) or len(set(identifiers)) != len(identifiers):
                raise ValueError("Invalid identifiers")
            if any(
                entry.get("kty") != "RSA"
                or entry.get("alg") != "RS256"
                or entry.get("use") != "sig"
                for entry in entries
            ):
                raise ValueError("Unsupported key profile")
            result = PyJWKSet.from_dict(data)
            if len(result.keys) != len(entries) or any(
                not isinstance(key.key, rsa.RSAPublicKey) or key.key.key_size < 2048
                for key in result.keys
            ):
                raise ValueError("Invalid RSA key")
            return result
        except (ValueError, TypeError, KeyError, jwt.PyJWTError):
            raise InvalidTokenError("Недопустимый формат JWKS") from None

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
            "require": ["exp", "iat", "sub", "aud", "iss", "token_use"],
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
            if payload.get("token_use") == "id_token":
                raise InvalidTokenError("Недопустимо использовать ID Token в качестве Access Token")
            validate_claims(payload, target_audience, "access_token")
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Срок действия токена истёк") from None
        except (jwt.InvalidTokenError, ValueError, TypeError):
            raise InvalidTokenError("Недействительная подпись или атрибуты токена") from None

        return UserClaims(
            sub=payload["sub"],
            preferred_username=payload.get("preferred_username"),
            email=payload.get("email"),
            email_verified=bool(payload.get("email_verified", False)),
            roles=list(payload.get("roles", [])),
            scope=payload["scope"],
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
        prompt: str | None = None,
        max_age: int | None = None,
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
        params.update(self._prompt_parameters(prompt))
        params.update(self._max_age_parameters(max_age))
        url = f"{self.server_url}/oauth/authorize?{urlencode(params)}"
        return url, code_verifier, actual_state, actual_nonce

    @staticmethod
    def _prompt_parameters(prompt: str | None) -> dict[str, str]:
        if prompt is None:
            return {}
        if prompt not in {"login", "none"}:
            raise ConfigurationError("Поддерживаются prompt=login и prompt=none")
        return {"prompt": prompt}

    @staticmethod
    def _max_age_parameters(max_age: int | None) -> dict[str, str]:
        if max_age is None:
            return {}
        if type(max_age) is not int or max_age < 0:
            raise ConfigurationError("max_age должен быть неотрицательным integer")
        return {"max_age": str(max_age)}

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
        max_age: int | None = None,
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
            "require": ["exp", "iat", "sub", "aud", "iss", "token_use"],
        }
        target_issuer = self.expected_issuer or self.server_url
        try:
            payload = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                options=decode_options,
                audience=self.client_id,
                issuer=target_issuer,
            )
            validate_claims(payload, self.client_id, "id_token")
            self._require_id_token_age(payload, max_age)
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Срок действия ID токена истёк") from None
        except (jwt.InvalidTokenError, ValueError, TypeError):
            raise InvalidTokenError("Недействительный ID токен") from None

        if payload.get("token_use") != "id_token":
            raise InvalidTokenError("Токен не является валидным ID Token (token_use != 'id_token')")

        if expected_nonce is not None:
            token_nonce = payload.get("nonce")
            if not token_nonce or not secrets.compare_digest(token_nonce, expected_nonce):
                raise InvalidTokenError(
                    "Значение claim 'nonce' в ID токене не совпадает с ожидаемым"
                )

        return payload

    def _require_id_token_age(self, payload: dict[str, Any], max_age: int | None) -> None:
        if max_age is None:
            return
        if type(max_age) is not int or max_age < 0 or type(payload.get("auth_time")) is not int:
            raise ValueError("Invalid max_age/auth_time")
        transit = self.FRESH_AUTH_TRANSIT_SECONDS if max_age == 0 else 0
        if int(time.time()) - payload["auth_time"] > max_age + transit:
            raise ValueError("Authentication is too old")

    async def handle_web_callback(
        self,
        code: str,
        state: str,
        expected_state: str,
        code_verifier: str,
        redirect_uri: str,
        expected_nonce: str | None = None,
        max_age: int | None = None,
    ) -> WebSessionInfo:
        """
        Завершает авторизационный callback веб-приложения (SDK-03/06):
        1. Сверяет state с ожидаемым для защиты от CSRF.
        2. Обменивает authorization code и code_verifier на токены.
        3. Валидирует полученный ID Token и значение nonce.
        4. Валидирует Access Token и извлекает типизированные UserClaims.
        """
        if not expected_nonce:
            raise InvalidTokenError("Для OIDC callback требуется ожидаемый nonce")
        if not state or not expected_state or not secrets.compare_digest(state, expected_state):
            raise InvalidTokenError("Неверный параметр state: возможна попытка CSRF-атаки")

        tokens = await self.exchange_code_for_tokens(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )

        if not tokens.id_token:
            raise InvalidTokenError("OIDC token response не содержит обязательный ID Token")
        id_token_claims = self.verify_id_token(
            id_token=tokens.id_token,
            expected_nonce=expected_nonce,
            max_age=max_age,
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
        id_token_hint: str,
        post_logout_redirect_uri: str | None = None,
        state: str | None = None,
    ) -> str:
        """
        Формирует URL выхода RP-Initiated Logout (SSO-07).
        """
        base = f"{self.server_url}/oauth/logout"
        if not id_token_hint:
            raise ConfigurationError("Для RP logout требуется ID Token текущей сессии")
        params: dict[str, str] = {"id_token_hint": id_token_hint}
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

        async with httpx.AsyncClient(verify=True, timeout=15.0) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code != 200:
                raise SSOError(f"Ошибка обмена кода авторизации (HTTP {resp.status_code})")

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

        async with httpx.AsyncClient(verify=True, timeout=15.0) as client:
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

        async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
            resp = await client.post(revoke_url, data=data)
            return resp.status_code == 200

    # --------------------------------------------------------------------------
    # Cross-application transaction step-up (external hosted confirmation)
    # --------------------------------------------------------------------------

    def _require_confidential_for_step_up(self) -> None:
        if not self.client_secret:
            raise ConfigurationError(
                "Для внешнего step-up требуется confidential client с client_secret"
            )

    @staticmethod
    def _step_up_error(status_code: int, payload: dict[str, Any]) -> Exception:
        error = payload.get("error")
        error = error if isinstance(error, str) else "request_rejected"
        details = {"status": status_code, "error": error}
        if error in {"proof_replayed"}:
            return StepUpReplayError("Подтверждение уже использовано", details)
        if error in {"step_up_expired", "proof_expired"}:
            return StepUpExpiredError("Срок действия подтверждения истёк", details)
        if error in {"step_up_not_enabled", "feature_disabled", "step_up_client_inactive"}:
            return StepUpUnavailableError("Внешнее подтверждение недоступно", details)
        if error in {
            "step_up_policy_denied",
            "assurance_unavailable",
            "step_up_factor_unavailable",
            "step_up_method_not_allowed",
        }:
            return StepUpPolicyError("Сервер не разрешает выбранный способ", details)
        if status_code == 401:
            return StepUpAuthenticationError("Клиент или сессия не прошли проверку", details)
        if status_code == 404:
            return StepUpUnavailableError("Внешнее подтверждение недоступно", details)
        if status_code == 410:
            return StepUpExpiredError("Срок действия подтверждения истёк", details)
        return StepUpRejectedError("Подтверждение отклонено", details)

    @staticmethod
    def _step_up_json(response: httpx.Response) -> dict[str, Any]:
        if len(response.content) > 65536:
            raise StepUpRejectedError("Слишком большой ответ step-up")
        try:
            payload = response.json()
        except ValueError:
            raise StepUpRejectedError("Некорректный ответ step-up") from None
        if not isinstance(payload, dict):
            raise StepUpRejectedError("Некорректный ответ step-up")
        return payload

    async def create_step_up_request(
        self,
        *,
        action: str,
        payload_hash: str,
        subject: str,
        assurance: str,
        redirect_uri: str,
        description: str,
        ttl_seconds: int = 300,
        state: str | None = None,
        nonce: str | None = None,
    ) -> StepUpRequest:
        """Create a server-owned challenge for one exact sensitive action.

        The caller must persist the returned ``StepUpRequest`` server-side until
        the browser returns.  It contains the PKCE verifier, state and nonce.
        """
        self._require_confidential_for_step_up()
        if not STEP_UP_ACTIONS.fullmatch(action):
            raise ConfigurationError("Недопустимый идентификатор действия")
        if not PAYLOAD_HASH.fullmatch(payload_hash):
            raise ConfigurationError("payload_hash должен быть SHA-256 hex")
        try:
            subject_value = str(uuid.UUID(subject))
        except (ValueError, AttributeError, TypeError):
            raise ConfigurationError("subject должен быть UUID") from None
        if assurance not in STEP_UP_ASSURANCE:
            raise ConfigurationError("Недопустимый уровень подтверждения")
        if type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 300:
            raise ConfigurationError("ttl_seconds должен быть от 30 до 300")
        if (
            not description
            or len(description) > 280
            or any(ord(character) < 32 or ord(character) == 127 for character in description)
            or "<" in description
            or ">" in description
        ):
            raise ConfigurationError("Описание действия должно быть безопасным текстом")
        if not redirect_uri or len(redirect_uri) > 512:
            raise ConfigurationError("Некорректный redirect_uri")

        actual_state = state or secrets.token_urlsafe(24)
        actual_nonce = nonce or secrets.token_urlsafe(24)
        if not 16 <= len(actual_state) <= 128 or not re.fullmatch(
            r"[A-Za-z0-9._~-]+", actual_state
        ):
            raise ConfigurationError("state должен содержать 16-128 безопасных символов")
        if not 16 <= len(actual_nonce) <= 128 or not re.fullmatch(
            r"[A-Za-z0-9._~-]+", actual_nonce
        ):
            raise ConfigurationError("nonce должен содержать 16-128 безопасных символов")

        code_verifier = secrets.token_urlsafe(64)[:96]
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        body = {
            "subject": subject_value,
            "action": action,
            "payload_hash": payload_hash,
            "description": description,
            "assurance": assurance,
            "redirect_uri": redirect_uri,
            "state": actual_state,
            "nonce": actual_nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "ttl_seconds": ttl_seconds,
        }
        try:
            async with httpx.AsyncClient(verify=True, timeout=15.0) as client:
                response = await client.post(
                    f"{self.server_url}/api/v1/step-up/requests",
                    auth=(self.client_id, self.client_secret or ""),
                    json=body,
                )
        except httpx.HTTPError as error:
            raise SSOError("Не удалось создать step-up запрос") from error
        data = self._step_up_json(response)
        if response.status_code not in {200, 201}:
            raise self._step_up_error(response.status_code, data)
        return StepUpRequest(
            **data,
            redirect_uri=redirect_uri,
            state=actual_state,
            nonce=actual_nonce,
            code_verifier=code_verifier,
        )

    def build_step_up_url(self, request: StepUpRequest, redirect_uri: str | None = None) -> str:
        """Return the trusted SSO-hosted confirmation URL."""
        if redirect_uri is not None and redirect_uri != request.redirect_uri:
            raise ConfigurationError("redirect_uri не совпадает с созданным запросом")
        return request.authorization_url

    async def consume_step_up_proof(
        self,
        *,
        code: str,
        request: StepUpRequest,
        state: str,
        expected_action: str | None = None,
        expected_payload_hash: str | None = None,
        expected_subject: str,
        expected_assurance: str | None = None,
    ) -> StepUpProof:
        """Redeem one proof and verify the returned transaction-bound JWT.

        Server-side redemption supplies one-time semantics.  Local JWT checks
        additionally prove issuer, audience, subject, action, payload, nonce and
        assurance before the caller performs the action.
        """
        self._require_confidential_for_step_up()
        if not isinstance(request, StepUpRequest):
            raise ConfigurationError("Для redemption требуется сохранённый StepUpRequest")
        if not state or not secrets.compare_digest(state, request.state):
            raise StepUpBindingError("state не совпадает с исходным запросом")
        if request.expires_at <= datetime.now(timezone.utc):
            raise StepUpExpiredError("Срок действия запроса истёк")
        target_action = expected_action or request.action
        target_payload = expected_payload_hash or request.payload_hash
        target_assurance = expected_assurance or request.assurance
        if target_assurance not in STEP_UP_ASSURANCE:
            raise ConfigurationError("Недопустимый ожидаемый уровень подтверждения")
        if target_action != request.action or target_payload != request.payload_hash:
            raise StepUpBindingError("Ожидаемая операция не совпадает с запросом")
        if target_assurance != request.assurance:
            raise StepUpBindingError("Уровень подтверждения не совпадает с запросом")
        body = {
            "code": code,
            "code_verifier": request.code_verifier,
            "redirect_uri": request.redirect_uri,
        }
        try:
            async with httpx.AsyncClient(verify=True, timeout=15.0) as client:
                response = await client.post(
                    f"{self.server_url}/api/v1/step-up/redeem",
                    auth=(self.client_id, self.client_secret or ""),
                    json=body,
                )
        except httpx.HTTPError as error:
            raise SSOError("Не удалось погасить step-up proof") from error
        data = self._step_up_json(response)
        if response.status_code != 200:
            raise self._step_up_error(response.status_code, data)
        proof = data.get("proof")
        if not isinstance(proof, str) or not proof:
            raise StepUpRejectedError("Сервер не вернул step-up proof")
        claims = await self._verify_step_up_proof(
            proof,
            request=request,
            expected_subject=expected_subject,
            expected_action=target_action,
            expected_payload_hash=target_payload,
            expected_assurance=target_assurance,
        )
        return StepUpProof(proof=proof, claims=claims)

    async def _verify_step_up_proof(
        self,
        proof: str,
        *,
        request: StepUpRequest,
        expected_subject: str,
        expected_action: str,
        expected_payload_hash: str,
        expected_assurance: str,
    ) -> StepUpProofClaims:
        signing_key = await self._get_signing_key_async(proof)
        target_issuer = self.expected_issuer or self.server_url
        decode_options: Any = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iat": True,
            "verify_aud": True,
            "verify_iss": True,
            "require": [
                "exp",
                "iat",
                "sub",
                "aud",
                "iss",
                "token_use",
                "transaction_id",
                "action",
                "payload_hash",
                "acr",
                "amr",
                "nonce",
                "auth_time",
                "security_revision",
                "jti",
            ],
        }
        try:
            payload = jwt.decode(
                proof,
                signing_key.key,
                algorithms=["RS256"],
                options=decode_options,
                audience=self.client_id,
                issuer=target_issuer,
            )
        except jwt.ExpiredSignatureError:
            raise StepUpExpiredError("Срок действия step-up proof истёк") from None
        except (jwt.InvalidTokenError, ValueError, TypeError):
            raise StepUpBindingError("Недействительный step-up proof") from None

        if payload.get("token_use") != "external_step_up_proof":
            raise StepUpBindingError("Неверный token_use step-up proof")
        if payload.get("aud") != self.client_id:
            raise StepUpBindingError("Неверная audience step-up proof")
        if payload.get("sub") != str(expected_subject):
            raise StepUpBindingError("Подтверждение относится к другому subject")
        if payload.get("action") != expected_action:
            raise StepUpBindingError("Подтверждение относится к другому действию")
        if payload.get("payload_hash") != expected_payload_hash:
            raise StepUpBindingError("Payload изменился после подтверждения")
        if payload.get("acr") != expected_assurance:
            raise StepUpBindingError("Уровень подтверждения не совпадает")
        if not isinstance(payload.get("nonce"), str) or not secrets.compare_digest(
            payload["nonce"], request.nonce
        ):
            raise StepUpBindingError("nonce не совпадает с запросом")
        if not isinstance(payload.get("transaction_id"), str) or not payload["transaction_id"]:
            raise StepUpBindingError("Отсутствует transaction_id")
        if type(payload.get("security_revision")) is not int or payload["security_revision"] < 0:
            raise StepUpBindingError("Некорректная security revision")
        if type(payload.get("auth_time")) is not int:
            raise StepUpBindingError("Некорректный auth_time")
        if payload["auth_time"] > payload.get("iat", 0):
            raise StepUpBindingError("auth_time позже выдачи proof")
        if int(time.time()) - payload["auth_time"] > 300:
            raise StepUpExpiredError("Подтверждение слишком старое")
        amr = payload.get("amr")
        if (
            not isinstance(amr, list)
            or not amr
            or len(amr) > 3
            or len(set(amr)) != len(amr)
            or any(method not in {"pwd", "otp", "hwk"} for method in amr)
        ):
            raise StepUpBindingError("Некорректный amr")
        if not any(set(amr) == required for required in STEP_UP_ASSURANCE[expected_assurance]):
            raise StepUpBindingError("Факторы не соответствуют уровню подтверждения")
        try:
            return StepUpProofClaims.model_validate(payload)
        except Exception:
            raise StepUpBindingError("Некорректные claims step-up proof") from None
