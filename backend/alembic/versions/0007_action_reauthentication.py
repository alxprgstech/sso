"""One-use action authorization and separate pending TOTP enrollment."""

import sqlalchemy as sa
from alembic import op

revision = "0007_action_reauthentication"
down_revision = "0006_security_revision"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "security_authorizations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "session_id",
            sa.UUID(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("security_revision", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("webauthn_challenge", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("user_id", "session_id", "expires_at"):
        op.create_index(f"ix_security_authorizations_{name}", "security_authorizations", [name])
    op.add_column(
        "totp_credentials", sa.Column("pending_encrypted_secret", sa.Text(), nullable=True)
    )
    op.add_column(
        "totp_credentials",
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("totp_credentials", sa.Column("pending_session_id", sa.UUID(), nullable=True))


def downgrade():
    for name in ("pending_session_id", "pending_expires_at", "pending_encrypted_secret"):
        op.drop_column("totp_credentials", name)
    op.drop_table("security_authorizations")
