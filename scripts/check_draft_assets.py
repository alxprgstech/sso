"""Check a draft's existing assets before uploading only missing release files."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


class DraftConflict(RuntimeError):
    pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def missing_assets(expected: Path, existing: Path) -> list[str]:
    expected_names = {path.name for path in expected.iterdir() if path.is_file()}
    existing_names = {path.name for path in existing.iterdir() if path.is_file()}
    if not expected_names or existing_names - expected_names:
        raise DraftConflict("Draft contains unexpected assets or expected bundle is empty")
    for name in existing_names:
        if digest(expected / name) != digest(existing / name):
            raise DraftConflict("Draft asset content differs from verified bundle")
    return sorted(expected_names - existing_names)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--existing", type=Path, required=True)
    args = parser.parse_args()
    try:
        for name in missing_assets(args.expected, args.existing):
            print(name)
        return 0
    except (DraftConflict, OSError) as exc:
        print(f"Draft assets rejected: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
