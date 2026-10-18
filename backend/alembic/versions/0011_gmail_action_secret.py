"""Require an independent mail-secret proof for Gmail registration actions."""

import sqlalchemy as sa
from alembic import op

revision = "0011_gmail_action_secret"
down_revision = "0010_registration_session"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pending_registrations", sa.Column("action_hash", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_pending_registration_action_hash", "pending_registrations", ["action_hash"]
    )


def downgrade():
    op.drop_constraint(
        "uq_pending_registration_action_hash", "pending_registrations", type_="unique"
    )
    op.drop_column("pending_registrations", "action_hash")
