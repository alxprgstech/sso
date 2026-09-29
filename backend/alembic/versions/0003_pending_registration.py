"""Create pending registrations and add code challenges to existing email tokens.

Revision ID: 0003_pending_registration
Revises: 0002_reg_system_config
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0003_pending_registration"
down_revision: Union[str, None] = "0002_reg_system_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_registrations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("link_hash", sa.String(64), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("send_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_details", JSONB(), nullable=False),
        sa.UniqueConstraint("email", name="uq_pending_registrations_email"),
        sa.UniqueConstraint("link_hash", name="uq_pending_registrations_link_hash"),
        sa.CheckConstraint(
            "failed_attempts BETWEEN 0 AND 5", name="ck_pending_registration_attempts"
        ),
        sa.CheckConstraint("send_count BETWEEN 1 AND 3", name="ck_pending_registration_sends"),
    )
    op.create_index("ix_pending_registrations_expires_at", "pending_registrations", ["expires_at"])
    op.add_column("email_verification_tokens", sa.Column("code_hash", sa.String(64), nullable=True))
    op.add_column(
        "email_verification_tokens",
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("email_verification_tokens", "failed_attempts")
    op.drop_column("email_verification_tokens", "code_hash")
    op.drop_index("ix_pending_registrations_expires_at", table_name="pending_registrations")
    op.drop_table("pending_registrations")
