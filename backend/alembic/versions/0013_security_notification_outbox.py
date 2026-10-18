"""Transactional, bounded security notification queue."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0013_security_outbox"
down_revision = "0012_canonical_credential_ids"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "security_notification_outbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= 5", name="ck_security_notification_attempts"
        ),
    )
    for column in ("next_attempt_at", "expires_at"):
        op.create_index(
            f"ix_security_notification_outbox_{column}", "security_notification_outbox", [column]
        )


def downgrade():
    op.drop_table("security_notification_outbox")
