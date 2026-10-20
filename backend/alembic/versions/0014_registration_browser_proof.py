"""Bind pending enrollment to its initiating browser; legacy pending fails closed."""

from alembic import op
import sqlalchemy as sa

revision = "0014_registration_browser"
down_revision = "0013_security_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pending_registrations", sa.Column("browser_secret_hash", sa.String(64)))


def downgrade() -> None:
    op.drop_column("pending_registrations", "browser_secret_hash")
