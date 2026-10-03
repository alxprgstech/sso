"""Run daily even when backup creation is suspended; owned filenames only."""

import argparse
from pathlib import Path

try:
    from scripts.privacy_journal import purge_backups
except ModuleNotFoundError:
    from privacy_journal import purge_backups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(f"Expired backup files removed: {purge_backups(args.directory)}")


if __name__ == "__main__":
    main()
