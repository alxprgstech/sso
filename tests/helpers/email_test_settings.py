"""Use the application's settings loader, with test-only credentials."""

from __future__ import annotations

import os
from pathlib import Path

from app.config import Settings
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class EmailTestConfigurationError(RuntimeError):
    pass


class EmailTestSettings(Settings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )
    TESTMAIL_API_KEY: SecretStr = Field(default=SecretStr(""), repr=False)
    TESTMAIL_NAMESPACE: str = ""
    TESTMAIL_TIMEOUT_SECONDS: float = Field(default=120, ge=1, le=600)
    TESTMAIL_POLL_INTERVAL_SECONDS: float = Field(default=2, ge=0.5, le=30)
    AWS_ACCESS_KEY_ID: SecretStr = Field(default=SecretStr(""), repr=False)
    AWS_SECRET_ACCESS_KEY: SecretStr = Field(default=SecretStr(""), repr=False)
    AWS_SESSION_TOKEN: SecretStr = Field(default=SecretStr(""), repr=False)

    def require_credentials(self) -> None:
        if not self.TESTMAIL_API_KEY.get_secret_value() or not self.TESTMAIL_NAMESPACE:
            raise EmailTestConfigurationError(
                "TESTMAIL_API_KEY and TESTMAIL_NAMESPACE are required"
            )
        import re

        if not re.fullmatch(r"[a-z0-9-]{1,18}", self.TESTMAIL_NAMESPACE):
            raise EmailTestConfigurationError(
                "Invalid TESTMAIL_NAMESPACE (local part must fit 64 bytes)"
            )

    def process_environment(self, *, recipient: str = "helper") -> dict[str, str]:
        env = dict(os.environ)
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            value = getattr(self, name).get_secret_value()
            if value:
                env[name] = value
        if recipient != "helper":
            env = {k: v for k, v in env.items() if not k.startswith("TESTMAIL_")}
        if recipient == "frontend":
            env = {k: v for k, v in env.items() if not k.startswith("AWS_")}
        return env

    def application_settings(self) -> Settings:
        values = {name: getattr(self, name) for name in Settings.model_fields}
        values.update(
            ENVIRONMENT="testing",
            EMAIL_PROVIDER="ses",
            REQUIRE_VERIFIED_EMAIL=True,
            FEATURE_TOTP_ENABLED=False,
            FEATURE_PASSKEY_ENABLED=False,
            FEATURE_RECOVERY_CODES_ENABLED=False,
            BASE_URL="http://localhost:8000",
            FRONTEND_URL="http://localhost:5173",
        )
        return Settings(_env_file=None, **values)


def load_email_settings() -> EmailTestSettings:
    try:
        settings = EmailTestSettings()
        settings.require_credentials()
        return settings
    except ValidationError:
        raise EmailTestConfigurationError(
            "Invalid email test configuration; check documented variables"
        ) from None
