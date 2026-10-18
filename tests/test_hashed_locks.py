import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.hashed_locks import check


def test_hash_companions_match_version_locks():
    check()


def test_hash_companions_reject_version_drift(tmp_path):
    from scripts.hashed_locks import LOCKS, ROOT

    for name in LOCKS:
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
        companion = name.replace(".txt", "-hashed.txt")
        (tmp_path / companion).write_bytes((ROOT / companion).read_bytes())
    (tmp_path / LOCKS[0]).write_text("synthetic==1.0\n")
    with pytest.raises(ValueError, match="disagrees"):
        check(tmp_path)


def test_pip_rejects_tampered_artifact(tmp_path: Path):
    wheel = tmp_path / "synthetic_integrity-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("synthetic_integrity.py", "VALUE = 1\n")
        archive.writestr(
            "synthetic_integrity-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: synthetic-integrity\nVersion: 1.0\n",
        )
        archive.writestr(
            "synthetic_integrity-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: regression\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("synthetic_integrity-1.0.dist-info/RECORD", "")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    requirements = tmp_path / "checked.txt"
    requirements.write_text(f"synthetic-integrity==1.0 --hash=sha256:{digest}\n")
    command = [
        sys.executable,
        "-m",
        "pip",
        "--isolated",
        "install",
        "--no-index",
        "--no-cache-dir",
        "--find-links",
        str(tmp_path),
        "--require-hashes",
        "-r",
        str(requirements),
        "--target",
    ]
    valid = subprocess.run([*command, str(tmp_path / "valid")], capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    assert (tmp_path / "valid/synthetic_integrity.py").exists()
    wheel.write_bytes(wheel.read_bytes() + b"tampered artifact")
    rejected = subprocess.run(
        [*command, str(tmp_path / "rejected")], capture_output=True, text=True
    )
    assert rejected.returncode != 0
    assert "DO NOT MATCH THE HASHES" in rejected.stderr
    assert not (tmp_path / "rejected/synthetic_integrity.py").exists()
