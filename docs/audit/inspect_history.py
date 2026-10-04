"""Offline, read-only Git history scan. Output contains fingerprints, never values.

Run with the repository's detect-secrets 1.5.0 environment. It is an audit aid,
not a replacement for privately reviewing candidates or revoking leaked secrets.
"""

import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from detect_secrets.core.scan import scan_file
from detect_secrets.settings import transient_settings


def git(*args):
    return subprocess.check_output(["git", *args])


def main():
    root = Path(__file__).resolve().parents[2]
    baseline = json.loads((root / ".secrets.baseline").read_text(encoding="utf-8"))
    settings = {name: baseline[name] for name in ("plugins_used", "filters_used")}
    # Verification filters can contact a provider. This scan is strictly offline.
    settings["filters_used"] = [
        item for item in settings["filters_used"] if "verification" not in item["path"]
    ]
    known = {item["hashed_secret"] for items in baseline["results"].values() for item in items}
    candidates = []
    blobs = 0
    with (
        transient_settings(settings),
        tempfile.TemporaryDirectory(dir=root / "artifacts/audit") as directory,
    ):
        for entry in git("rev-list", "--objects", "--all").decode("utf-8").splitlines():
            parts = entry.split(" ", 1)
            if len(parts) != 2 or parts[1] == ".secrets.baseline":
                continue
            oid, path = parts
            if git("cat-file", "-t", oid).strip() != b"blob":
                continue
            content = git("cat-file", "blob", oid)
            if b"\x00" in content:
                continue
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            blobs += 1
            # File parsing preserves string-literal/context filters. The ad-hoc
            # scan_line API treats a whole source line as an eager secret candidate.
            temporary = Path(directory) / ("source" + Path(path).suffix)
            temporary.write_bytes(content)
            for item in scan_file(str(temporary)):
                candidates.append(
                    {
                        "blob": oid,
                        "path": path,
                        "line": item.line_number,
                        "type": item.type,
                        "fingerprint": item.secret_hash,
                        "in_current_baseline": item.secret_hash in known,
                    }
                )
            temporary.unlink()
    output = root / "artifacts/audit/history-scan.json"
    output.write_text(
        json.dumps({"text_blobs": blobs, "candidates": candidates}, indent=2), encoding="utf-8"
    )
    unreviewed = [item for item in candidates if not item["in_current_baseline"]]
    print(
        json.dumps(
            {
                "text_blobs": blobs,
                "signals": len(candidates),
                "signals_outside_current_baseline": len(unreviewed),
                "outside_baseline_by_path": dict(Counter(item["path"] for item in unreviewed)),
            }
        )
    )


if __name__ == "__main__":
    main()
