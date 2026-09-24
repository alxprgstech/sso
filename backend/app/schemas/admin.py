from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


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
