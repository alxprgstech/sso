#!/usr/bin/env python3
"""Offline transactional TOTP ciphertext migration; keys are read from private files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session


def rotate_ciphertexts(values: list[str], old_key: bytes, new_key: bytes) -> list[str]:
    old, new = Fernet(old_key.strip()), Fernet(new_key.strip())
    for value in values:
        old.decrypt(value.encode("ascii"))
    rotator = MultiFernet([new, old])
    return [rotator.rotate(value.encode("ascii")).decode("ascii") for value in values]


def migrate(session: Session, old_key: bytes, new_key: bytes) -> int:
    from app.models.mfa import TOTPCredential

    session.execute(text("SELECT pg_advisory_xact_lock(741239812)"))
    rows = list(session.scalars(select(TOTPCredential).with_for_update()))
    destinations = [(row, "encrypted_secret") for row in rows]
    destinations += [
        (row, "pending_encrypted_secret") for row in rows if row.pending_encrypted_secret
    ]
    values = rotate_ciphertexts(
        [getattr(row, field) for row, field in destinations], old_key, new_key
    )
    for (row, field), value in zip(destinations, values, strict=True):
        setattr(row, field, value)
    session.flush()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-key-file", type=Path, required=True)
    parser.add_argument("--new-key-file", type=Path, required=True)
    parser.add_argument("--offline-maintenance", action="store_true", required=True)
    parser.add_argument("--confirm", action="store_true", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    import app.models  # noqa: F401 — Register the complete ORM graph.
    from app.config import get_settings

    try:
        settings = get_settings()
        old_key, new_key = (
            args.old_key_file.read_bytes().strip(),
            args.new_key_file.read_bytes().strip(),
        )
        if old_key.decode("ascii") != settings.TOTP_ENCRYPTION_KEY or old_key == new_key:
            raise ValueError("Old key must match the selected deployment, new key must differ")
        engine = create_engine(settings.DATABASE_URL_SYNC, hide_parameters=True)
        try:
            with Session(engine) as session, session.begin():
                count = migrate(session, old_key, new_key)
        finally:
            engine.dispose()
    except Exception:
        print(
            "TOTP migration failed; transaction rolled back. Sensitive diagnostics withheld.",
            file=sys.stderr,
        )
        return 1
    print(f"Migrated {count} TOTP credentials. Install the new key before restarting all workers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
