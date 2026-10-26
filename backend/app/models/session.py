from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('full', 'deletion_management', 'password_change', 'admin_mfa_enrollment')",
            name="ck_sessions_purpose",
        ),
        CheckConstraint(
            "mfa_method IS NULL OR mfa_method IN ('totp', 'passkey', 'recovery_code')",
            name="ck_sessions_mfa_method",
        ),
    )
    security_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    purpose: Mapped[str] = mapped_column(String(32), default="full", nullable=False)
    auth_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # Server-written proof that this exact session completed a verified second
    # factor. Client input can never set these columns.
    mfa_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    mfa_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amr: Mapped[str] = mapped_column(
        String(64), default="pwd", server_default="pwd", nullable=False
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    session_token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship("User", back_populates="sessions")
