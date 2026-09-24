from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserClaims(BaseModel):
    """
    Типизированный объект данных пользователя из декодированного Access/ID токена.
    """

    model_config = ConfigDict(extra="ignore")

    sub: str
    preferred_username: str
    email: str | None = None
    email_verified: bool = False
    roles: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    """
    Стандартный ответ эндпоинта /oauth/token.
    """

    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    id_token: str | None = None
    refresh_token: str | None = None
    scope: str | None = None
