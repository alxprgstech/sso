"""Extend the existing session-purpose check for forced password change."""

from alembic import op

revision = "0009_limited_password_session"
down_revision = "0008_auth_context_scopes"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f("ck_sessions_ck_sessions_purpose"), "sessions", type_="check")
    op.create_check_constraint(
        "ck_sessions_purpose",
        "sessions",
        "purpose IN ('full', 'deletion_management', 'password_change')",
    )


def downgrade():
    # This migration intentionally terminates limited sessions before restoring
    # the prior finite purpose set; it never promotes them to a full session.
    op.execute("DELETE FROM sessions WHERE purpose = 'password_change'")
    op.drop_constraint(op.f("ck_sessions_ck_sessions_purpose"), "sessions", type_="check")
    op.create_check_constraint(
        "ck_sessions_purpose", "sessions", "purpose IN ('full', 'deletion_management')"
    )
