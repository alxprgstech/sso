"""Generate pip hash companions from fixed-version PyPI artifact metadata."""

import argparse
import concurrent.futures
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ("requirements-lock.txt", "requirements-runtime-lock.txt", "requirements-build-lock.txt")


def pins(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def artifact_hashes(pin: str) -> tuple[str, list[str]]:
    package, version = pin.split(";", 1)[0].strip().split("==", 1)
    with urllib.request.urlopen(
        f"https://pypi.org/pypi/{package}/{version}/json", timeout=30
    ) as response:
        document = json.load(response)
    hashes = sorted(
        {item["digests"]["sha256"] for item in document["urls"] if not item.get("yanked")}
    )
    if not hashes or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes):
        raise ValueError(f"No valid artifacts for {package}")
    return pin, hashes


def check(root: Path = ROOT) -> None:
    for name in LOCKS:
        source = pins(root / name)
        hashed = pins(root / name.replace(".txt", "-hashed.txt"))
        reconstructed = []
        for line in hashed:
            parts = line.split(" --hash=sha256:")
            if len(parts) < 2 or any(
                not re.fullmatch(r"[0-9a-f]{64}", value) for value in parts[1:]
            ):
                raise ValueError(f"Invalid artifact hashes in {name}")
            reconstructed.append(parts[0])
        if source != reconstructed:
            raise ValueError(f"Hash companion disagrees with {name}")


def generate() -> None:
    all_pins = sorted({pin for name in LOCKS for pin in pins(ROOT / name)})
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        hashes = dict(executor.map(artifact_hashes, all_pins))
    for name in LOCKS:
        content = "# Generated from PyPI HTTPS artifact metadata by scripts/hashed_locks.py.\n"
        for pin in pins(ROOT / name):
            content += pin + "".join(f" --hash=sha256:{value}" for value in hashes[pin]) + "\n"
        (ROOT / name.replace(".txt", "-hashed.txt")).write_text(content, encoding="utf-8")
    check()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    if args.generate:
        generate()
    else:
        check()
    print("Hash companions match all three version locks")
