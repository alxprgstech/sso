"""Immutable installed artifact metadata; source checkout fallback is local only."""

import json
from pathlib import Path


def get_build_info() -> dict[str, str]:
    artifact = Path(__file__).with_name("_build_info.json")
    if artifact.is_file():
        return json.loads(artifact.read_text(encoding="utf-8"))
    source_version = Path(__file__).resolve().parents[2] / "VERSION"
    return {
        "version": source_version.read_text(encoding="utf-8").strip(),
        "release": "",
        "commit_sha": "",
    }
