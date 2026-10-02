"""Single build identity from the product VERSION and verified checkout SHA."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def build_identity(root: Path, expected_sha: str | None = None) -> dict[str, str]:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-rc\.[1-9]\d*)?", version):
        raise ValueError("Invalid product version")
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or (expected_sha and sha != expected_sha):
        raise ValueError("Build revision mismatch")
    return {"version": version, "commit_sha": sha, "release": f"alxprgs-sso@{version}+{sha}"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    identity = build_identity(Path(__file__).resolve().parents[1], args.expected_sha)
    value = json.dumps(identity, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(value, encoding="utf-8")
    else:
        print(value, end="")
