"""Bind pending WebAuthn registration to the authenticated browser session."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_registration_session"
down_revision = "0009_limited_password_session"
branch_labels = None
depends_on = None


def upgrade():
    # Pre-upgrade registration challenges cannot prove a session binding.
    op.execute("DELETE FROM webauthn_challenges WHERE purpose='registration'")
    op.add_column("webauthn_challenges", sa.Column("session_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        None, "webauthn_challenges", "sessions", ["session_id"], ["id"], ondelete="CASCADE"
    )


def downgrade():
    op.drop_constraint(
        op.f("fk_webauthn_challenges_session_id_sessions"),
        "webauthn_challenges",
        type_="foreignkey",
    )
    op.drop_column("webauthn_challenges", "session_id")
