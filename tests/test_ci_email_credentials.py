"""Offline regression for the real SES job's credential gate; no email is sent."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_workflow(name: str) -> dict:
    return yaml.load((ROOT / ".github" / "workflows" / name).read_text("utf-8"), yaml.BaseLoader)


def bash_executable() -> str:
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        if git_bash.is_file():
            return str(git_bash)
    bash = shutil.which("bash")
    assert bash is not None, "Bash is required to verify the CI credential gate"
    return bash


@pytest.mark.parametrize("required", [False, True], ids=["ordinary-ci", "explicit-required"])
@pytest.mark.parametrize(
    ("access_key", "secret_key"),
    [
        ("", ""),
        ("synthetic-access", ""),
        ("", "synthetic-secret"),
        ("synthetic-access", "synthetic-secret"),
    ],
    ids=["no-keys", "no-secret-key", "no-access-key", "both-keys"],
)
def test_credential_gate(required: bool, access_key: str, secret_key: str, tmp_path: Path):
    gate = load_workflow("ci.yml")["jobs"]["email-e2e-credentials"]["steps"][0]
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    # Do not inherit real AWS credentials or other developer secrets into the shell.
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT") if name in os.environ}
    env.update(
        AWS_ACCESS_KEY_ID=access_key,
        AWS_SECRET_ACCESS_KEY=secret_key,
        EMAIL_TESTS_REQUIRED=str(required).lower(),
        GITHUB_OUTPUT=output.as_posix(),
        GITHUB_STEP_SUMMARY=summary.as_posix(),
    )
    result = subprocess.run(
        [bash_executable(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", gate["run"]],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    available = bool(access_key and secret_key)
    assert result.returncode == (1 if required and not available else 0), result.stderr
    assert output.read_text("utf-8").strip() == f"available={str(available).lower()}"
    if not available and not required:
        assert "::notice::Skipping real SES" in result.stdout
        assert "Real email delivery was not tested." in summary.read_text("utf-8")
    else:
        assert not summary.exists()
    if required and not available:
        assert "::error::Required CI AWS credentials are missing" in result.stdout
    for key in (access_key, secret_key):
        if key:
            assert key not in result.stdout + result.stderr + output.read_text("utf-8")


def test_real_ses_job_requires_gate_and_release_stays_mandatory():
    jobs = load_workflow("ci.yml")["jobs"]
    gate = jobs["email-e2e-credentials"]
    assert gate["if"] == (
        "github.event_name != 'pull_request' && github.ref == 'refs/heads/main' && "
        "(github.event_name == 'push' || github.event_name == 'workflow_dispatch' || inputs.run_email_tests)"
    )
    assert len(gate["steps"]) == 1  # No checkout or untrusted code with AWS credentials.
    assert gate["outputs"]["available"] == "${{ steps.credentials.outputs.available }}"
    assert (
        gate["steps"][0]["env"]["EMAIL_TESTS_REQUIRED"] == "${{ inputs.run_email_tests || false }}"
    )
    email = jobs["email-e2e"]
    assert email["needs"] == "email-e2e-credentials"
    assert email["if"] == "needs.email-e2e-credentials.outputs.available == 'true'"
    assert "continue-on-error" not in email
    for step in email["steps"]:
        assert "continue-on-error" not in step
    commands = "\n".join(step.get("run", "") for step in email["steps"])
    assert "git merge-base --is-ancestor HEAD origin/main" in commands
    assert "python -m tests.helpers.testmail_cli preflight" in commands
    assert (
        "pytest tests/integration/test_testmail_email_pg.py -m email_external --run-email-tests"
        in commands
    )
    assert "python scripts/run_e2e_suite.py --suite email" in commands
    release = load_workflow("release.yml")["jobs"]
    assert release["verify-quality"]["with"]["run_email_tests"] == "true"
    assert "verify-quality" in release["build-artifacts"]["needs"]
