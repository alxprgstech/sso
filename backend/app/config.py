from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal
from pydantic import model_validator
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

    # Сетевые параметры
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:5173"

    # OIDC параметры
    OIDC_ISSUER: str = "https://auth.alxprgs.tech"
    JWT_PRIVATE_KEY_PEM: str = ""
    JWT_KEY_ID: str = "default-rsa-key-1"

    # База данных
    DATABASE_URL: str = "postgresql+psycopg://sso_user:sso_password@localhost:5432/alxprgs_sso"
    DATABASE_URL_SYNC: str = "postgresql+psycopg://sso_user:sso_password@localhost:5432/alxprgs_sso"

    # Сессии и CSRF
    SESSION_SECRET_KEY: str = "default-dev-session-secret-key-at-least-64-characters-long-safe-for-dev-only"
    SESSION_COOKIE_NAME: str = "__Host-alx_session"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"

    # Времена жизни (в секундах)
    AUTH_CODE_TTL_SECONDS: int = 60
    ACCESS_TOKEN_TTL_SECONDS: int = 300  # 5 минут
    REFRESH_TOKEN_TTL_SECONDS: int = 604800  # 7 дней
    SESSION_IDLE_TIMEOUT_SECONDS: int = 43200  # 12 часов
    SESSION_ABSOLUTE_TIMEOUT_SECONDS: int = 604800  # 7 дней
    MFA_STEP_TTL_SECONDS: int = 300  # 5 минут на подтверждение второго фактора

    # ФЛАГИ ОТЛОЖЕННЫХ ВОЗМОЖНОСТЕЙ (СТРОГО FALSE ПО УМОЛЧАНИЮ)
    FEATURE_TOTP_ENABLED: bool = False
    FEATURE_PASSKEY_ENABLED: bool = False
    FEATURE_RECOVERY_CODES_ENABLED: bool = False
    FEATURE_EMAIL_VERIFICATION_ENABLED: bool = False
    REQUIRE_VERIFIED_EMAIL: bool = False

    # Ключ шифрования TOTP (Fernet 32 байта base64)
    TOTP_ENCRYPTION_KEY: str = "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="

    # WebAuthn параметры
    WEBAUTHN_RP_ID: str = "auth.alxprgs.tech"
    WEBAUTHN_RP_NAME: str = "ALXPRGS SSO"
    WEBAUTHN_ORIGIN: str = "https://auth.alxprgs.tech"

    # SMTP параметры
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@alxprgs.tech"
    SMTP_USE_TLS: bool = False

    @model_validator(mode="after")
    def validate_feature_invariants(self) -> Settings:
        """
        Проверка архитектурных инвариантов зависимости флагов (SEC-FLAG-03, SEC-FLAG-05).
        """
        if self.FEATURE_RECOVERY_CODES_ENABLED and not self.FEATURE_TOTP_ENABLED:
            raise ValueError(
                "Конфигурационная ошибка: FEATURE_RECOVERY_CODES_ENABLED не может быть включен "
                "без включения FEATURE_TOTP_ENABLED."
            )
        if self.REQUIRE_VERIFIED_EMAIL and not self.FEATURE_EMAIL_VERIFICATION_ENABLED:
            raise ValueError(
                "Конфигурационная ошибка: REQUIRE_VERIFIED_EMAIL не может быть установлен в true "
                "при отключенном FEATURE_EMAIL_VERIFICATION_ENABLED."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
