from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class TOTPCredential(Base):
    __tablename__ = "totp_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="totp_credential")


class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    credential_id: Mapped[str] = mapped_column(String(512), unique=True, index=True, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transports: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(128), default="Passkey", nullable=False)

    user: Mapped[User] = relationship("User", back_populates="webauthn_credentials")


class WebAuthnChallenge(Base):
    __tablename__ = "webauthn_challenges"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    challenge: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # 'registration' | 'authentication'
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="recovery_codes")


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)

    user: Mapped[User] = relationship("User")
