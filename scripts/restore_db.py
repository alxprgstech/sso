#!/usr/bin/env python3
"""ALXPRGS SSO Database Restore Script.

Restores a PostgreSQL backup either locally via psql or via docker exec.
Usage:
    python scripts/restore_db.py <backup_file.sql> --confirm [--docker] [--db sso_db]
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Restore ALXPRGS SSO Database")
    parser.add_argument("backup_file", help="Path to SQL backup file")
    parser.add_argument("--confirm", action="store_true", help="Confirmation flag required to prevent accidental restore")
    parser.add_argument("--docker", action="store_true", help="Execute restore inside running docker container")
    parser.add_argument("--container", default="alxprgs-sso-db", help="Docker container name")
    parser.add_argument("--host", default=os.getenv("POSTGRES_HOST", "localhost"), help="PostgreSQL host")
    parser.add_argument("--port", default=os.getenv("POSTGRES_PORT", "5432"), help="PostgreSQL port")
    parser.add_argument("--user", default=os.getenv("POSTGRES_USER", "sso_user"), help="PostgreSQL user")
    parser.add_argument("--db", default=os.getenv("POSTGRES_DB", "sso_db"), help="PostgreSQL database name")

    args = parser.parse_args()

    backup_path = Path(args.backup_file)
    if not backup_path.exists() or backup_path.stat().st_size == 0:
        print(f"[x] Error: Backup file '{backup_path}' does not exist or is empty.", file=sys.stderr)
        sys.exit(1)

    if not args.confirm:
        print("[!] Safety check failed: Restoring a database replaces existing data.")
        print("    To proceed, please pass the '--confirm' flag explicitly.")
        sys.exit(1)

    print(f"[*] Starting restore for database '{args.db}' from '{backup_path.name}'...")

    try:
        if args.docker:
            print(f"[*] Restoring via Docker container '{args.container}'...")
            cmd = ["docker", "exec", "-i", args.container, "psql", "-U", args.user, "-d", args.db]
            with open(backup_path, "rb") as f:
                subprocess.run(cmd, stdin=f, stderr=subprocess.PIPE, check=True)
        else:
            psql_path = shutil.which("psql")
            if not psql_path:
                print("[!] 'psql' not found in PATH, attempting docker fallback...")
                cmd = ["docker", "exec", "-i", args.container, "psql", "-U", args.user, "-d", args.db]
                with open(backup_path, "rb") as f:
                    subprocess.run(cmd, stdin=f, stderr=subprocess.PIPE, check=True)
            else:
                env = os.environ.copy()
                if "POSTGRES_PASSWORD" in os.environ:
                    env["PGPASSWORD"] = os.environ["POSTGRES_PASSWORD"]
                cmd = [
                    psql_path,
                    "-h", args.host,
                    "-p", str(args.port),
                    "-U", args.user,
                    "-d", args.db,
                    "-f", str(backup_path)
                ]
                print(f"[*] Executing psql on {args.host}:{args.port}...")
                subprocess.run(cmd, env=env, check=True, stderr=subprocess.PIPE)

        print("[+] Database restored successfully!")

    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.decode() if e.stderr else str(e)
        print(f"[x] Restore failed: {err_msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[x] Unexpected restore error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
