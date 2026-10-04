"""Render a proxy snippet from validated public DSN; no private settings."""

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings

parser = argparse.ArgumentParser()
parser.add_argument("--dsn", default="", help="Public frontend DSN, not auth token")
parser.add_argument(
    "--enforce", action="store_true", help="Compatibility flag; enforcement is the default"
)
parser.add_argument(
    "--report-only", action="store_true", help="Explicit diagnostic staging profile"
)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
settings = Settings(_env_file=None, SENTRY_FRONTEND_DSN=args.dsn)
origin = f" https://{urlsplit(settings.SENTRY_FRONTEND_DSN).hostname}" if args.dsn else ""
header = "Content-Security-Policy-Report-Only" if args.report_only else "Content-Security-Policy"
policy = f"default-src 'self'; script-src 'self'; style-src 'self'; worker-src 'self'; img-src 'self' data:; connect-src 'self'{origin}; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
args.out.write_text(f'add_header {header} "{policy}" always;\n', encoding="utf-8")
