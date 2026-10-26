from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StepUpAssurance = Literal["reauth_basic", "reauth_mfa", "reauth_strict", "reauth_password_mfa"]
StepUpMethod = Literal["password", "totp", "passkey"]


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


class StepUpPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    methods: list[StepUpMethod]


class StepUpRequest(BaseModel):
    """Server-issued challenge plus locally held PKCE/state material.

    ``code_verifier``, ``state`` and ``nonce`` are secrets of the relying-party
    flow and are intentionally hidden from repr/logging.
    """

    model_config = ConfigDict(extra="ignore")

    request_token: str = Field(repr=False)
    authorization_url: str
    client_name: str
    action: str
    description: str
    payload_hash: str
    assurance: StepUpAssurance
    assurance_label: str
    plans: list[StepUpPlan]
    expires_at: datetime
    redirect_uri: str
    state: str = Field(repr=False)
    nonce: str = Field(repr=False)
    code_verifier: str = Field(repr=False)


class StepUpProofClaims(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub: str
    aud: str
    iss: str
    exp: int
    iat: int
    auth_time: int
    token_use: str
    transaction_id: str
    action: str
    payload_hash: str
    acr: StepUpAssurance
    amr: list[str]
    nonce: str
    security_revision: int
    jti: str


class StepUpProof(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proof: str = Field(repr=False)
    claims: StepUpProofClaims
