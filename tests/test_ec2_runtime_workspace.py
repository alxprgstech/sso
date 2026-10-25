"""Fresh runners do not have the ignored artifacts directory before CD verification."""

import os
import stat

import pytest

from scripts.backup_db import require_private_directory
from scripts.check_ec2_runtime import prepare_workspace


def test_fresh_checkout_creates_parent_and_owner_only_workspace(tmp_path):
    assert not (tmp_path / "artifacts").exists()
    workspace = prepare_workspace(tmp_path, "sso-ec2-check-fresh")
    assert workspace == tmp_path / "artifacts/sso-ec2-check-fresh"
    assert workspace.is_dir()
    # Actual POSIX permissions or Windows owner-only DACL, not a mocked helper.
    require_private_directory(workspace)
    if os.name != "nt":
        assert stat.S_IMODE(workspace.stat().st_mode) == 0o700


def test_existing_artifacts_preserved_and_workspace_reuse_rejected(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    marker = artifacts / "preserve.txt"
    marker.write_text("existing evidence", encoding="utf-8")
    workspace = prepare_workspace(tmp_path, "sso-ec2-check-once")
    sentinel = workspace / "preserve.txt"
    sentinel.write_text("private evidence", encoding="utf-8")
    with pytest.raises(FileExistsError):
        prepare_workspace(tmp_path, "sso-ec2-check-once")
    assert marker.read_text("utf-8") == "existing evidence"
    assert sentinel.read_text("utf-8") == "private evidence"
