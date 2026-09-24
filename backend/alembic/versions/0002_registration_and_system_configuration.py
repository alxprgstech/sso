"""Add system_configuration table for registration mode and bootstrap tracking (REG-02, SETUP-05, SETUP-06)

Revision ID: 0002_reg_system_config
Revises: 0001_initial_schema
Create Date: 2026-09-24 17:25:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002_reg_system_config"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Создаем таблицу system_configuration с ограничением id = 1
    op.create_table(
        "system_configuration",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column(
            "bootstrap_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("bootstrap_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "registration_mode", sa.String(32), nullable=False, server_default=sa.text("'closed'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("id = 1", name="ck_system_configuration_single_row"),
        sa.CheckConstraint(
            "registration_mode IN ('closed', 'open')",
            name="ck_system_configuration_registration_mode",
        ),
    )

    # 2. Инициализируем запись состояния (REG-02, SETUP-06)
    # Если в системе уже существует активный суперпользователь, фиксируем bootstrap_completed = true,
    # а режим регистрации строго инициализируем в 'closed'.
    op.execute(
        sa.text(
            """
            INSERT INTO system_configuration (id, bootstrap_completed, bootstrap_completed_at, registration_mode, updated_at)
            SELECT 1,
                   COALESCE(EXISTS(SELECT 1 FROM users WHERE is_superuser = true), false),
                   CASE WHEN EXISTS(SELECT 1 FROM users WHERE is_superuser = true) THEN CURRENT_TIMESTAMP ELSE NULL END,
                   'closed',
                   CURRENT_TIMESTAMP
            ON CONFLICT (id) DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    op.drop_table("system_configuration")
