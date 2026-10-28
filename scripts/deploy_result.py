"""Strict machine protocol for the ssoctl deployment result.

``upload.sh`` pipes the captured server stdout here instead of parsing human
text. A new operator prints exactly one ``ssoctl-result:`` JSON line. An old
operator has no protocol: its success path always performed a real installation,
so the result is explicitly marked ``deployed_legacy`` and the workflow warns
that the server-side no-op guard is not active. Any malformed protocol line is a
hard failure and is never reported as a successful installation.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROTOCOL_PREFIX = "ssoctl-result:"
PROTOCOL_VERSION = 1
SHA_LENGTH = 40
PROTOCOL_KEYS = {"version", "result", "sha", "sequence"}
RESULT_KEYS = {"deployed", "already_deployed"}
LEGACY_REASON = "legacy operator: server-side idempotency guard is not active"


class ProtocolError(Exception):
    pass


@dataclass(frozen=True)
class DeployResult:
    result: str
    installed: bool
    sha: str
    reason: str
    legacy: bool = False


def _valid_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_sequence(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _protocol_payload(raw: str) -> dict | None:
    lines = [line for line in raw.splitlines() if line.startswith(PROTOCOL_PREFIX)]
    if len(lines) > 1:
        raise ProtocolError("server returned multiple deployment protocol lines")
    if not lines:
        return None
    try:
        value = json.loads(lines[0][len(PROTOCOL_PREFIX) :])
    except (ValueError, TypeError):
        raise ProtocolError("server deployment protocol is not valid JSON") from None
    if not isinstance(value, dict) or set(value) != PROTOCOL_KEYS:
        raise ProtocolError("server deployment protocol has an unexpected shape")
    return value


def _validate_payload(value: dict, expected_sha: str, expected_sequence: int) -> None:
    if value["version"] != PROTOCOL_VERSION or isinstance(value["version"], bool):
        raise ProtocolError("server deployment protocol version is unsupported")
    if not isinstance(value["result"], str) or value["result"] not in RESULT_KEYS:
        raise ProtocolError("server deployment result is unknown")
    if not _valid_sha(value["sha"]) or value["sha"] != expected_sha:
        raise ProtocolError("server deployment SHA does not match the target")
    if not _valid_sequence(value["sequence"]) or value["sequence"] != expected_sequence:
        raise ProtocolError("server deployment sequence does not match the run")


def _decision(value: dict) -> DeployResult:
    if value["result"] == "already_deployed":
        return DeployResult(
            "already_deployed",
            False,
            value["sha"],
            "server confirmed the same revision is installed",
        )
    return DeployResult("deployed", True, value["sha"], "new installation completed")


def parse_server_output(raw: str, expected_sha: str, expected_sequence: int) -> DeployResult:
    value = _protocol_payload(raw)
    if value is None:
        # The pre-idempotency operator never had a no-op path: exit 0 means the
        # full verified installation completed. Mark it explicitly, never silently.
        return DeployResult("deployed_legacy", True, expected_sha, LEGACY_REASON, legacy=True)
    _validate_payload(value, expected_sha, expected_sequence)
    return _decision(value)


def write_github_output(path: Path, result: DeployResult) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"result={result.result}\n")
        output.write(f"installed={'true' if result.installed else 'false'}\n")
        output.write(f"installed_sha={result.sha}\n")
        output.write(f"reason={result.reason}\n")
        output.write(f"legacy={'true' if result.legacy else 'false'}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = sys.stdin.read()
    try:
        result = parse_server_output(raw, args.sha, args.sequence)
    except ProtocolError as error:
        print(f"Server deployment protocol failed: {error}", file=sys.stderr)
        return 1
    write_github_output(args.github_output, result)
    print(f"Server deployment result: {result.result} ({result.reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
