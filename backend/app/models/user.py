from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Role(Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    users: Mapped[list[User]] = relationship(
        "User",
        secondary="user_roles",
        back_populates="roles",
        lazy="selectin",
    )


class User(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary="user_roles",
        back_populates="users",
        lazy="selectin",
    )
    password_credential: Mapped[PasswordCredential | None] = relationship(
        "PasswordCredential",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    sessions: Mapped[list[Session]] = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    totp_credential: Mapped[TOTPCredential | None] = relationship(
        "TOTPCredential",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    webauthn_credentials: Mapped[list[WebAuthnCredential]] = relationship(
        "WebAuthnCredential",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    recovery_codes: Mapped[list[RecoveryCode]] = relationship(
        "RecoveryCode",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class PasswordCredential(Base):
    __tablename__ = "password_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), default="argon2id", nullable=False)

    user: Mapped[User] = relationship("User", back_populates="password_credential")
