"""External transaction step-up: client policy and one-use proof state."""

import sqlalchemy as sa
from alembic import op

revision = "0015_external_step_up"
down_revision = "0014_registration_browser"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "oidc_clients",
        sa.Column("step_up_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "oidc_clients",
        sa.Column(
            "step_up_assurance_levels",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "oidc_clients",
        sa.Column("step_up_actions", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "oidc_clients",
        sa.Column(
            "step_up_max_ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default="300",
        ),
    )
    op.create_check_constraint(
        "step_up_max_ttl",
        "oidc_clients",
        "step_up_max_ttl_seconds BETWEEN 30 AND 300",
    )

    op.create_table(
        "external_step_up_requests",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "client_id",
            sa.UUID(),
            sa.ForeignKey("oidc_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.UUID(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("security_revision", sa.Integer(), nullable=False),
        sa.Column("request_token_hash", sa.String(length=64), nullable=False),
        sa.Column("redirect_uri", sa.String(length=512), nullable=False),
        sa.Column("state", sa.String(length=128), nullable=False),
        sa.Column("code_challenge", sa.String(length=43), nullable=False),
        sa.Column(
            "code_challenge_method",
            sa.String(length=10),
            nullable=False,
            server_default="S256",
        ),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=280), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("assurance", sa.String(length=32), nullable=False),
        sa.Column("plan", sa.String(length=64), nullable=True),
        sa.Column("password_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totp_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("passkey_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("webauthn_challenge", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proof_token_hash", sa.String(length=64), nullable=True),
        sa.Column("proof_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'denied', 'consumed')",
            name="ck_external_step_up_requests_status",
        ),
        sa.CheckConstraint(
            "assurance IN ('reauth_basic', 'reauth_mfa', 'reauth_strict', 'reauth_password_mfa')",
            name="ck_external_step_up_requests_assurance",
        ),
    )
    op.create_index(
        "ix_external_step_up_requests_client_id",
        "external_step_up_requests",
        ["client_id"],
    )
    op.create_index(
        "ix_external_step_up_requests_user_id",
        "external_step_up_requests",
        ["user_id"],
    )
    op.create_index(
        "ix_external_step_up_requests_session_id",
        "external_step_up_requests",
        ["session_id"],
    )
    op.create_index(
        "ix_external_step_up_requests_request_token_hash",
        "external_step_up_requests",
        ["request_token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_external_step_up_requests_proof_token_hash",
        "external_step_up_requests",
        ["proof_token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_external_step_up_requests_expires_at",
        "external_step_up_requests",
        ["expires_at"],
    )


def downgrade():
    op.drop_table("external_step_up_requests")
    op.drop_constraint("ck_oidc_clients_step_up_max_ttl", "oidc_clients", type_="check")
    op.drop_column("oidc_clients", "step_up_max_ttl_seconds")
    op.drop_column("oidc_clients", "step_up_actions")
    op.drop_column("oidc_clients", "step_up_assurance_levels")
    op.drop_column("oidc_clients", "step_up_enabled")
