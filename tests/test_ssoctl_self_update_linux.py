"""Isolated Linux proof of ssoctl self-update file replacement, backup and lock.

These tests use temporary directories and the current runner account only. The
production path, GitHub credentials and application state are never touched.
"""

import hashlib
import importlib.util
import os
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="real POSIX ownership, flock and atomic replacement checks",
)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sso_ec2_linux", ROOT / "deploy/ec2/ssoctl.py")
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)

SOURCE = (ROOT / "deploy/ec2/ssoctl.py").read_bytes()
COMMIT = hashlib.sha1(b"self-update linux", usedforsecurity=False).hexdigest()


def variant(label: bytes) -> bytes:
    # Comments after the entrypoint keep the revision executable and distinct.
    return SOURCE + b"\n# " + label + b"\n"


@pytest.fixture
def operator(tmp_path, monkeypatch):
    root = tmp_path / "opt"
    tools = root / "tools"
    state = tmp_path / "state"
    tools.mkdir(parents=True)
    state.mkdir()
    path = tools / "ssoctl.py"
    path.write_bytes(variant(b"previous"))
    path.chmod(0o755)
    downloads = {"candidate": SOURCE}
    monkeypatch.setattr(ctl, "ROOT", root)
    monkeypatch.setattr(ctl, "STATE", state)
    monkeypatch.setattr(ctl, "SYSTEM_PYTHON", Path(sys.executable))
    monkeypatch.setattr(ctl, "ROOT_UID", os.getuid())
    monkeypatch.setattr(ctl, "ROOT_GID", os.getgid())
    monkeypatch.setattr(ctl, "resolve_revision", lambda requested: COMMIT)
    monkeypatch.setattr(ctl, "download_operator", lambda revision: downloads["candidate"])
    return SimpleNamespace(
        root=root, tools=tools, state=state, path=path, downloads=downloads, tmp=tmp_path
    )


def candidate_temps(root: Path) -> list[Path]:
    return list((root / "tools").glob(".ssoctl-candidate-*"))


def test_installs_verified_operator_with_private_backup(operator, monkeypatch, capsys):
    previous = operator.path.read_bytes()
    previous_inode = operator.path.stat().st_ino
    monkeypatch.setattr(ctl, "run", lambda *a, **k: pytest.fail("application command must not run"))
    monkeypatch.setattr(ctl, "settings", lambda: pytest.fail("configuration must not be read"))
    monkeypatch.setattr(ctl, "current", lambda: pytest.fail("release must not be resolved"))
    monkeypatch.setattr(ctl, "notify", lambda event: pytest.fail("email must not be sent"))

    ctl.self_update(None)

    output = capsys.readouterr().out
    assert operator.path.read_bytes() == SOURCE
    info = operator.path.stat()
    assert stat.S_ISREG(info.st_mode)
    assert stat.S_IMODE(info.st_mode) == 0o755
    assert (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
    assert info.st_ino != previous_inode
    backups = list((operator.state / "operator-backups").glob("*.bak"))
    assert len(backups) == 1
    backup = backups[0]
    backup_info = backup.stat()
    assert stat.S_IMODE(backup_info.st_mode) == 0o600
    assert (backup_info.st_uid, backup_info.st_gid) == (os.getuid(), os.getgid())
    assert backup.read_bytes() == previous
    assert COMMIT in output
    assert "updated" in output
    assert str(backup) in output
    assert "Application and configuration were not changed." in output
    assert not candidate_temps(operator.root)
    assert not (operator.state / "deployed.json").exists()
    assert not (operator.state / "maintenance").exists()
    assert not (operator.state / "highwater.json").exists()


def test_identical_content_is_noop_without_replacement_or_backup(operator, capsys):
    operator.path.write_bytes(SOURCE)
    operator.path.chmod(0o755)
    before = operator.path.stat()
    ctl.self_update(None)
    after = operator.path.stat()
    output = capsys.readouterr().out
    assert output.count("already current") == 1
    assert before.st_ino == after.st_ino
    assert before.st_mtime_ns == after.st_mtime_ns
    assert operator.path.read_bytes() == SOURCE
    assert not (operator.state / "operator-backups").exists()
    assert not candidate_temps(operator.root)


def test_backup_failure_leaves_previous_operator_and_no_temp(operator, monkeypatch):
    previous = operator.path.read_bytes()
    before = operator.path.stat()

    def fail_backup(data):
        raise ctl.OperationError("backup failed")

    monkeypatch.setattr(ctl, "_write_backup", fail_backup)
    with pytest.raises(ctl.OperationError, match="backup failed"):
        ctl.self_update(None)
    after = operator.path.stat()
    assert operator.path.read_bytes() == previous
    assert after.st_ino == before.st_ino
    assert after.st_mtime_ns == before.st_mtime_ns
    assert not (operator.state / "operator-backups").exists()
    assert not candidate_temps(operator.root)


def test_failed_installed_check_restores_previous_file(operator, monkeypatch):
    previous = operator.path.read_bytes()

    def fail_check(path, expected):
        raise ctl.OperationError("post-install check failed")

    monkeypatch.setattr(ctl, "_verify_installed", fail_check)
    with pytest.raises(ctl.OperationError, match="previous file was restored") as failure:
        ctl.self_update(None)
    assert operator.path.read_bytes() == previous
    info = operator.path.stat()
    assert stat.S_IMODE(info.st_mode) == 0o755
    assert (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
    backups = list((operator.state / "operator-backups").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == previous
    assert str(backups[0]) in str(failure.value)
    assert not candidate_temps(operator.root)


def test_symlink_destination_is_refused_and_target_is_untouched(operator):
    victim = operator.root / "victim.py"
    victim.write_bytes(b"# unrelated target\n")
    victim.chmod(0o644)
    operator.path.unlink()
    operator.path.symlink_to(victim)
    with pytest.raises(ctl.OperationError, match="symlink"):
        ctl.self_update(None)
    assert victim.read_bytes() == b"# unrelated target\n"
    assert operator.path.is_symlink()
    assert operator.path.resolve() == victim
    assert not (operator.state / "operator-backups").exists()
    assert not candidate_temps(operator.root)


def test_symlinked_backup_directory_is_refused(operator):
    outside = operator.root / "outside"
    outside.mkdir()
    (operator.state / "operator-backups").symlink_to(outside, target_is_directory=True)
    previous = operator.path.read_bytes()
    with pytest.raises(ctl.OperationError, match="backup directory"):
        ctl.self_update(None)
    assert list(outside.iterdir()) == []
    assert operator.path.read_bytes() == previous
    assert not candidate_temps(operator.root)


def test_repeated_updates_never_overwrite_a_backup(operator, monkeypatch):
    class FrozenDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(ctl, "datetime", FrozenDateTime)
    revisions = [SOURCE, variant(b"b"), variant(b"c"), SOURCE, variant(b"b")]
    for candidate in revisions:
        operator.downloads["candidate"] = candidate
        ctl.self_update(None)
    backups = sorted((operator.state / "operator-backups").glob("*.bak"))
    assert len(backups) == 5
    assert len({backup.name for backup in backups}) == 5
    digest = hashlib.sha256(SOURCE).hexdigest()[:12]
    duplicates = [backup for backup in backups if digest in backup.name]
    assert len(duplicates) == 2
    assert all(backup.read_bytes() == SOURCE for backup in duplicates)
    assert operator.path.read_bytes() == variant(b"b")
    assert not candidate_temps(operator.root)


def test_shared_flock_serializes_operator_operations(operator):
    started = operator.tmp / "child-started"
    acquired = operator.tmp / "child-acquired"
    child = (
        "import importlib.util, pathlib, sys\n"
        "spec = importlib.util.spec_from_file_location('sso_child', sys.argv[1])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "module.STATE = pathlib.Path(sys.argv[2])\n"
        "pathlib.Path(sys.argv[3]).write_text('started')\n"
        "with module.locked():\n"
        "    pathlib.Path(sys.argv[4]).write_text('acquired')\n"
    )
    argv = [
        sys.executable,
        "-c",
        child,
        str(ROOT / "deploy/ec2/ssoctl.py"),
        str(operator.state),
        str(started),
        str(acquired),
    ]
    with ctl.locked():
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started.exists(), process.communicate(timeout=5)[1].decode()
        time.sleep(0.3)
        assert not acquired.exists()
    _, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr.decode()
    assert acquired.read_text() == "acquired"
