"""Canonicalize credential IDs without losing or silently merging credentials."""

import base64
import binascii
import re

import sqlalchemy as sa
from alembic import op

revision = "0012_canonical_credential_ids"
down_revision = "0011_gmail_action_secret"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, credential_id FROM webauthn_credentials FOR UPDATE")
    ).all()
    canonical = {}
    updates = []
    for row in rows:
        value = row.credential_id
        try:
            if not re.fullmatch(r"[A-Za-z0-9_+/\-]{1,512}={0,2}", value):
                raise ValueError
            raw = value.rstrip("=")
            decoded = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
            normalized = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
            if not normalized:
                raise ValueError
        except (ValueError, binascii.Error):
            raise RuntimeError(
                "Credential ID migration rejected an invalid stored identifier; no rows removed"
            ) from None
        if normalized in canonical:
            raise RuntimeError(
                "Credential ID migration detected a canonical collision; no rows removed"
            )
        canonical[normalized] = row.id
        updates.append((row.id, normalized))
    for identifier, normalized in updates:
        connection.execute(
            sa.text("UPDATE webauthn_credentials SET credential_id=:value WHERE id=:id"),
            {"value": normalized, "id": identifier},
        )


def downgrade():
    # Canonical binary identities cannot recover their original textual padding.
    pass
