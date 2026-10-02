from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
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
        from urllib.parse import urlsplit
        import re

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
            if val.startswith("[") and val.endswith("]"):
                import json

                try:
                    return json.loads(val)
                except Exception:
                    pass
            return [x.strip() for x in val.split(",") if x.strip()]
        if isinstance(val, list):
            return val
        return ["127.0.0.1", "::1"]

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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
