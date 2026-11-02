#!/usr/bin/env python3
"""Thin, hand-maintained entry point for the SSO EC2 operator.

The operator implementation is the shared ``alxprgstech/ctl`` delivery, vendored
as ``deploy/ec2/operator/ssoctl.py`` and pinned by
``deploy/ec2/operator-provenance.json``. This file only verifies that pin and
executes the vendored artifact in its own namespace; it never contains operator
logic.

The host installs the vendored artifact itself
(``/opt/alxprgs-sso/tools/ssoctl.py``, refreshed by ``sudo ssoctl self-update``
or by ``bootstrap.sh``). The installed operator is therefore one self-contained
root-owned file, and the runtime never depends on this checkout, a virtual
environment, Docker or the network.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACT = HERE / "operator" / "ssoctl.py"
PROVENANCE = HERE / "operator-provenance.json"


def _entry_point_failure(message: str) -> SystemExit:
    print(f"ssoctl entry point: {message}", file=sys.stderr)
    return SystemExit(1)


def _vendored_artifact() -> bytes:
    try:
        record = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise _entry_point_failure("operator provenance is missing or unreadable") from None
    if (
        not isinstance(record, dict)
        or record.get("format") != 1
        or record.get("target") != "sso"
        or record.get("tool") != "ssoctl.py"
    ):
        raise _entry_point_failure("operator provenance is not for this entry point")
    try:
        data = ARTIFACT.read_bytes()
    except OSError:
        raise _entry_point_failure("vendored operator artifact is missing") from None
    if hashlib.sha256(data).hexdigest() != record.get("sha256"):
        raise _entry_point_failure(
            "vendored operator artifact does not match the pinned digest; re-pin ctl"
        )
    return data


# Project tests, helper scripts and the container check import this module; the
# installed command executes it. Both modes load the same verified bytes here.
# `dont_inherit=True` keeps this file's `from __future__ import annotations` out of
# the artifact: the operator's own annotations must stay real objects.
# The executed bytes are the pinned delivery, verified above; nothing else is
# imported from the working tree.
exec(  # noqa: S102 - executing the digest-verified pinned delivery
    compile(_vendored_artifact(), str(ARTIFACT), "exec", dont_inherit=True), globals()
)
