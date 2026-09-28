from pathlib import Path

import pytest

from scripts.check_draft_assets import DraftConflict, missing_assets


def test_draft_upload_only_missing_identical_assets(tmp_path: Path) -> None:
    expected = tmp_path / "expected"
    existing = tmp_path / "existing"
    expected.mkdir()
    existing.mkdir()
    (expected / "a.whl").write_bytes(b"verified")
    (expected / "b.tar.gz").write_bytes(b"verified-two")
    (existing / "a.whl").write_bytes(b"verified")
    assert missing_assets(expected, existing) == ["b.tar.gz"]


@pytest.mark.parametrize("conflict", ["modified", "extra"])
def test_foreign_or_modified_draft_assets_rejected(tmp_path: Path, conflict: str) -> None:
    expected = tmp_path / "expected"
    existing = tmp_path / "existing"
    expected.mkdir()
    existing.mkdir()
    (expected / "a.whl").write_bytes(b"verified")
    (existing / "a.whl").write_bytes(b"modified" if conflict == "modified" else b"verified")
    if conflict == "extra":
        (existing / "foreign.txt").write_bytes(b"unknown")
    with pytest.raises(DraftConflict):
        missing_assets(expected, existing)
