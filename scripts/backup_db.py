#!/usr/bin/env python3
"""ALXPRGS SSO Database Backup Script.

Creates a PostgreSQL backup either locally via pg_dump or via docker exec.
Usage:
    python scripts/backup_db.py [--output-dir backups/] [--docker] [--db sso_db]
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.privacy_journal import EXPORT_SQL, purge_backups
except ModuleNotFoundError:
    from privacy_journal import EXPORT_SQL, purge_backups


def calculate_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backup ALXPRGS SSO Database")
    parser.add_argument("--output-dir", default="backups", help="Directory to save backup files")
    parser.add_argument(
        "--docker", action="store_true", help="Execute pg_dump inside running docker container"
    )
    parser.add_argument("--container", default="alxprgs-sso-db", help="Docker container name")
    parser.add_argument(
        "--host", default=os.getenv("POSTGRES_HOST", "localhost"), help="PostgreSQL host"
    )
    parser.add_argument(
        "--port", default=os.getenv("POSTGRES_PORT", "5432"), help="PostgreSQL port"
    )
    parser.add_argument(
        "--user", default=os.getenv("POSTGRES_USER", "sso_user"), help="PostgreSQL user"
    )
    parser.add_argument(
        "--db", default=os.getenv("POSTGRES_DB", "sso_db"), help="PostgreSQL database name"
    )

    return parser.parse_args()


def postgres_environment() -> dict[str, str]:
    env = os.environ.copy()
    if "POSTGRES_PASSWORD" in env:
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    return env


def postgres_command(args: argparse.Namespace, tool: str, options: list[str]) -> list[str]:
    if args.docker:
        return [
            "docker",
            "exec",
            "-i",
            args.container,
            tool,
            "-U",
            args.user,
            "-d",
            args.db,
            *options,
        ]
    executable = shutil.which(tool)
    if not executable:
        raise RuntimeError(
            f"{tool} is not in PATH; use --docker only for an explicitly verified container"
        )
    return [
        executable,
        "-w",
        "-h",
        args.host,
        "-p",
        str(args.port),
        "-U",
        args.user,
        "-d",
        args.db,
        *options,
    ]


def create_dump(args: argparse.Namespace, backup_file: Path) -> None:
    cmd = postgres_command(args, "pg_dump", ["--clean", "--if-exists"])
    if args.docker:
        print(f"[*] Executing via Docker container '{args.container}'...")
        with backup_file.open("wb") as output:
            subprocess.run(cmd, stdout=output, stderr=subprocess.PIPE, check=True)
    else:
        print(f"[*] Executing pg_dump on {args.host}:{args.port}...")
        subprocess.run(
            [*cmd, "-f", str(backup_file)],
            env=postgres_environment(),
            check=True,
            stderr=subprocess.PIPE,
        )
    if not backup_file.exists():
        raise RuntimeError("Backup file was not created")
    if backup_file.stat().st_size == 0:
        raise RuntimeError("Backup file is empty")


def export_snapshot_journal(args: argparse.Namespace, backup_file: Path) -> None:
    # Restore still requires a NEW journal from the authoritative database,
    # including erasures performed after this snapshot.
    cmd = postgres_command(args, "psql", ["-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", EXPORT_SQL])
    env = os.environ.copy() if args.docker else postgres_environment()
    journal = subprocess.run(cmd, env=env, check=True, capture_output=True)
    backup_file.with_suffix(".journal.json").write_bytes(journal.stdout)


def remove_failed_backup(backup_file: Path) -> None:
    for path in (backup_file, backup_file.with_suffix(".journal.json")):
        if path.exists():
            path.unlink()


def print_backup_result(backup_file: Path) -> None:
    print("[+] Backup completed successfully!")
    print(f"    File: {backup_file.resolve()}")
    print(f"    Size: {backup_file.stat().st_size / 1024:.2f} KB")
    print(f"    SHA-256: {calculate_sha256(backup_file)}")


def main() -> None:
    args = parse_arguments()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    purge_backups(out_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = out_dir / f"sso_backup_{args.db}_{timestamp}.sql"
    print(f"[*] Starting backup for database '{args.db}'...")
    try:
        create_dump(args, backup_file)
        export_snapshot_journal(args, backup_file)
        print_backup_result(backup_file)
    except subprocess.CalledProcessError as error:
        print(
            f"[x] Backup failed (exit {error.returncode}); inspect the server privately",
            file=sys.stderr,
        )
        remove_failed_backup(backup_file)
        sys.exit(1)
    except Exception as error:
        print(f"[x] Backup failed: {type(error).__name__}", file=sys.stderr)
        remove_failed_backup(backup_file)
        sys.exit(1)


if __name__ == "__main__":
    main()
