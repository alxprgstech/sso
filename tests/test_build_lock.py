"""Wheel builder graph excludes application/test dependencies and rejects missing pins."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_lock import render  # noqa: E402


def test_builder_lock_matches_installed_graph():
    value = render(ROOT)
    assert value == (ROOT / "requirements-build-lock.txt").read_text("utf-8")
    assert "hatchling==" in value and "build==" in value
    for name in ("pytest", "mypy", "ruff", "fastapi", "boto3"):
        assert f"\n{name}==" not in value


def test_builder_lock_rejects_missing_transitive_pin(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_bytes((ROOT / "backend/pyproject.toml").read_bytes())
    full = (ROOT / "requirements-lock.txt").read_text("utf-8")
    (tmp_path / "requirements-lock.txt").write_text(
        "\n".join(line for line in full.splitlines() if not line.startswith("packaging==")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing from the full lock"):
        render(tmp_path)
