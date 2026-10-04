from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.security import validate_new_password


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class TelemetryConfigResponse(BaseModel):
    enabled: bool
    dsn: str
    environment: Literal["local", "test", "staging", "production"]
    traces_sample_rate: float
    replay_enabled: bool
    replays_session_sample_rate: float
    replays_on_error_sample_rate: float
    trace_propagation_targets: list[str]


class MFAStepRequiredResponse(BaseModel):
    mfa_required: bool = True
    mfa_token: str
    available_methods: list[str]  # e.g. ["totp", "passkey", "recovery_code"]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=15, max_length=128)
    _password_policy = field_validator("new_password")(validate_new_password)


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    is_active: bool
    is_superuser: bool
    email_verified: bool
    roles: list[str] = []
    has_totp: bool = False
    has_passkey: bool = False
    created_at: datetime
    legal_acceptance_required: bool = True
    deletion_pending: bool = False
    deletion_scheduled_for: datetime | None = None
    session_purpose: str = "full"


class SessionInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ip_address: str | None = None
    user_agent: str | None = None
    is_current: bool = False
    last_activity_at: datetime
    expires_at: datetime
    created_at: datetime


class CapabilitiesResponse(BaseModel):
    """Безопасная витрина возможностей сервера (SEC-FLAG-01, REG-03)."""

    totp_enabled: bool
    passkey_enabled: bool
    recovery_codes_enabled: bool
    email_verification_enabled: bool
    require_verified_email: bool
    registration_mode: str = "closed"


class RegisterRequest(BaseModel):
    """
    Схема самостоятельной регистрации обычного пользователя (REG-01, REG-04, REG-05).
    Любые дополнительные поля (роли, флаги прав) строго запрещены (extra='forbid').
    """

    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    email: str = Field(..., min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(..., min_length=15, max_length=128)
    _password_policy = field_validator("password")(validate_new_password)
    confirm_password: str = Field(..., min_length=15, max_length=128)
    terms_accepted: Literal[True]
    data_processing_consent: Literal[True]
    legal_versions: dict[str, str]

    @field_validator("terms_accepted", "data_processing_consent", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("Требуется явное согласие")
        return value

    @model_validator(mode="after")
    def validate_passwords_match(self) -> RegisterRequest:
        if self.password != self.confirm_password:
            raise ValueError("Пароли не совпадают")
        return self


class RegisterResponse(BaseModel):
    status: str = "verification_pending"
    message: str = "Введите код из письма или откройте ссылку подтверждения."
    challenge_id: uuid.UUID
    expires_at: datetime
    request_details: dict[str, str]


class RegistrationCodeConfirmRequest(BaseModel):
    challenge_id: uuid.UUID
    code: str = Field(..., pattern=r"^[0-9]{6}$")


class RegistrationLinkConfirmRequest(BaseModel):
    token: str = Field(..., min_length=32, max_length=128)


class RegistrationResendRequest(BaseModel):
    challenge_id: uuid.UUID


class RegistrationCompleteResponse(BaseModel):
    status: str = "ok"
    message: str = "Адрес подтверждён. Теперь можно войти."
    user_id: uuid.UUID
