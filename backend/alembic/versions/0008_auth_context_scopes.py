"""Authentication timestamp, client scope policy, expiring temporary passwords."""

import sqlalchemy as sa
from alembic import op

revision = "0008_auth_context_scopes"
down_revision = "0007_action_reauthentication"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("sessions", "authorization_codes", "refresh_tokens"):
        op.add_column(table, sa.Column("auth_time", sa.DateTime(timezone=True), nullable=True))
        op.execute(sa.text(f"UPDATE {table} SET auth_time = created_at"))
        op.alter_column(table, "auth_time", nullable=False)
    op.add_column(
        "oidc_clients",
        sa.Column(
            "allowed_scopes", sa.String(255), nullable=False, server_default="openid profile email"
        ),
    )
    # Old grants have no recoverable original auth_time; never infer a fresh
    # authentication from the time of the latest refresh token issuance.
    op.execute("UPDATE authorization_codes SET is_used = true")
    op.execute("UPDATE refresh_tokens SET is_revoked = true")
    op.add_column(
        "password_credentials",
        sa.Column("requires_change", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "password_credentials",
        sa.Column("temporary_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "password_credentials",
        sa.Column("temporary_consumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    for field in ("temporary_consumed_at", "temporary_expires_at", "requires_change"):
        op.drop_column("password_credentials", field)
    op.drop_column("oidc_clients", "allowed_scopes")
    for table in ("refresh_tokens", "authorization_codes", "sessions"):
        op.drop_column(table, "auth_time")
