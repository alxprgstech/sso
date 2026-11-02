"""Integration contract for the pinned shared operator delivery in SSO.

The self-update trust chain is implemented once in ``alxprgstech/ctl`` and tested
there. This module proves that SSO consumes exactly that pinned delivery: the
vendored bytes match the pin, the entry point is thin and fails closed, the
command surface and the ``ssoctl-result`` protocol are unchanged, and bootstrap
installs the artifact rather than the repository entry point.

HTTP and subprocess outputs are synthetic; no GitHub credential, production
server or installed operator is touched by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/ec2"
ENTRY = DEPLOY / "ssoctl.py"
ARTIFACT = DEPLOY / "operator/ssoctl.py"
PROVENANCE = DEPLOY / "operator-provenance.json"
REQUIRED_COMMANDS = (
    "configure", "backup", "renew", "test-alert", "admin", "status", "maintenance",
    "resume", "mfa-status", "enable-mfa", "recover-admin", "admin-status", "deploy",
    "verify-backup", "self-update",
)

spec = importlib.util.spec_from_file_location("sso_ec2_operator", ENTRY)
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)

SOURCE = ARTIFACT.read_bytes()
PIN = json.loads(PROVENANCE.read_text(encoding="utf-8"))
COMMIT = hashlib.sha1(b"self-update main", usedforsecurity=False).hexdigest()


def embedded_provenance(data: bytes = SOURCE) -> dict:
    match = re.search(rb"^CTL_PROVENANCE = (\{.*\})$", data, re.MULTILINE)
    assert match is not None, "vendored operator has no provenance block"
    return json.loads(match.group(1))


def run_entry(*arguments: str, entry: Path = ENTRY, cwd: Path | None = None):
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(entry), *arguments],
        cwd=cwd or ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )


def subparsers():
    parser = ctl.build_parser()
    return next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))


def test_pin_is_a_full_committed_delivery_identity():
    assert PIN["format"] == 1
    assert PIN["target"] == "sso"
    assert PIN["tool"] == "ssoctl.py"
    assert PIN["ctl_repository"] == "alxprgstech/ctl"
    assert PIN["artifact_path"] == "dist/ssoctl"
    assert re.fullmatch(r"[a-f0-9]{40}", PIN["ctl_delivery_commit"])
    assert re.fullmatch(r"[a-f0-9]{40}", PIN["ctl_source_commit"])
    assert re.fullmatch(r"[a-f0-9]{64}", PIN["sha256"])
    assert re.fullmatch(r"[a-f0-9]{64}", PIN["content_sha256"])
    assert PIN["ctl_version"] == "1.0.0"


def test_vendored_artifact_matches_the_pinned_digest():
    assert hashlib.sha256(SOURCE).hexdigest() == PIN["sha256"]
    assert SOURCE.startswith(b"#!/usr/bin/env python3\n")
    assert len(SOURCE) > 50_000, "the vendored operator must be the built delivery"


def test_embedded_provenance_agrees_with_the_pin():
    document = embedded_provenance()
    assert document["format"] == 1
    assert document["target"] == "sso"
    assert document["project"] == "sso"
    assert document["delivery"] == "dist/ssoctl"
    assert document["adapter"] == "ctl.adapters.sso"
    assert document["version"] == PIN["ctl_version"]
    assert document["source_commit"] == PIN["ctl_source_commit"]
    assert document["content_sha256"] == PIN["content_sha256"]


def test_entry_point_is_thin_and_carries_no_operator_logic():
    text = ENTRY.read_text(encoding="utf-8")
    assert "operator-provenance.json" in text
    assert len(text) < 6000
    for forbidden in ("def deploy(", "def self_update(", "def notify(", "def locked("):
        assert forbidden not in text
    assert "from ctl import" in SOURCE.decode("utf-8"), "the operator must be the shared delivery"


def test_entry_point_fails_closed_on_a_digest_mismatch(tmp_path):
    copy = tmp_path / "deploy"
    (copy / "operator").mkdir(parents=True)
    shutil.copyfile(ENTRY, copy / "ssoctl.py")
    shutil.copyfile(PROVENANCE, copy / "operator-provenance.json")
    (copy / "operator" / "ssoctl.py").write_bytes(SOURCE + b"\n# tampered\n")
    result = run_entry("--version", entry=copy / "ssoctl.py", cwd=tmp_path)
    assert result.returncode == 1
    assert "does not match the pinned digest" in result.stderr


def test_entry_point_rejects_a_foreign_provenance(tmp_path):
    copy = tmp_path / "deploy"
    (copy / "operator").mkdir(parents=True)
    shutil.copyfile(ENTRY, copy / "ssoctl.py")
    shutil.copyfile(ARTIFACT, copy / "operator" / "ssoctl.py")
    record = dict(PIN, target="mp")
    (copy / "operator-provenance.json").write_text(json.dumps(record), encoding="utf-8")
    result = run_entry("--version", entry=copy / "ssoctl.py", cwd=tmp_path)
    assert result.returncode == 1
    assert "not for this entry point" in result.stderr


def test_entry_point_refuses_a_missing_artifact(tmp_path):
    copy = tmp_path / "deploy"
    copy.mkdir()
    shutil.copyfile(ENTRY, copy / "ssoctl.py")
    shutil.copyfile(PROVENANCE, copy / "operator-provenance.json")
    result = run_entry("--version", entry=copy / "ssoctl.py", cwd=tmp_path)
    assert result.returncode == 1
    assert "artifact is missing" in result.stderr


def test_real_entrypoint_help_and_version_work_without_root(tmp_path):
    help_result = run_entry("--help", cwd=tmp_path)
    assert help_result.returncode == 0, help_result.stderr
    assert "recover-admin" in help_result.stdout
    assert "self-update" in help_result.stdout
    assert help_result.stderr == ""
    version_result = run_entry("--version", cwd=tmp_path)
    assert version_result.returncode == 0
    assert "target=sso" in version_result.stdout
    assert f"source_commit={PIN['ctl_source_commit']}" in version_result.stdout
    assert list(tmp_path.iterdir()) == []


def test_recover_admin_help_keeps_required_interface():
    result = run_entry("recover-admin", "--help")
    assert result.returncode == 0, result.stderr
    for expected in (
        "--username", "--reason", "--confirm",
        "lost_factor", "compromised", "owner_request",
    ):
        assert expected in result.stdout


def test_parser_registers_each_command_once():
    sub = subparsers()
    assert set(REQUIRED_COMMANDS) == set(sub.choices)
    assert len(list(sub.choices)) == len(set(sub.choices))
    assert ctl.REQUIRED_COMMANDS == REQUIRED_COMMANDS
    assert ctl.REQUIRED_COMMANDS.count("recover-admin") == 1


def test_recover_admin_arguments_and_choices_are_preserved():
    recover = subparsers().choices["recover-admin"]
    required = {action.dest for action in recover._actions if action.required}
    assert required == {"username", "reason", "confirm"}
    reason = next(action for action in recover._actions if action.dest == "reason")
    assert tuple(reason.choices) == ("lost_factor", "compromised", "owner_request")


def test_self_update_parser_has_no_arbitrary_source_or_destination_arguments():
    update = subparsers().choices["self-update"]
    options = {action.dest: action for action in update._actions}
    assert set(options) == {"help", "sha"}
    assert options["sha"].required is False
    assert options["sha"].type is ctl.commit_sha
    assert all(action.option_strings for action in update._actions)


@pytest.mark.parametrize("value", ["abc", "main", "v1.0.0", "A" * 40, "a" * 39, "a" * 41])
def test_real_entrypoint_rejects_invalid_sha_before_sudo(tmp_path, value):
    result = run_entry("self-update", "--sha", value, cwd=tmp_path)
    assert result.returncode == 2
    assert "full 40-character lowercase hexadecimal commit SHA" in result.stderr
    assert "Run with sudo" not in result.stderr


def test_result_protocol_is_unchanged():
    line = ctl.result_protocol("deployed", "b" * 40, 7)
    assert line.startswith("ssoctl-result:")
    payload = json.loads(line.split(":", 1)[1])
    assert payload == {"version": 1, "result": "deployed", "sha": "b" * 40, "sequence": 7}


def test_events_are_unchanged_and_exclude_self_update():
    assert ctl.EVENTS == {"backup", "renew", "deploy", "test"}


def test_fixed_trusted_source_is_the_shared_delivery():
    assert ctl.GITHUB_API == "https://api.github.com"
    assert ctl.GITHUB_REPO == "alxprgstech/ctl"
    assert ctl.GITHUB_BRANCH == "main"
    assert ctl.GITHUB_OPERATOR == "dist/ssoctl"
    assert ctl.GITHUB_MANIFEST == "dist/ctl-manifest.json"
    assert (ctl.ROOT_UID, ctl.ROOT_GID) == (0, 0)
    assert ctl.GITHUB_TOKEN.as_posix().startswith("/etc/alxprgs-sso/")
    assert ctl.MAX_OPERATOR_BYTES >= len(SOURCE)


def test_operator_identity_comes_from_the_delivery_not_the_application():
    assert ctl.CTL_PROVENANCE["source_commit"] == PIN["ctl_source_commit"]
    assert ctl.CTL_PROVENANCE["target"] == "sso"
    assert ctl.TOOL == "ssoctl"
    assert ctl.PROJECT == "sso"


def test_installed_path_matches_the_unchanged_bootstrap_policy():
    bootstrap = (DEPLOY / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'install -m 0755 "$here/operator/ssoctl.py" /opt/alxprgs-sso/tools/ssoctl.py' in bootstrap
    assert '"$here/operator-provenance.json"' in bootstrap
    assert "NOPASSWD: /usr/local/sbin/ssoctl deploy *" in bootstrap
    assert 'exec /usr/bin/python3 /opt/alxprgs-sso/tools/ssoctl.py "$@"' in bootstrap
    assert "self-update" not in bootstrap


def test_status_reports_operator_identity_before_the_first_deployment(
    tmp_path, monkeypatch, capsys
):
    state = tmp_path / "state"
    root = tmp_path / "opt"
    tools = root / "tools"
    state.mkdir()
    tools.mkdir(parents=True)
    operator = tools / "ssoctl.py"
    operator.write_bytes(SOURCE)
    monkeypatch.setattr(ctl, "STATE", state)
    monkeypatch.setattr(ctl, "ROOT", root)
    monkeypatch.setattr(ctl.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(ctl, "locked", lambda: __import__("contextlib").nullcontext())
    monkeypatch.setattr(sys, "argv", ["ssoctl", "status"])
    previous_umask = os.umask(0o022)
    try:
        assert ctl.main() == 0
    finally:
        os.umask(previous_umask)
    output = capsys.readouterr().out
    assert output.splitlines()[0] == "Not deployed"
    assert "operator_tool=ssoctl" in output
    assert f"operator_build_source={PIN['ctl_source_commit']}" in output
    assert "operator_delivery=alxprgstech/ctl:dist/ssoctl" in output
    assert f"operator_file_sha256={PIN['sha256']}" in output


def test_container_check_can_import_the_entry_point():
    # deploy/ec2/check.Dockerfile copies the whole deploy/ec2 directory to
    # /check/ec2, so the entry point finds operator/ssoctl.py beside it.
    dockerfile = (DEPLOY / "check.Dockerfile").read_text(encoding="utf-8")
    assert "COPY deploy/ec2 /check/ec2" in dockerfile
    assert (DEPLOY / "operator" / "ssoctl.py").is_file()
