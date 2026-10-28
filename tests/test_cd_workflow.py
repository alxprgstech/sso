"""CD workflow policy contracts; local YAML checks do not execute GitHub scheduler."""

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.load((ROOT / ".github/workflows/cd.yml").read_text(), Loader=yaml.BaseLoader)
JOBS = WORKFLOW["jobs"]


def test_cd_keeps_automatic_gate_and_concurrency():
    assert WORKFLOW["on"] == {
        "workflow_dispatch": {},
        "workflow_run": {"workflows": ["CI"], "types": ["completed"], "branches": ["main"]},
    }
    gate = JOBS["preflight"]["if"]
    for condition in (
        "conclusion == 'success'",
        "event == 'push'",
        "head_branch == 'main'",
        "head_repository.full_name == github.repository",
    ):
        assert condition in gate
    assert WORKFLOW["concurrency"]["cancel-in-progress"] == "false"


def test_cd_preflight_checks_out_exact_sha_and_identity():
    steps = JOBS["preflight"]["steps"]
    assert steps[0]["with"]["ref"] == "${{ env.DEPLOY_SHA }}"
    assert WORKFLOW["env"]["DEPLOY_SHA"] == (
        "${{ github.event_name == 'workflow_dispatch' && github.sha || github.event.workflow_run.head_sha }}"
    )
    decide = next(step for step in steps if step.get("id") == "decide")
    assert "check_deployed_revision.py" in decide["run"]
    assert '"$GITHUB_OUTPUT"' in decide["run"]


def test_cd_verify_and_install_keep_transport_checks():
    verify = JOBS["verify"]
    transport = next(
        step for step in verify["steps"] if step["name"] == "Verify the transport to be installed"
    )
    assert "scripts.check_ec2_runtime" in transport["run"]
    assert verify["if"] == "needs.build.outputs.artifact_name != ''"
    install = JOBS["deploy"]["steps"][-1]["run"]
    assert "latest" in install and "deploy/ec2/upload.sh" in install


def test_cd_pins_actions_and_has_no_continue_on_error():
    all_steps = [step for job in JOBS.values() for step in job["steps"]]
    assert all("continue-on-error" not in step for step in all_steps)
    for step in all_steps:
        if "uses" in step:
            assert re.search(r"@[a-f0-9]{40}$", step["uses"])


@pytest.mark.parametrize(
    "case",
    [
        ("workflow_dispatch", "refs/heads/main", "failure", "push", "main", True, True),
        ("workflow_dispatch", "refs/heads/new/test", "success", "push", "main", True, False),
        ("workflow_run", "refs/heads/main", "success", "push", "main", True, True),
        ("workflow_run", "refs/heads/main", "failure", "push", "main", True, False),
        ("workflow_run", "refs/heads/main", "cancelled", "push", "main", True, False),
        ("workflow_run", "refs/heads/main", "success", "pull_request", "main", True, False),
        ("workflow_run", "refs/heads/main", "success", "push", "other", True, False),
        ("workflow_run", "refs/heads/main", "success", "push", "main", False, False),
        ("push", "refs/heads/main", "success", "push", "main", True, False),
    ],
)
def test_cd_event_gate_matrix(case):
    from types import SimpleNamespace as NS

    event, ref, conclusion, origin, branch, same_repo, allowed = case
    expression = JOBS["preflight"]["if"].replace("&&", "and").replace("||", "or")
    github = NS(
        event_name=event,
        ref=ref,
        repository="owner/sso",
        event=NS(
            workflow_run=NS(
                conclusion=conclusion,
                event=origin,
                head_branch=branch,
                head_repository=NS(full_name="owner/sso" if same_repo else "fork/sso"),
            )
        ),
    )
    assert bool(eval(expression, {"__builtins__": {}}, {"github": github})) == allowed


def test_transport_pipeline_pins_classic_docker_image_store():
    pinning = "Pin classic Docker image store to match the EC2 server"
    for path, job, anchor in (
        (".github/workflows/cd.yml", "build", "Build private transport bundle"),
        (".github/workflows/cd.yml", "verify", "Verify the transport to be installed"),
        (
            ".github/workflows/ci.yml",
            "verify-cd-template",
            "Verify transport and production database lifecycle",
        ),
    ):
        steps = yaml.safe_load((ROOT / path).read_text())["jobs"][job]["steps"]
        names = [step["name"] for step in steps]
        assert names.index(pinning) < names.index(anchor)
    # Docker 29 fresh installs default to the containerd image store; new
    # servers must land on the classic store the runners are pinned to.
    bootstrap = (ROOT / "deploy/ec2/bootstrap.sh").read_text()
    assert '["containerd-snapshotter"] = False' in bootstrap
    assert bootstrap.index("containerd-snapshotter") < bootstrap.index("enable --now docker")


def test_cd_retry_uses_same_immutable_bundle():
    assert set(JOBS) == {"preflight", "build", "verify", "deploy", "public-check", "report"}
    assert JOBS["build"]["needs"] == "preflight"
    assert JOBS["build"]["if"] == "needs.preflight.outputs.decision == 'deploy'"
    assert JOBS["verify"]["needs"] == "build"
    assert JOBS["deploy"]["needs"] == ["build", "verify"]
    assert JOBS["deploy"]["if"] == (
        "needs.build.outputs.artifact_name != '' && needs.verify.result == 'success'"
    )
    upload = next(step for step in JOBS["build"]["steps"] if step.get("id") == "bundle")
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == "7"
    assert "github.run_attempt" in upload["with"]["name"]
    assert "overwrite" not in upload["with"]
    assert JOBS["build"]["outputs"]["artifact_id"] == "${{ steps.bundle.outputs.artifact-id }}"
    assert JOBS["build"]["outputs"]["artifact_name"] == upload["with"]["name"]


def test_cd_deploy_downloads_the_verified_bundle_without_rebuilding():
    for name in ("verify", "deploy"):
        steps = JOBS[name]["steps"]
        download = next(step for step in steps if "download-artifact@" in step.get("uses", ""))
        assert download["with"]["name"] == "${{ needs.build.outputs.artifact_name }}"
        assert "run-id" not in download["with"]  # Only artifacts of this workflow run.
        assert "pattern" not in download["with"]
        assert steps[0]["with"]["ref"] == "${{ env.DEPLOY_SHA }}"
        assert not any("build_ec2_bundle.py" in step.get("run", "") for step in steps)
    install = JOBS["deploy"]["steps"][-1]
    assert install["env"]["DEPLOY_SEQUENCE"] == "${{ github.run_number }}"
    assert 'latest" != "$DEPLOY_SHA' in install["run"]


def test_cd_confines_production_environment_to_deploy():
    assert JOBS["deploy"]["environment"] == "production"
    assert all(
        "environment" not in JOBS[name]
        for name in ("preflight", "build", "verify", "public-check", "report")
    )


def test_early_identity_noop_skips_build_verify_and_install():
    assert JOBS["build"]["if"] == "needs.preflight.outputs.decision == 'deploy'"
    assert JOBS["verify"]["if"] == "needs.build.outputs.artifact_name != ''"
    public_if = JOBS["public-check"]["if"]
    assert "needs.deploy.outputs.result == 'already_deployed'" in public_if
    assert "needs.preflight.outputs.decision == 'already_deployed'" in public_if
    preflight_step = next(step for step in JOBS["preflight"]["steps"] if step.get("id") == "decide")
    assert "decision=superseded" in preflight_step["run"]
    assert preflight_step["run"].index("latest") < preflight_step["run"].index(
        "check_deployed_revision.py"
    )


def test_deploy_consumes_server_protocol_and_never_claims_installed_from_upload_exit():
    deploy = JOBS["deploy"]
    install = deploy["steps"][-1]
    assert install["id"] == "install"
    assert deploy["outputs"]["result"] == "${{ steps.install.outputs.result }}"
    assert deploy["outputs"]["installed"] == "${{ steps.install.outputs.installed }}"
    assert deploy["outputs"]["installed_sha"] == "${{ steps.install.outputs.installed_sha }}"
    assert install["run"].index("exit 0") < install["run"].index("bash deploy/ec2/upload.sh")
    assert "installed=true" not in install["run"]  # upload.sh writes the real outcome.
    assert "deploy_result.py" in (ROOT / "deploy/ec2/upload.sh").read_text()
    assert "result=superseded" in install["run"]


def test_public_check_runs_after_install_or_noop_and_can_retry():
    check = JOBS["public-check"]
    assert check["needs"] == ["preflight", "deploy"]
    assert check["if"].startswith("always()")
    assert "needs.deploy.outputs.result == 'deployed'" in check["if"]
    assert "needs.deploy.outputs.result == 'already_deployed'" in check["if"]
    assert "environment" not in check
    assert check["steps"][0]["with"]["ref"] == "${{ env.DEPLOY_SHA }}"
    assert check["steps"][-1]["run"] == "python3 scripts/check_public_readiness.py"
    assert "continue-on-error" not in check
    assert not any("upload.sh" in step.get("run", "") for step in check["steps"])


def test_report_is_always_run_and_records_safe_result_fields():
    report = JOBS["report"]
    assert report["if"] == "always()"
    assert set(report["needs"]) == {
        "preflight",
        "build",
        "verify",
        "deploy",
        "public-check",
    }
    summary = report["steps"][-1]["run"]
    for fragment in ("$DEPLOY_SHA", "$INSTALLED_SHA", "$RESULT", "$REASON", "deployed_legacy"):
        assert fragment in summary
    assert "RESULT='error'" in summary and "exit 1" in summary


def test_production_secrets_are_confined_to_deploy_job():
    deploy_step = JOBS["deploy"]["steps"][-1]
    assert deploy_step["env"]["SSH_PRIVATE_KEY"] == "${{ secrets.SSH_PRIVATE_KEY }}"
    assert deploy_step["env"]["SSH_KNOWN_HOSTS"] == "${{ secrets.SSH_KNOWN_HOSTS }}"
    for name in ("preflight", "build", "verify", "public-check", "report"):
        assert "secrets." not in json.dumps(JOBS[name])
