from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class OIDCClient(Base):
    __tablename__ = "oidc_clients"

    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    client_secret_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_name: Mapped[str] = mapped_column(String(128), nullable=False)
    client_type: Mapped[str] = mapped_column(
        String(32), default="confidential", nullable=False
    )  # confidential | public
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    redirect_uris: Mapped[list[OIDCRedirectUri]] = relationship(
        "OIDCRedirectUri",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    authorization_codes: Mapped[list[AuthorizationCode]] = relationship(
        "AuthorizationCode",
        back_populates="client",
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        "RefreshToken",
        back_populates="client",
        cascade="all, delete-orphan",
    )


class OIDCRedirectUri(Base):
    __tablename__ = "oidc_redirect_uris"

    client_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("oidc_clients.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    uri: Mapped[str] = mapped_column(String(512), nullable=False)

    client: Mapped[OIDCClient] = relationship("OIDCClient", back_populates="redirect_uris")


class AuthorizationCode(Base):
    __tablename__ = "authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("oidc_clients.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(10), default="S256", nullable=False)
    nonce: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scope: Mapped[str] = mapped_column(String(255), default="openid profile email", nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )

    client: Mapped[OIDCClient] = relationship("OIDCClient", back_populates="authorization_codes")
    user: Mapped[User] = relationship("User")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("oidc_clients.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )

    client: Mapped[OIDCClient] = relationship("OIDCClient", back_populates="refresh_tokens")
    user: Mapped[User] = relationship("User")
