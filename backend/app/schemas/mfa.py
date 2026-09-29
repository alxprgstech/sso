from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class TOTPSetupResponse(BaseModel):
    secret: str
    otpauth_url: str


class TOTPVerifyRequest(BaseModel):
    code: str = Field(..., pattern=r"^\d{6}$")
    mfa_token: str | None = None  # Передаётся, если подтверждение происходит на шаге входа


class PasskeyRegistrationOptionsResponse(BaseModel):
    options: dict[str, Any]


class PasskeyRegistrationVerifyRequest(BaseModel):
    credential: dict[str, Any]
    name: str = "Passkey"


class PasskeyAuthenticationOptionsResponse(BaseModel):
    options: dict[str, Any]


class PasskeyAuthenticationVerifyRequest(BaseModel):
    credential: dict[str, Any]
    mfa_token: str | None = None


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class RecoveryCodeVerifyRequest(BaseModel):
    recovery_code: str = Field(..., min_length=8, max_length=32)
    mfa_token: str | None = None


class EmailVerificationRequest(BaseModel):
    email: str | None = None


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=128)


class EmailVerificationCodeConfirmRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    code: str = Field(..., pattern=r"^[0-9]{6}$")
