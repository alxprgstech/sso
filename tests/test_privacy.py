"""Pure validation/minimization and recovery preflight checks."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.core.privacy import short_user_agent
from app.legal import DOCUMENTS, REQUIRED_DOCUMENTS, validate_versions
from app.schemas.auth import RegisterRequest
from fastapi import HTTPException
from pydantic import ValidationError

from scripts.privacy_journal import purge_backups, restore_sql


def test_two_explicit_unchecked_agreements_required():
    fields = dict(
        username="privacy_test",
        email="privacy@example.test",
        password="SyntheticPassword2026!",  # pragma: allowlist secret -- synthetic test password
        confirm_password="SyntheticPassword2026!",  # pragma: allowlist secret -- synthetic test password
        legal_versions=REQUIRED_DOCUMENTS,
    )
    for terms, consent in [(None, None), (False, True), (True, False), (1, True), (True, "true")]:
        with pytest.raises(ValidationError):
            RegisterRequest(**fields, terms_accepted=terms, data_processing_consent=consent)
    assert RegisterRequest(**fields, terms_accepted=True, data_processing_consent=True)
    with pytest.raises(HTTPException):
        validate_versions({"terms": "old", "data-consent": "old"})
    assert {item["path"] for item in DOCUMENTS} == {
        "/privacy",
        "/terms",
        "/cookies",
        "/data-consent",
    }


def test_device_description_cannot_retain_arbitrary_ua():
    description = short_user_agent("Mozilla/5.0 Windows NT Chrome/123.0 canary-private-identifier")
    assert "canary" not in description and "123" not in description
    assert short_user_agent("user@example.test") == "Неизвестно / Неизвестно / Компьютер"


def test_journal_rejects_stale_or_untrusted_sql_and_retention(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "journal.json"
    document = {
        "version": 1,
        "generated_at": now.isoformat(),
        "subjects": [
            {"subject_id": str(uuid.uuid4()), "deleted_at": (now - timedelta(days=1)).isoformat()}
        ],
    }
    path.write_text(json.dumps(document))
    assert "DELETE FROM users" in restore_sql(path)
    document["subjects"][0]["subject_id"] = "'); DROP TABLE users;--"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        restore_sql(path)
    document["subjects"] = []
    document["generated_at"] = (now - timedelta(minutes=6)).isoformat()
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        restore_sql(path)
    old = tmp_path / f"sso_backup_test_{(now - timedelta(days=31)).strftime('%Y%m%d_%H%M%S')}.sql"
    old.write_text("synthetic dump")
    unrelated = tmp_path / "operator_notes.sql"
    unrelated.write_text("preserve")
    assert purge_backups(tmp_path) == 1
    assert unrelated.exists() and not old.exists()
