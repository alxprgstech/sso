"""The mandatory type checker must follow real application imports, rather than Any."""

import subprocess
import sys
from pathlib import Path


def test_imported_user_uuid_cannot_be_assigned_to_int(tmp_path):
    canary = tmp_path / "typecheck_canary.py"
    canary.write_text(
        "from app.models.user import User\nwrong: int = User().id\n", encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--explicit-package-bases",
            "--ignore-missing-imports",
            "--no-incremental",
            str(canary),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, "An incompatible imported UUID must fail type checking"
    errors = [
        line for line in result.stdout.splitlines() if "typecheck_canary.py:2: error:" in line
    ]
    assert len(errors) == 1, "The canary assignment itself must be rejected"
    assert all(marker in errors[0] for marker in ("UUID", "int", "[assignment]"))
