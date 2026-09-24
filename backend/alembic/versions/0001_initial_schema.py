"""Initial schema for ALXPRGS SSO

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-09-24 11:42:00.000000

"""
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 2. roles
    op.create_table(
        "roles",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)

    # 3. user_roles
    op.create_table(
        "user_roles",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", PG_UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # 4. password_credentials
    op.create_table(
        "password_credentials",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("algorithm", sa.String(32), nullable=False, server_default="argon2id"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_password_credentials_user_id", "password_credentials", ["user_id"], unique=True)

    # 5. sessions
    op.create_table(
        "sessions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_token_hash", sa.String(64), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_sessions_session_token_hash", "sessions", ["session_token_hash"], unique=True)
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    # 6. oidc_clients
    op.create_table(
        "oidc_clients",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("client_secret_hash", sa.String(255), nullable=True),
        sa.Column("client_name", sa.String(128), nullable=False),
        sa.Column("client_type", sa.String(32), nullable=False, server_default="confidential"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_oidc_clients_client_id", "oidc_clients", ["client_id"], unique=True)

    # 7. oidc_redirect_uris
    op.create_table(
        "oidc_redirect_uris",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("client_id", PG_UUID(as_uuid=True), sa.ForeignKey("oidc_clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uri", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_oidc_redirect_uris_client_id", "oidc_redirect_uris", ["client_id"])

    # 8. authorization_codes
    op.create_table(
        "authorization_codes",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("client_id", PG_UUID(as_uuid=True), sa.ForeignKey("oidc_clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("redirect_uri", sa.String(512), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("code_challenge_method", sa.String(10), nullable=False, server_default="S256"),
        sa.Column("nonce", sa.String(128), nullable=True),
        sa.Column("scope", sa.String(255), nullable=False, server_default="openid profile email"),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_authorization_codes_code_hash", "authorization_codes", ["code_hash"], unique=True)
    op.create_index("ix_authorization_codes_expires_at", "authorization_codes", ["expires_at"])

    # 9. refresh_tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("family_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("client_id", PG_UUID(as_uuid=True), sa.ForeignKey("oidc_clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    # 10. totp_credentials
    op.create_table(
        "totp_credentials",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_totp_credentials_user_id", "totp_credentials", ["user_id"], unique=True)

    # 11. webauthn_credentials
    op.create_table(
        "webauthn_credentials",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_id", sa.String(512), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transports", sa.String(255), nullable=True),
        sa.Column("name", sa.String(128), nullable=False, server_default="Passkey"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_webauthn_credentials_credential_id", "webauthn_credentials", ["credential_id"], unique=True)
    op.create_index("ix_webauthn_credentials_user_id", "webauthn_credentials", ["user_id"])

    # 12. webauthn_challenges
    op.create_table(
        "webauthn_challenges",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("challenge", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_webauthn_challenges_challenge", "webauthn_challenges", ["challenge"], unique=True)

    # 13. recovery_codes
    op.create_table(
        "recovery_codes",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_recovery_codes_code_hash", "recovery_codes", ["code_hash"], unique=True)
    op.create_index("ix_recovery_codes_user_id", "recovery_codes", ["user_id"])

    # 14. email_verification_tokens
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_email_verification_tokens_token_hash", "email_verification_tokens", ["token_hash"], unique=True)
    op.create_index("ix_email_verification_tokens_user_id", "email_verification_tokens", ["user_id"])

    # 15. audit_events
    op.create_table(
        "audit_events",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("email_verification_tokens")
    op.drop_table("recovery_codes")
    op.drop_table("webauthn_challenges")
    op.drop_table("webauthn_credentials")
    op.drop_table("totp_credentials")
    op.drop_table("refresh_tokens")
    op.drop_table("authorization_codes")
    op.drop_table("oidc_redirect_uris")
    op.drop_table("oidc_clients")
    op.drop_table("sessions")
    op.drop_table("password_credentials")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("users")
