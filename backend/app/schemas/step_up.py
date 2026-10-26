"""Wire contracts for cross-application transaction step-up."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Assurance = Literal["reauth_basic", "reauth_mfa", "reauth_strict", "reauth_password_mfa"]
StepUpMethod = Literal["password", "totp", "passkey"]


class StepUpRequestCreate(BaseModel):
    """Server-to-server request; client credentials travel only in Basic auth."""

    model_config = ConfigDict(extra="forbid")

    subject: uuid.UUID
    action: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
    payload_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    description: str = Field(..., min_length=1, max_length=280)
    assurance: Assurance
    redirect_uri: str = Field(..., min_length=1, max_length=512)
    state: str = Field(..., min_length=16, max_length=128)
    nonce: str = Field(..., min_length=16, max_length=128)
    code_challenge: str = Field(..., pattern=r"^[A-Za-z0-9_-]{43}$")
    code_challenge_method: Literal["S256"] = "S256"
    ttl_seconds: int = Field(default=300, ge=30, le=300)

    @field_validator("description")
    @classmethod
    def plain_description(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Описание действия должно быть однострочным текстом")
        if any(character in "<>" for character in value):
            raise ValueError("HTML в описании действия запрещён")
        if value != value.strip():
            raise ValueError("Описание действия не должно содержать внешние пробелы")
        return value

    @field_validator("state", "nonce")
    @classmethod
    def high_entropy_marker(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._~-]{16,128}", value):
            raise ValueError("state/nonce должны содержать не менее 16 безопасных символов")
        return value


class StepUpPlan(BaseModel):
    id: str
    label: str
    methods: list[StepUpMethod]


class StepUpRequestResponse(BaseModel):
    request_token: str = Field(..., repr=False)
    authorization_url: str
    client_name: str
    action: str
    description: str
    payload_hash: str
    assurance: Assurance
    assurance_label: str
    plans: list[StepUpPlan]
    expires_at: datetime


class StepUpDetailsResponse(BaseModel):
    client_name: str
    action: str
    description: str
    payload_hash: str
    assurance: Assurance
    assurance_label: str
    plans: list[StepUpPlan]
    verified_methods: list[StepUpMethod]
    plan: str | None = None
    status: str
    passkey_enabled: bool
    expires_at: datetime


class StepUpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: str = Field(..., min_length=1, max_length=64)
    method: StepUpMethod
    password: str | None = Field(default=None, max_length=128)
    code: str | None = Field(default=None, max_length=128)
    credential: dict[str, Any] | None = None

    @field_validator("plan")
    @classmethod
    def sane_plan(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z_]{1,64}", value):
            raise ValueError("Некорректный план подтверждения")
        return value


class StepUpPasskeyOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: str = Field(..., min_length=1, max_length=64)

    @field_validator("plan")
    @classmethod
    def sane_plan(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z_]{1,64}", value):
            raise ValueError("Некорректный план подтверждения")
        return value


class StepUpVerifyResponse(BaseModel):
    completed: bool
    status: str
    verified_methods: list[StepUpMethod]
    remaining_methods: list[StepUpMethod]
    redirect_to: str | None = None
    expires_at: datetime


class StepUpDenyResponse(BaseModel):
    status: Literal["denied"]


class StepUpRedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=32, max_length=128)
    code_verifier: str = Field(..., pattern=r"^[A-Za-z0-9._~-]{43,128}$")
    redirect_uri: str = Field(..., min_length=1, max_length=512)


class StepUpProofResponse(BaseModel):
    proof: str
    claims: dict[str, Any]


class StepUpAdminPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_up_enabled: bool
    assurance_levels: list[Assurance] = Field(default_factory=list, max_length=4)
    actions: list[str] = Field(default_factory=list, max_length=32)
    max_ttl_seconds: int = Field(default=300, ge=30, le=300)

    @field_validator("actions")
    @classmethod
    def action_policy(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Действия не должны повторяться")
        for action in value:
            if not re.fullmatch(r"[a-z0-9][a-z0-9_.:-]{0,63}", action):
                raise ValueError("Недопустимый идентификатор действия")
        return value

    @field_validator("assurance_levels")
    @classmethod
    def level_policy(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Уровни не должны повторяться")
        return value
