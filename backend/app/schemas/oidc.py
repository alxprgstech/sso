from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str | None = None
    id_token: str | None = None
    scope: str = "openid profile email"


class UserInfoResponse(BaseModel):
    sub: str  # Стабильный непрозрачный UUID (SSO-04)
    preferred_username: str
    email: str
    email_verified: bool
    roles: list[str] = []
