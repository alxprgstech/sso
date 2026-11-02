"""Compatibility CLI for the shared deployment result parser.

The active workflow uses deploy/ec2/deploy.py directly. Keep this entry point
for existing tooling without maintaining a second protocol implementation.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "shared_deployment_protocol", Path(__file__).resolve().parents[1] / "deploy/ec2/deploy.py"
)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
ProtocolError = _shared.DeployError
DeployResult = _shared.Result
PROTOCOL_PREFIX = "ssoctl-result:"


def parse_server_output(raw: str, expected_sha: str, expected_sequence: int) -> DeployResult:
    return _shared.parse_result(raw, expected_sha, expected_sequence, "inbox")


def write_github_output(path: Path, result: DeployResult) -> None:
    _shared.outputs(
        {
            "result": result.result,
            "installed": str(result.installed).lower(),
            "installed_sha": result.sha,
            "reason": result.reason,
            "legacy": str(result.legacy).lower(),
        },
        str(path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = parse_server_output(sys.stdin.read(), args.sha, args.sequence)
    except ProtocolError as error:
        print(f"Server deployment protocol failed: {error}", file=sys.stderr)
        return 1
    write_github_output(args.github_output, result)
    print(f"Server deployment result: {result.result} ({result.reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
