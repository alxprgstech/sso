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
from datetime import datetime
from pathlib import Path


def calculate_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def main():
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

    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = out_dir / f"sso_backup_{args.db}_{timestamp}.sql"

    print(f"[*] Starting backup for database '{args.db}'...")

    try:
        if args.docker:
            # Check docker command
            cmd = [
                "docker",
                "exec",
                "-t",
                args.container,
                "pg_dump",
                "-U",
                args.user,
                "-d",
                args.db,
                "--clean",
                "--if-exists",
            ]
            print(f"[*] Executing via Docker container '{args.container}'...")
            with open(backup_file, "wb") as f:
                subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, check=True)
        else:
            # Check pg_dump locally
            pg_dump_path = shutil.which("pg_dump")
            if not pg_dump_path:
                # If pg_dump not found locally, try docker container as fallback
                print("[!] 'pg_dump' not found in PATH, attempting docker fallback...")
                cmd = [
                    "docker",
                    "exec",
                    "-i",
                    args.container,
                    "pg_dump",
                    "-U",
                    args.user,
                    "-d",
                    args.db,
                    "--clean",
                    "--if-exists",
                ]
                with open(backup_file, "wb") as f:
                    subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, check=True)
            else:
                env = os.environ.copy()
                if "POSTGRES_PASSWORD" in os.environ:
                    env["PGPASSWORD"] = os.environ["POSTGRES_PASSWORD"]
                cmd = [
                    pg_dump_path,
                    "-h",
                    args.host,
                    "-p",
                    str(args.port),
                    "-U",
                    args.user,
                    "-d",
                    args.db,
                    "--clean",
                    "--if-exists",
                    "-f",
                    str(backup_file),
                ]
                print(f"[*] Executing pg_dump on {args.host}:{args.port}...")
                subprocess.run(cmd, env=env, check=True, stderr=subprocess.PIPE)

        if not backup_file.exists() or backup_file.stat().st_size == 0:
            print("[x] Error: Backup file is empty or was not created.")
            sys.exit(1)

        size_kb = backup_file.stat().st_size / 1024
        sha256 = calculate_sha256(backup_file)

        print("[+] Backup completed successfully!")
        print(f"    File: {backup_file.resolve()}")
        print(f"    Size: {size_kb:.2f} KB")
        print(f"    SHA-256: {sha256}")

    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.decode() if e.stderr else str(e)
        print(f"[x] Backup failed: {err_msg}", file=sys.stderr)
        if backup_file.exists():
            backup_file.unlink()
        sys.exit(1)
    except Exception as e:
        print(f"[x] Unexpected backup error: {e}", file=sys.stderr)
        if backup_file.exists():
            backup_file.unlink()
        sys.exit(1)


if __name__ == "__main__":
    main()
