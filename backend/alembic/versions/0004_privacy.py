"""Consent records, restricted sessions and delayed account erasure."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004_privacy"
down_revision = "0003_pending_registration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("deletion_requested_at", "deletion_scheduled_for", "deletion_request_allowed_at"):
        op.add_column("users", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_deletion_scheduled_for", "users", ["deletion_scheduled_for"])
    op.create_check_constraint(
        "ck_users_deletion_pair",
        "users",
        "(deletion_requested_at IS NULL) = (deletion_scheduled_for IS NULL)",
    )
    op.add_column(
        "sessions", sa.Column("purpose", sa.String(32), nullable=False, server_default="full")
    )
    op.create_check_constraint(
        "ck_sessions_purpose", "sessions", "purpose IN ('full', 'deletion_management')"
    )
    op.add_column(
        "pending_registrations",
        sa.Column("legal_versions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "pending_registrations",
        sa.Column("legal_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("totp_credentials", sa.Column("last_verified_step", sa.Integer(), nullable=True))

    # Explicit schema definitions keep this historical migration independent of later models.
    def base():
        return [
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ]

    op.create_table(
        "legal_acceptances",
        *base(),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "document_id", "version", name="uq_legal_acceptance_version"
        ),
    )
    op.create_index("ix_legal_acceptances_user_id", "legal_acceptances", ["user_id"])
    op.create_table(
        "deletion_authorizations",
        *base(),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("webauthn_challenge", sa.String(255), nullable=True),
        sa.CheckConstraint("action IN ('request', 'cancel')", name="ck_deletion_action"),
        sa.CheckConstraint("stage IN ('factor', 'authorized')", name="ck_deletion_stage"),
        sa.CheckConstraint("failed_attempts BETWEEN 0 AND 5", name="ck_deletion_attempts"),
    )
    op.create_index("ix_deletion_authorizations_user_id", "deletion_authorizations", ["user_id"])
    op.create_index(
        "ix_deletion_authorizations_expires_at", "deletion_authorizations", ["expires_at"]
    )
    op.create_table(
        "privacy_rate_windows",
        *base(),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_privacy_rate_windows_expires_at", "privacy_rate_windows", ["expires_at"])
    op.create_table(
        "deleted_subjects",
        *base(),
        sa.Column("subject_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_deleted_subjects_deleted_at", "deleted_subjects", ["deleted_at"])
    # Previously collected geo and full User-Agent are unnecessary. This privacy
    # cleanup is intentionally irreversible even if the schema is downgraded.
    op.execute("UPDATE sessions SET user_agent=NULL")
    op.execute(
        "UPDATE audit_events SET user_agent=NULL, details=details - ARRAY['city','country','identifier','username','email','name','credential_id']"
    )
    op.execute(
        "UPDATE pending_registrations SET request_details=request_details - ARRAY['city','country','user_agent']"
    )


def downgrade() -> None:
    for name in (
        "deleted_subjects",
        "privacy_rate_windows",
        "deletion_authorizations",
        "legal_acceptances",
    ):
        op.drop_table(name)
    op.drop_column("totp_credentials", "last_verified_step")
    op.drop_column("pending_registrations", "legal_accepted_at")
    op.drop_column("pending_registrations", "legal_versions")
    op.drop_constraint("ck_sessions_purpose", "sessions", type_="check")
    op.drop_column("sessions", "purpose")
    op.drop_constraint("ck_users_deletion_pair", "users", type_="check")
    op.drop_index("ix_users_deletion_scheduled_for", table_name="users")
    for name in ("deletion_request_allowed_at", "deletion_scheduled_for", "deletion_requested_at"):
        op.drop_column("users", name)
