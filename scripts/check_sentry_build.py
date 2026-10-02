"""Offline frontend privacy/build gate; no Sentry token or network required."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_identity import build_identity
from scripts.sentry_artifacts import prepare_private_maps

root = Path(__file__).resolve().parents[1]
(root / "artifacts").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="sentry-ci-private-", dir=root / "artifacts") as private:
    prepare_private_maps(root / "frontend/dist", Path(private), build_identity(root))
assert not list((root / "frontend/dist").rglob("*.map"))
assert json.loads((root / "frontend/dist/build-info.json").read_text())["release"].startswith(
    "alxprgs-sso@"
)
print("Debug IDs/private maps validated; deployment dist contains no source maps")
