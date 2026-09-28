from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    roles: list[str] = ["user"]
    is_superuser: bool = False


class AdminUserUpdateRequest(BaseModel):
    email: str | None = Field(None, min_length=5, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    roles: list[str] | None = None
    new_password: str | None = Field(None, min_length=8, max_length=128)


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


class AdminClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: str
    client_name: str
    client_type: str
    is_active: bool
    redirect_uris: list[str] = []
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
    """Смена режима регистрации с подтверждением пароля администратора (REG-02)."""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(..., pattern=r"^(closed|open)$")
    current_admin_password: str = Field(..., min_length=1, max_length=128)

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
