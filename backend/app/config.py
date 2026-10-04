from __future__ import annotations

import base64
import ipaddress
import json
import re
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _require_production_origin(value: str, issuer: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Production issuer and external URLs must share one exact HTTPS origin")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Production issuer and external URLs must share one exact HTTPS origin")
    if parsed.username or parsed.password:
        raise ValueError("Production issuer and external URLs must share one exact HTTPS origin")
    if any((parsed.query, parsed.fragment, parsed.path)):
        raise ValueError("Production issuer and external URLs must share one exact HTTPS origin")
    if parsed.port == 0 or value != issuer:
        raise ValueError("Production issuer and external URLs must share one exact HTTPS origin")


def _parse_proxy_list(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except Exception:
            raise ValueError("Invalid trusted proxy list") from None
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_proxy_address(address: Any) -> None:
    if not isinstance(address, str):
        raise ValueError("Invalid trusted proxy address")
    network = ipaddress.ip_network(address, strict=True)
    if network.prefixlen == 0:
        raise ValueError("Wildcard proxy trust is forbidden")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    # Окружение
    ENVIRONMENT: Literal["development", "testing", "production"] = "development"
    DEBUG: bool = False

    # Observability is independent of SSO availability. No credentials in this projection.
    SENTRY_ENABLED: bool = False
    SENTRY_DSN: str = ""
    SENTRY_FRONTEND_ENABLED: bool = False
    SENTRY_FRONTEND_DSN: str = ""
    SENTRY_ENVIRONMENT: Literal["local", "test", "staging", "production"] | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    SENTRY_FRONTEND_TRACES_SAMPLE_RATE: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    SENTRY_REPLAY_ENABLED: bool = False
    SENTRY_REPLAYS_SESSION_SAMPLE_RATE: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)

    @property
    def telemetry_environment(self) -> str:
        return (
            self.SENTRY_ENVIRONMENT
            or {"development": "local", "testing": "test", "production": "production"}[
                self.ENVIRONMENT
            ]
        )

    @field_validator("SENTRY_DSN", "SENTRY_FRONTEND_DSN")
    @classmethod
    def validate_sentry_dsn(cls, value: str) -> str:
        import re
        from urllib.parse import urlsplit

        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.username
            or not re.fullmatch(r"[a-zA-Z0-9]+", parsed.username)
            or not re.fullmatch(r"/[0-9]+", parsed.path)
            or not parsed.hostname
            or parsed.port not in (None, 443)
            or not re.fullmatch(r"o[0-9]+\.ingest(?:\.[a-z]+)?\.sentry\.io", parsed.hostname)
        ):
            raise ValueError("Invalid Sentry DSN (HTTPS Sentry ingestion required)")
        return value

    # Сетевые параметры
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:5173"
    TRUSTED_PROXIES: list[str] | str = ["127.0.0.1", "::1"]

    # OIDC параметры
    OIDC_ISSUER: str = "https://auth.alxprgs.tech"
    JWT_PRIVATE_KEY_PEM: str = ""
    JWT_KEY_ID: str = "default-rsa-key-1"
    JWT_PREVIOUS_PUBLIC_KEY_PEM: str = ""
    JWT_PREVIOUS_KEY_ID: str = ""
    JWT_PREVIOUS_KEY_VALID_UNTIL: datetime | None = None

    @field_validator("JWT_PREVIOUS_KEY_VALID_UNTIL", mode="before")
    @classmethod
    def empty_retirement_deadline(cls, value: Any) -> Any:
        return None if value == "" else value

    # База данных
    DATABASE_URL: str = "postgresql+psycopg://sso_user:sso_password@localhost:5432/alxprgs_sso"
    DATABASE_URL_SYNC: str = "postgresql+psycopg://sso_user:sso_password@localhost:5432/alxprgs_sso"

    # Сессии и CSRF
    SESSION_SECRET_KEY: str = (
        "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only"
    )
    SESSION_COOKIE_NAME: str = "__Host-alx_session"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"

    # Времена жизни (в секундах)
    AUTH_CODE_TTL_SECONDS: int = 60
    ACCESS_TOKEN_TTL_SECONDS: int = 300  # 5 минут
    REFRESH_TOKEN_TTL_SECONDS: int = 604800  # 7 дней
    REFRESH_FAMILY_MAX_LIFETIME_SECONDS: int = 2592000  # 30 дней абсолютный лимит семейства
    SESSION_IDLE_TIMEOUT_SECONDS: int = 43200  # 12 часов
    SESSION_ABSOLUTE_TIMEOUT_SECONDS: int = 604800  # 7 дней
    MFA_STEP_TTL_SECONDS: int = 300  # 5 минут на подтверждение второго фактора

    # Отложенные факторы выключены по умолчанию. Email для саморегистрации обязателен.
    FEATURE_TOTP_ENABLED: bool = False
    FEATURE_PASSKEY_ENABLED: bool = False
    FEATURE_RECOVERY_CODES_ENABLED: bool = False
    FEATURE_EMAIL_VERIFICATION_ENABLED: bool = True
    REQUIRE_VERIFIED_EMAIL: bool = False

    # Ключ шифрования TOTP (Fernet 32 байта base64)
    TOTP_ENCRYPTION_KEY: str = "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="

    # WebAuthn параметры
    WEBAUTHN_RP_ID: str = "auth.alxprgs.tech"
    WEBAUTHN_RP_NAME: str = "ALXPRGS SSO"
    WEBAUTHN_ORIGIN: str = "https://auth.alxprgs.tech"

    # Почтовый транспорт.
    EMAIL_PROVIDER: Literal["smtp", "ses"] = "smtp"
    SES_REGION: str = "us-east-1"
    SES_FROM_EMAIL: str = "sso@alxprgs.tech"
    SES_FROM_NAME: str = "ALXPRGS"

    # SMTP параметры
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@alxprgs.tech"
    SMTP_USE_TLS: bool = False
    SMTP_CA_FILE: str = ""  # Optional trusted local/enterprise CA; normal system trust by default.

    @field_validator("SES_REGION", "SES_FROM_EMAIL", "SES_FROM_NAME")
    @classmethod
    def validate_ses_header_values(cls, value: str) -> str:
        if not value.strip() or "\r" in value or "\n" in value:
            raise ValueError("Некорректное значение параметра SES")
        return value.strip()

    @field_validator("SES_FROM_EMAIL")
    @classmethod
    def validate_ses_from_email(cls, value: str) -> str:
        if (
            not value.isascii()
            or value.count("@") != 1
            or any(char.isspace() or char in "<>,;" for char in value)
        ):
            raise ValueError("SES_FROM_EMAIL должен быть ASCII email адресом")
        local, domain = value.split("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("SES_FROM_EMAIL должен быть корректным email адресом")
        return value

    @field_validator("TRUSTED_PROXIES", mode="after")
    @classmethod
    def parse_trusted_proxies(cls, val: Any) -> list[str]:
        if isinstance(val, str):
            val = _parse_proxy_list(val)
        if not isinstance(val, list) or len(val) > 16:
            raise ValueError("Invalid trusted proxy list")
        for item in val:
            _validate_proxy_address(item)
        return val

    @model_validator(mode="after")
    def validate_feature_invariants(self) -> Settings:
        """
        Проверка архитектурных инвариантов зависимости флагов (SEC-FLAG-03, SEC-FLAG-05).
        """
        if not self.FEATURE_EMAIL_VERIFICATION_ENABLED:
            raise ValueError("Подтверждение email обязательно и не может быть отключено")
        if self.FEATURE_RECOVERY_CODES_ENABLED and not self.FEATURE_TOTP_ENABLED:
            raise ValueError(
                "Конфигурационная ошибка: FEATURE_RECOVERY_CODES_ENABLED не может быть включен "
                "без включения FEATURE_TOTP_ENABLED."
            )
        self.validate_key_configuration()
        if self.ENVIRONMENT == "production":
            self.validate_production_configuration()
        return self

    def validate_key_configuration(self) -> None:
        from app.core.key_material import load_private_key, load_public_key, validate_key_id

        validate_key_id(self.JWT_KEY_ID)
        if self.JWT_PRIVATE_KEY_PEM:
            load_private_key(self.JWT_PRIVATE_KEY_PEM)
        previous = bool(self.JWT_PREVIOUS_PUBLIC_KEY_PEM)
        if previous != bool(self.JWT_PREVIOUS_KEY_ID):
            raise ValueError("Previous RSA key and identifier must be configured together")
        if previous:
            validate_key_id(self.JWT_PREVIOUS_KEY_ID)
            if self.JWT_PREVIOUS_KEY_ID == self.JWT_KEY_ID:
                raise ValueError("Active and previous RSA identifiers must differ")
            load_public_key(self.JWT_PREVIOUS_PUBLIC_KEY_PEM)
        if self.JWT_PREVIOUS_KEY_VALID_UNTIL is not None:
            if not previous or self.JWT_PREVIOUS_KEY_VALID_UNTIL.utcoffset() is None:
                raise ValueError(
                    "Previous key retirement requires a key and timezone-aware deadline"
                )

    def validate_production_configuration(self) -> None:
        self._validate_session_secret()
        self._validate_totp_key()
        self._validate_production_signing()
        self._validate_production_origins()
        self._validate_lifetimes()
        self._validate_production_transport()

    def _validate_session_secret(self) -> None:
        session = self.SESSION_SECRET_KEY
        if (
            len(session) < 64
            or len(set(session)) < 16
            or re.search(r"default|dev-only|change-me|example|placeholder", session, re.I)
        ):
            raise ValueError(
                "Production requires a non-default random SESSION_SECRET_KEY (64+ characters)"
            )

    def _validate_totp_key(self) -> None:
        try:
            Fernet(self.TOTP_ENCRYPTION_KEY.encode("ascii"))
        except (ValueError, UnicodeError):
            raise ValueError("Production requires a valid TOTP_ENCRYPTION_KEY") from None
        if self.TOTP_ENCRYPTION_KEY == type(self).model_fields["TOTP_ENCRYPTION_KEY"].default:
            raise ValueError("Production rejects the development TOTP_ENCRYPTION_KEY")
        if len(set(base64.urlsafe_b64decode(self.TOTP_ENCRYPTION_KEY))) < 16:
            raise ValueError("Production requires a random TOTP_ENCRYPTION_KEY")

    def _validate_production_signing(self) -> None:
        if not self.JWT_PRIVATE_KEY_PEM.strip() or self.JWT_KEY_ID == "default-rsa-key-1":
            raise ValueError(
                "Production requires persistent RSA material and an explicit JWT_KEY_ID"
            )
        if self.JWT_PREVIOUS_PUBLIC_KEY_PEM and self.JWT_PREVIOUS_KEY_VALID_UNTIL is None:
            raise ValueError("Production previous RSA key requires an explicit retirement deadline")

    def _validate_production_origins(self) -> None:
        for value in (self.OIDC_ISSUER, self.BASE_URL, self.FRONTEND_URL, self.WEBAUTHN_ORIGIN):
            _require_production_origin(value, self.OIDC_ISSUER)
        if self.WEBAUTHN_RP_ID != urlsplit(self.OIDC_ISSUER).hostname:
            raise ValueError("Production WebAuthn RP ID must match the issuer host")

    def _validate_lifetimes(self) -> None:
        bounds = {
            "AUTH_CODE_TTL_SECONDS": 60,
            "ACCESS_TOKEN_TTL_SECONDS": 300,
            "REFRESH_TOKEN_TTL_SECONDS": 604800,
            "REFRESH_FAMILY_MAX_LIFETIME_SECONDS": 2592000,
            "SESSION_IDLE_TIMEOUT_SECONDS": 43200,
            "SESSION_ABSOLUTE_TIMEOUT_SECONDS": 604800,
            "MFA_STEP_TTL_SECONDS": 300,
        }
        if any(not 1 <= getattr(self, name) <= limit for name, limit in bounds.items()):
            raise ValueError("Production token/session lifetimes exceed the supported bounds")
        if self.SESSION_IDLE_TIMEOUT_SECONDS > self.SESSION_ABSOLUTE_TIMEOUT_SECONDS:
            raise ValueError("Idle session timeout cannot exceed the absolute timeout")

    def _validate_production_transport(self) -> None:
        if self.DEBUG:
            raise ValueError("Production DEBUG must be disabled")
        if not re.fullmatch(r"__Host-[A-Za-z0-9_-]+", self.SESSION_COOKIE_NAME):
            raise ValueError("Production requires a __Host- session cookie name")
        if self.EMAIL_PROVIDER == "smtp" and not self.SMTP_USE_TLS:
            raise ValueError("Production SMTP requires verified STARTTLS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
