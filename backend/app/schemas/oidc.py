from __future__ import annotations

from pydantic import BaseModel


class ClientContextResponse(BaseModel):
    client_name: str
    redirect_origin: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str | None = None
    id_token: str | None = None
    scope: str = "openid profile email"


class UserInfoResponse(BaseModel):
    sub: str  # Стабильный непрозрачный UUID (SSO-04)
    preferred_username: str | None = None
    email: str | None = None
    email_verified: bool | None = None
    roles: list[str] = []
