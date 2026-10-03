"""Export the current minimal journal before backup recovery; no profiles or secrets."""

import argparse
import json
import os
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

try:
    from scripts.privacy_journal import EXPORT_SQL
except ModuleNotFoundError:
    from privacy_journal import EXPORT_SQL


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    url = make_url(os.environ["DATABASE_URL_SYNC"])
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL required")
    with psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname=url.database,
        **dict(url.query),
    ) as connection:
        result = connection.execute(EXPORT_SQL).fetchone()
        if not result:
            raise RuntimeError("Journal unavailable")
        args.output.write_text(json.dumps(result[0]), encoding="utf-8")
    print("Current erasure journal exported (UUID and UTC time only).")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"Journal export failed: {type(error).__name__}") from None
