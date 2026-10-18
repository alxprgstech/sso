from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PendingRegistration(Base):
    __tablename__ = "pending_registrations"
    __table_args__ = (UniqueConstraint("action_hash", name="uq_pending_registration_action_hash"),)

    legal_versions: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    legal_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    link_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    action_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    send_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    request_details: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
