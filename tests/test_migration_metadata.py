"""Clean process import regression: Alembic must not see an empty metadata (F-21)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.migration_metadata import include_object


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ((None, "test_database_marker", "table", True, None), False),
        ((None, "test_database_marker", "table", True, object()), True),
        ((None, "test_database_marker", "table", False, None), True),
        ((None, "test_database_marker", "index", True, None), True),
        ((None, "users", "table", True, None), True),
        ((None, "alembic_version", "table", True, None), True),
    ],
)
def test_framework_callback_excludes_only_external_marker(arguments, expected):
    assert include_object(*arguments) is expected


def test_framework_callback_accepts_all_five_named_arguments():
    assert include_object(obj=None, name="users", type_="table", reflected=True, compare_to=None)


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
