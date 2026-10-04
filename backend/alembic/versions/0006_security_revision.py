"""Account security revision and persistent one-use MFA steps (F-04/F-05/F-06)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0006_security_revision"
down_revision = "0005_schema_indexes"
branch_labels = None
depends_on = None

TABLES = ("users", "sessions", "authorization_codes", "refresh_tokens", "email_verification_tokens")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table, sa.Column("security_revision", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_table(
        "authentication_steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("security_revision", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_authentication_steps_token_hash"),
    )
    op.create_index("ix_authentication_steps_user_id", "authentication_steps", ["user_id"])
    op.create_index("ix_authentication_steps_expires_at", "authentication_steps", ["expires_at"])


def downgrade() -> None:
    op.drop_table("authentication_steps")
    for table in reversed(TABLES):
        op.drop_column(table, "security_revision")
