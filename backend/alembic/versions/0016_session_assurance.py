"""Session MFA assurance and OIDC grant assurance snapshots.

Existing sessions and grants deliberately become non-assured: a password-only
session created before this migration must never satisfy the administrator MFA
policy.  No session is promoted and no factor is created.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_session_assurance"
down_revision = "0015_external_step_up"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sessions",
        sa.Column("mfa_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("sessions", sa.Column("mfa_method", sa.String(length=32), nullable=True))
    op.add_column(
        "sessions", sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "sessions",
        sa.Column("amr", sa.String(length=64), nullable=False, server_default="pwd"),
    )
    op.drop_constraint(op.f("ck_sessions_ck_sessions_purpose"), "sessions", type_="check")
    op.create_check_constraint(
        "ck_sessions_purpose",
        "sessions",
        "purpose IN ('full', 'deletion_management', 'password_change', 'admin_mfa_enrollment')",
    )
    op.create_check_constraint(
        "ck_sessions_mfa_method",
        "sessions",
        "mfa_method IS NULL OR mfa_method IN ('totp', 'passkey', 'recovery_code')",
    )

    for table in ("authorization_codes", "refresh_tokens"):
        op.add_column(
            table,
            sa.Column("mfa_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.add_column(
            table,
            sa.Column("amr", sa.String(length=64), nullable=False, server_default="pwd"),
        )


def downgrade():
    # Reverting the assurance-aware code must not leave old sessions/grants that
    # the previous revision would treat as sufficient for administrative access.
    op.execute("DELETE FROM sessions")
    op.execute("DELETE FROM authorization_codes")
    op.execute("UPDATE refresh_tokens SET is_revoked = true")
    for table in ("authorization_codes", "refresh_tokens"):
        op.drop_column(table, "amr")
        op.drop_column(table, "mfa_verified")
    op.drop_constraint(op.f("ck_sessions_ck_sessions_mfa_method"), "sessions", type_="check")
    op.drop_constraint(op.f("ck_sessions_ck_sessions_purpose"), "sessions", type_="check")
    op.create_check_constraint(
        "ck_sessions_purpose",
        "sessions",
        "purpose IN ('full', 'deletion_management', 'password_change')",
    )
    op.drop_column("sessions", "amr")
    op.drop_column("sessions", "mfa_verified_at")
    op.drop_column("sessions", "mfa_method")
    op.drop_column("sessions", "mfa_verified")
