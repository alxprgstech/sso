from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserClaims(BaseModel):
    """
    Типизированный объект данных пользователя из декодированного Access/ID токена.
    """

    model_config = ConfigDict(extra="ignore")

    sub: str
    preferred_username: str | None = None
    email: str | None = None
    email_verified: bool = False
    roles: list[str] = Field(default_factory=list)
    scope: str = ""

    @property
    def scopes(self) -> frozenset[str]:
        return frozenset(self.scope.split())


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


class WebSessionInfo(BaseModel):
    """
    Информация об установленной веб-сессии пользователя (SDK-03/06).
    """

    model_config = ConfigDict(extra="ignore")

    user: UserClaims
    access_token: str
    id_token: str | None = None
    refresh_token: str | None = None
    expires_in: int
    id_token_claims: dict[str, object] | None = None
