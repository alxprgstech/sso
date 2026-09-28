"""The secret scanner must read UTF-8 files on every supported host."""

import secrets
import tempfile
from pathlib import Path

from scripts.check_secret_scan import ROOT, scan


def test_scanner_reads_utf8_file_with_cyrillic_comment(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONUTF8", "0")
    with tempfile.TemporaryDirectory(prefix="sso_utf8_scan_", dir=ROOT) as directory:
        fixture = Path(directory) / "synthetic.py"
        fixture.write_text(
            '# Тест кодировки UTF-8\npassword = "' + secrets.token_urlsafe(48) + '"\n',
            encoding="utf-8",
        )
        result = scan([fixture.relative_to(ROOT).as_posix()])
    assert sum(map(len, result["results"].values())) > 0
