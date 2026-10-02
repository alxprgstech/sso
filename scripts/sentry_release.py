"""Trusted release uploader. Builds nothing; validates before accessing credentials."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release_bundle import verify
from scripts.sentry_artifacts import verify_private_maps


def api(url: str, method: str, payload: dict | None, token: str) -> dict:
    request = Request(
        url,
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--private-maps", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--cli", default="sentry-cli")
    parser.add_argument("--repository", default="")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[a-f0-9]{40}", args.expected_sha):
            raise ValueError("Invalid revision")
        release_manifest = verify(args.release_dir, args.expected_sha)
        manifest = verify_private_maps(args.private_maps, args.release_dir, args.expected_sha)
        if not args.upload:
            print("Sentry artifacts validated offline; network upload disabled")
            return 0
        if (
            release_manifest.get("source_tree_dirty")
            or release_manifest.get("tag") != f"v{release_manifest['version']}"
        ):
            raise ValueError("Upload requires a clean tagged release artifact")
        token = os.environ.get("SENTRY_AUTH_TOKEN", "")
        org = os.environ.get("SENTRY_ORG", "")
        backend = os.environ.get("SENTRY_PROJECT_BACKEND", "")
        frontend = os.environ.get("SENTRY_PROJECT_FRONTEND", "")
        base = os.environ.get("SENTRY_URL", "https://de.sentry.io/").rstrip("/")
        if (
            not token
            or base != "https://de.sentry.io"
            or not all(re.fullmatch(r"[a-z0-9_-]+", name) for name in (org, backend, frontend))
        ):
            raise ValueError("Upload credentials/DE project configuration missing or invalid")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
            raise ValueError("Verified GitHub repository identity required")
        identity = manifest["identity"]
        release = identity["release"]
        collection = f"{base}/api/0/organizations/{org}/releases/"
        resource = collection + quote(release, safe="") + "/"
        payload = {
            "version": release,
            "projects": [backend, frontend],
            "ref": args.expected_sha,
            "url": f"https://github.com/{args.repository}/commit/{args.expected_sha}",
            "commits": [{"id": args.expected_sha}],
            "dateReleased": None,
        }
        try:
            existing = api(resource, "GET", None, token)
            if existing.get("version") != release or existing.get("ref") != args.expected_sha:
                raise ValueError("Existing release identity mismatch")
        except HTTPError as error:
            if error.code != 404:
                raise
            api(collection, "POST", payload, token)
        # Retry reuses the same immutable release. No author emails/messages are read.
        cli_env = {**os.environ, "SENTRY_URL": base}
        result = subprocess.run(
            [
                args.cli,
                "--org",
                org,
                "--project",
                frontend,
                "sourcemaps",
                "upload",
                "--release",
                release,
                "--validate",
                "--strict",
                "--wait-for",
                "60",
                "--no-rewrite",
                str(args.private_maps / "assets"),
            ],
            env=cli_env,
            capture_output=True,
            check=False,
            timeout=120,
        )
        if result.returncode:
            raise ValueError("Source map upload failed (diagnostics withheld)")
        # CLI performs server processing/validation; also verify release project association.
        state = api(resource, "GET", None, token)
        associated = {project["slug"] for project in state.get("projects", [])}
        if (
            not {backend, frontend} <= associated
            or state.get("version") != release
            or state.get("ref") != args.expected_sha
            or state.get("url") != payload["url"]
            or (state.get("lastCommit") or {}).get("id") != args.expected_sha
        ):
            raise ValueError("Release project/commit association mismatch")
        from datetime import datetime, timezone

        if state.get("dateReleased") is None:
            api(resource, "PUT", {"dateReleased": datetime.now(timezone.utc).isoformat()}, token)
        print("Sentry release and private source maps prepared; no deployment recorded")
        return 0
    except Exception as error:
        # No HTTP response body, SDK exception value, token or CLI output in CI logs.
        print(f"Sentry release preparation failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
