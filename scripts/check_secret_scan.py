"""Fail on new detect-secrets findings without logging candidate values.

The provisional baseline contains fingerprints of historical test fixtures and
documentation examples. A new finding is never silently added to it. Each
historical signal still needs private review before full acceptance.
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / ".secrets.baseline"
REVIEWED_FIXTURE_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "docs/acceptance-goal-08.json",
        "docs/acceptance-goal-09.json",
        "docs/api.md",
        "frontend/e2e/sso.spec.ts",
        "packages/python-sdk/README.md",
        "scripts/prepare_e2e_data.py",
        "tests/integration/test_auth_sessions_pg.py",
        "tests/integration/test_bootstrap_pg.py",
        "tests/integration/test_concurrency_pg.py",
        "tests/integration/test_registration_pg.py",
        "tests/test_bootstrap_admin.py",
        "tests/test_core_verify.py",
        "tests/test_database_guard.py",
        "tests/test_ops_safety_unit.py",
        "tests/test_overnight_runner_criteria.py",
        "tests/test_registration.py",
    }
)


def scanner_command() -> str:
    found = shutil.which("detect-secrets")
    if found:
        return found
    candidate = Path(sys.executable).parent / "detect-secrets.exe"
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("detect-secrets 1.5.0 is required")


def tracked_and_new_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    paths = [item for item in result.stdout.decode("utf-8").split("\0") if item]
    return [path for path in paths if path != ".secrets.baseline"]


def scan(paths: list[str]) -> dict:
    result = subprocess.run(
        [scanner_command(), "scan", "--all-files", *paths],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def normalized(result: dict) -> dict:
    result["results"] = {
        path.replace("\\", "/"): findings for path, findings in result["results"].items()
    }
    for path, findings in result["results"].items():
        for finding in findings:
            finding["filename"] = path
    return result


def fingerprints(result: dict) -> set[tuple[str, str, str]]:
    return {
        (path, item["type"], item["hashed_secret"])
        for path, findings in result["results"].items()
        for item in findings
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="sso_secret_control_", dir=ROOT) as directory:
        fixture = Path(directory) / "synthetic.py"
        fixture.write_text(f'password = "{secrets.token_urlsafe(48)}"\n', encoding="utf-8")
        result = subprocess.run(
            [scanner_command(), "scan", "--all-files", str(fixture)],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        count = sum(map(len, json.loads(result.stdout)["results"].values()))
        if count == 0:
            raise RuntimeError("Synthetic secret control was not detected")
        print("Synthetic secret control: rejected")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--write-reviewed-baseline", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    current = normalized(scan(tracked_and_new_files()))
    current_fingerprints = fingerprints(current)
    if args.write_reviewed_baseline:
        unexpected_paths = set(current["results"]) - REVIEWED_FIXTURE_PATHS
        if unexpected_paths:
            print(f"Unreviewed candidate files: {len(unexpected_paths)}", file=sys.stderr)
            return 1
        BASELINE.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(f"Baseline fingerprints written: {len(current_fingerprints)}")
        return 0
    baseline = normalized(json.loads(BASELINE.read_text(encoding="utf-8")))
    if (
        current["version"] != baseline["version"]
        or current["plugins_used"] != baseline["plugins_used"]
    ):
        print("Scanner version or plugins changed; review required", file=sys.stderr)
        return 1
    new = current_fingerprints - fingerprints(baseline)
    print(f"Secret scan: {len(current_fingerprints)} candidates; {len(new)} new")
    if new:
        print("New candidates need private review; values are suppressed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
