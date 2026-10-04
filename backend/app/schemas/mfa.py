from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TOTPSetupResponse(BaseModel):
    secret: str
    otpauth_url: str


class TOTPVerifyRequest(BaseModel):
    code: str = Field(..., pattern=r"^\d{6}$")
    mfa_token: str | None = Field(default=None, max_length=16384)


class PasskeyRegistrationOptionsResponse(BaseModel):
    options: dict[str, Any]


class PasskeyRegistrationVerifyRequest(BaseModel):
    credential: dict[str, Any]
    name: str = Field(default="Passkey", min_length=1, max_length=255)


class PasskeyAuthenticationOptionsResponse(BaseModel):
    options: dict[str, Any]


class PasskeyAuthenticationVerifyRequest(BaseModel):
    credential: dict[str, Any]
    mfa_token: str | None = Field(default=None, max_length=16384)


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class RecoveryCodeVerifyRequest(BaseModel):
    recovery_code: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9\- ]+$")
    mfa_token: str | None = Field(default=None, max_length=16384)


class EmailVerificationRequest(BaseModel):
    email: str | None = None


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=128)


class EmailVerificationCodeConfirmRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    code: str = Field(..., pattern=r"^[0-9]{6}$")
