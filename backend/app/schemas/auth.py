from __future__ import annotations

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class MFAStepRequiredResponse(BaseModel):
    mfa_required: bool = True
    mfa_token: str
    available_methods: list[str]  # e.g. ["totp", "passkey", "recovery_code"]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


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
    """Безопасная витрина возможностей сервера (SEC-FLAG-01)."""
    totp_enabled: bool
    passkey_enabled: bool
    recovery_codes_enabled: bool
    email_verification_enabled: bool
    require_verified_email: bool
