"""Persistent privacy state; ephemeral authorizations never contain raw secrets."""

import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class LegalAcceptance(Base):
    __tablename__ = "legal_acceptances"
    __table_args__ = (UniqueConstraint("user_id", "document_id", "version"),)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeletionAuthorization(Base):
    __tablename__ = "deletion_authorizations"
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    stage: Mapped[str] = mapped_column(String(16), default="factor")
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    webauthn_challenge: Mapped[str | None] = mapped_column(String(255), nullable=True)


class PrivacyRateWindow(Base):
    __tablename__ = "privacy_rate_windows"
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DeletedSubject(Base):
    __tablename__ = "deleted_subjects"
    # Intentionally no FK: needed to reapply erasure after restoring an older backup.
    subject_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
