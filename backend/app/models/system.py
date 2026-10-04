from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import TimestampedBase


class SystemConfiguration(TimestampedBase):
    """
    Таблица-одиночка глобального состояния системы и конфигурации (REG-02, SETUP-05).
    Ограничение id = 1 обеспечивает наличие строго одной записи конфигурации в PostgreSQL.
    """

    __tablename__ = "system_configuration"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_system_configuration_single_row"),
        CheckConstraint(
            "registration_mode IN ('closed', 'open')",
            name="ck_system_configuration_registration_mode",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    bootstrap_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bootstrap_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_mode: Mapped[str] = mapped_column(String(32), default="closed", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
