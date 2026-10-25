"""A failed backup may clean up its own files, never an existing snapshot."""

import argparse
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts import backup_db


@pytest.fixture
def backup_cli(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    args = argparse.Namespace(
        output_dir=str(tmp_path),
        db="sso_db",
        user="synthetic",
        docker=True,
        container="synthetic-postgres",
    )
    monkeypatch.setattr(backup_db, "parse_arguments", lambda: args)
    monkeypatch.setattr(backup_db, "require_private_directory", lambda _: None)
    monkeypatch.setattr(backup_db, "datetime", SimpleNamespace(now=lambda _: now))
    dump = tmp_path / f"sso_backup_sso_db_{now.strftime('%Y%m%d_%H%M%S')}.sql"
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if "pg_dump" in cmd:
            kwargs["stdout"].write(b"synthetic new dump")
        return SimpleNamespace(stdout=b"{}")

    monkeypatch.setattr(backup_db.subprocess, "run", run)
    return dump, calls


def test_dump_filename_collision_preserves_existing_dump_and_journal(backup_cli):
    dump, calls = backup_cli
    journal = dump.with_suffix(".journal.json")
    dump.write_bytes(b"existing valid dump")
    journal.write_bytes(b"existing valid journal")
    with pytest.raises(SystemExit) as result:
        backup_db.main()
    assert result.value.code == 1
    assert dump.read_bytes() == b"existing valid dump"
    assert journal.read_bytes() == b"existing valid journal"
    assert not calls


def test_journal_collision_preserves_existing_journal_and_removes_only_new_dump(backup_cli):
    dump, calls = backup_cli
    journal = dump.with_suffix(".journal.json")
    journal.write_bytes(b"existing journal")
    with pytest.raises(SystemExit) as result:
        backup_db.main()
    assert result.value.code == 1
    assert not dump.exists()
    assert journal.read_bytes() == b"existing journal"
    assert len(calls) == 2


def test_failed_pg_dump_removes_its_own_partial_file(backup_cli, monkeypatch):
    dump, _ = backup_cli

    def fail(cmd, **kwargs):
        kwargs["stdout"].write(b"partial")
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(backup_db.subprocess, "run", fail)
    with pytest.raises(SystemExit) as result:
        backup_db.main()
    assert result.value.code == 1
    assert not dump.exists()


def test_failed_journal_write_removes_only_new_files(backup_cli, monkeypatch):
    dump, _ = backup_cli
    original_sync = backup_db.os.fsync
    calls = []

    def fail_sync(descriptor):
        calls.append(descriptor)
        if len(calls) == 2:
            raise OSError("synthetic full disk")
        original_sync(descriptor)

    monkeypatch.setattr(backup_db.os, "fsync", fail_sync)
    with pytest.raises(SystemExit) as result:
        backup_db.main()
    assert result.value.code == 1
    assert len(calls) == 2
    assert not dump.exists() and not dump.with_suffix(".journal.json").exists()
