from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.security import validate_new_password

STEP_UP_ASSURANCE_LEVELS = frozenset(
    {"reauth_basic", "reauth_mfa", "reauth_strict", "reauth_password_mfa"}
)
STEP_UP_ACTION_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,63}")


def _validate_assurance_levels(value: list[str]) -> None:
    if len(set(value)) != len(value) or not set(value) <= STEP_UP_ASSURANCE_LEVELS:
        raise ValueError("Недопустимый уровень подтверждения")


def _validate_actions(value: list[str]) -> None:
    if len(set(value)) != len(value) or any(
        not STEP_UP_ACTION_PATTERN.fullmatch(action) for action in value
    ):
        raise ValueError("Недопустимый идентификатор действия")


class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=15, max_length=128)
    _password_policy = field_validator("password")(validate_new_password)
    roles: list[str] = ["user"]
    is_superuser: bool = False


class AdminUserUpdateRequest(BaseModel):
    email: str | None = Field(None, min_length=5, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    roles: list[str] | None = None
    new_password: str | None = Field(None, min_length=15, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_policy(cls, value: str | None) -> str | None:
        return validate_new_password(value) if value is not None else None


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    is_active: bool
    is_superuser: bool
    email_verified: bool
    roles: list[str] = []
    created_at: datetime
    updated_at: datetime


class AdminClientCreateRequest(BaseModel):
    client_name: str = Field(..., min_length=2, max_length=128)
    client_type: str = Field("confidential", pattern="^(confidential|public)$")
    redirect_uris: list[str] = Field(..., min_length=1)
    allowed_scopes: list[str] = Field(
        default_factory=lambda: ["openid", "profile", "email"], min_length=1, max_length=3
    )
    step_up_enabled: bool = False
    step_up_assurance_levels: list[str] = Field(default_factory=list, max_length=4)
    step_up_actions: list[str] = Field(default_factory=list, max_length=32)
    step_up_max_ttl_seconds: int = Field(default=300, ge=30, le=300)

    @field_validator("allowed_scopes")
    @classmethod
    def scope_policy(cls, value: list[str]) -> list[str]:
        if (
            "openid" not in value
            or not set(value) <= {"openid", "profile", "email"}
            or len(set(value)) != len(value)
        ):
            raise ValueError("Допустимые scopes: openid (обязательно), profile, email")
        return value

    @field_validator("step_up_assurance_levels")
    @classmethod
    def assurance_policy(cls, value: list[str]) -> list[str]:
        _validate_assurance_levels(value)
        return value

    @field_validator("step_up_actions")
    @classmethod
    def action_policy(cls, value: list[str]) -> list[str]:
        _validate_actions(value)
        return value


class AdminClientStepUpUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_up_enabled: bool
    step_up_assurance_levels: list[str] = Field(default_factory=list, max_length=4)
    step_up_actions: list[str] = Field(default_factory=list, max_length=32)
    step_up_max_ttl_seconds: int = Field(default=300, ge=30, le=300)

    @field_validator("step_up_assurance_levels")
    @classmethod
    def assurance_policy(cls, value: list[str]) -> list[str]:
        _validate_assurance_levels(value)
        return value

    @field_validator("step_up_actions")
    @classmethod
    def action_policy(cls, value: list[str]) -> list[str]:
        _validate_actions(value)
        return value


class AdminClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: str
    client_name: str
    client_type: str
    is_active: bool
    allowed_scopes: list[str] = Field(default_factory=list)
    redirect_uris: list[str] = []
    step_up_enabled: bool = False
    step_up_assurance_levels: list[str] = Field(default_factory=list)
    step_up_actions: list[str] = Field(default_factory=list)
    step_up_max_ttl_seconds: int = 300
    client_secret: str | None = None  # Показывается ТОЛЬКО при создании или ротации
    created_at: datetime


class AdminAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    user_id: uuid.UUID | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    details: dict[str, Any] = {}
    created_at: datetime


class RegistrationModeUpdateRequest(BaseModel):
    """Смена режима регистрации (REG-02).

    Freshness is normally proven by the action-bound ``X-Reauthentication``
    proof (password + configured MFA, one use, bound to this exact body).
    ``current_admin_password`` remains accepted for older clients and is still
    verified when supplied, but new clients must not ask for the password twice.
    """

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(..., pattern=r"^(closed|open)$")
    current_admin_password: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def handle_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "mode" not in data and "registration_mode" in data:
                data["mode"] = data.pop("registration_mode")
            if "current_admin_password" not in data and "admin_password" in data:
                data["current_admin_password"] = data.pop("admin_password")
        return data


class SystemStatusResponse(BaseModel):
    """Срез состояния системы и конфигурации (REG-02, SETUP-05)."""

    model_config = ConfigDict(from_attributes=True)

    bootstrap_completed: bool
    bootstrap_completed_at: datetime | None = None
    registration_mode: str
    updated_at: datetime
    total_users: int
    total_active_admins: int
