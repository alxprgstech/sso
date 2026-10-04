"""Align application indexes with complete ORM metadata (F-21)."""

from alembic import op

revision = "0005_schema_indexes"
down_revision = "0004_privacy"
branch_labels = None
depends_on = None

INDEXES = (
    ("authorization_codes", "client_id"),
    ("authorization_codes", "user_id"),
    ("refresh_tokens", "client_id"),
    ("refresh_tokens", "user_id"),
    ("email_verification_tokens", "expires_at"),
    ("webauthn_challenges", "expires_at"),
    ("webauthn_challenges", "user_id"),
)


def upgrade() -> None:
    for table, column in INDEXES:
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table, column in reversed(INDEXES):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
