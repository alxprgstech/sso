"""Minimal erasure journal; UUIDs only. Restore applies it in the dump transaction."""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXPORT_SQL = """SELECT json_build_object('version', 1, 'generated_at', clock_timestamp(),
 'subjects', COALESCE((SELECT json_agg(json_build_object('subject_id', subject_id,
 'deleted_at', deleted_at)) FROM deleted_subjects
 WHERE deleted_at > clock_timestamp() - interval '30 days'), '[]'::json));"""


def current_journal(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") != 1:
        raise ValueError("Invalid journal")
    if not isinstance(document.get("subjects"), list):
        raise ValueError("Invalid journal")
    return document


def journal_generation(document: dict) -> datetime:
    generated = datetime.fromisoformat(document["generated_at"])
    if generated.tzinfo is None:
        raise ValueError("Export a current journal before restoring")
    now = datetime.now(timezone.utc)
    if generated > now + timedelta(minutes=5):
        raise ValueError("Export a current journal before restoring")
    if now - generated > timedelta(minutes=5):
        raise ValueError("Export a current journal before restoring")
    return generated


def deletion_entry(entry: dict, generated: datetime) -> tuple[str, datetime]:
    subject = str(uuid.UUID(entry["subject_id"]))
    deleted = datetime.fromisoformat(entry["deleted_at"])
    if deleted.tzinfo is None:
        raise ValueError("Invalid deletion time")
    if deleted > generated:
        raise ValueError("Invalid deletion time")
    if generated - deleted > timedelta(days=30):
        raise ValueError("Invalid deletion time")
    return subject, deleted


def subject_erasure_sql(subject: str, deleted: datetime) -> str:
    # Only normalized UUID/datetime from deletion_entry enter this SQL.
    return f"""
UPDATE audit_events SET user_id=NULL, ip_address=NULL, user_agent=NULL, details='{{}}'::jsonb
 WHERE user_id='{subject}'::uuid OR details->>'target_user_id'='{subject}'
 OR details->>'created_user_id'='{subject}'
 OR details->>'identifier' IN (SELECT username FROM users WHERE id='{subject}'::uuid)
 OR details->>'identifier' IN (SELECT email FROM users WHERE id='{subject}'::uuid)
 OR details->>'username' IN (SELECT username FROM users WHERE id='{subject}'::uuid);
DELETE FROM pending_registrations WHERE lower(email) IN
 (SELECT lower(email) FROM users WHERE id='{subject}'::uuid) OR lower(username) IN
 (SELECT lower(username) FROM users WHERE id='{subject}'::uuid);
DELETE FROM users WHERE id='{subject}'::uuid;
INSERT INTO deleted_subjects(id, created_at, subject_id, deleted_at)
 VALUES (gen_random_uuid(), '{deleted.isoformat()}', '{subject}', '{deleted.isoformat()}')
 ON CONFLICT(subject_id) DO NOTHING;
"""


def restore_sql(path: Path) -> str:
    document = current_journal(path)
    generated = journal_generation(document)
    statements = [
        subject_erasure_sql(*deletion_entry(entry, generated)) for entry in document["subjects"]
    ]
    # pg_dump leaves search_path empty; resolve only our schema. The caller keeps
    # this journal and the dump in one transaction; it must use a fresh export.
    return "SET LOCAL search_path = public, pg_catalog;\n" + ("\n".join(statements) or "SELECT 1;")


def purge_backups(directory: Path) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    removed = 0
    for path in directory.iterdir():
        match = re.fullmatch(
            r"sso_backup_[A-Za-z0-9_-]+_(\d{8}_\d{6})\.(sql|journal.json)", path.name
        )
        if match and path.is_file() and not path.is_symlink():
            created = datetime.strptime(match[1], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
            if created <= cutoff:
                path.unlink()
                removed += 1
    return removed
