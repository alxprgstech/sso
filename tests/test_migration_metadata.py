"""Clean process import regression: Alembic must not see an empty metadata (F-21)."""

import os
import subprocess
import sys
from pathlib import Path


def test_complete_metadata_in_clean_interpreter(tmp_path):
    code = "from app.migration_metadata import target_metadata; assert {'users','sessions','authorization_codes','refresh_tokens','totp_credentials','pending_registrations','deleted_subjects','legal_acceptances'} <= set(target_metadata.tables); print(len(target_metadata.tables))"
    env = {**os.environ, "PYTHONPATH": str(Path("backend").absolute())}
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert int(result.stdout) >= 21
