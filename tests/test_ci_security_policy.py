"""Release/security gates cannot silently lose mandatory execution or isolation."""

import ast
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def commands(job):
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def test_backend_lifecycle_dependencies_and_pg_checks_remain_mandatory():
    ci = yaml.load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"), Loader=yaml.BaseLoader)
    backend = commands(ci["jobs"]["backend-lint-and-test"])
    assert (
        backend.index("npm ci") < backend.index("npm run build") < backend.index("pytest -v tests/")
    )
    assert '-m "not postgres"' in commands(ci["jobs"]["windows-safety"])
    assert '-m "not postgres"' not in backend


def test_release_context_contains_every_copied_frontend_configuration():
    source = (ROOT / "frontend/Dockerfile.release").read_text("utf-8")
    allowed = (ROOT / "frontend/Dockerfile.release.dockerignore").read_text("utf-8").splitlines()
    copies = re.findall(r"^COPY ([\w.-]+\.conf) ", source, re.M)
    assert "nginx-main.conf" in copies
    assert all("!" + name in allowed for name in copies)


def workflow_jobs():
    return yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text("utf-8"), Loader=yaml.BaseLoader
    )["jobs"]


@pytest.mark.parametrize(
    "name",
    [
        "windows-safety",
        "telemetry-container-check",
        "backend-lint-and-test",
        "playwright-e2e",
        "sdk-build-and-test",
    ],
)
def test_required_jobs_and_steps_have_no_bypass(name):
    job = workflow_jobs()[name]
    assert "if" not in job and "continue-on-error" not in job
    assert all("continue-on-error" not in step for step in job["steps"])


def test_windows_jobs_run_both_shells_and_existing_regressions():
    windows = commands(workflow_jobs()["windows-safety"])
    assert "powershell.exe -ErrorAction Stop" in windows and "pwsh.exe -ErrorAction Stop" in windows
    for path in re.findall(r"tests/[\w/]+\.py", windows):
        assert (ROOT / path).is_file(), f"Missing required Windows regression: {path}"


def test_container_job_keeps_actual_runtime_and_strict_image_audit():
    container = commands(workflow_jobs()["telemetry-container-check"])
    assert "python scripts/check_container_runtime.py" in container
    assert "--exit-code 1" in container and "--severity HIGH,CRITICAL" in container
    assert "--ignore-unfixed" not in container


def test_browser_job_keeps_protocol_and_factor_regressions():
    browser = commands(workflow_jobs()["playwright-e2e"])
    assert "e2e/protocol_lifecycle.spec.ts" in browser and "e2e/totp.spec.ts" in browser


def test_every_ci_service_uses_immutable_digest():
    for job in workflow_jobs().values():
        for service in job.get("services", {}).values():
            assert re.search(r"@sha256:[0-9a-f]{64}$", service["image"])


@pytest.mark.parametrize("name", ["backend", "migrate", "frontend"])
def test_runtime_compose_enforces_service_boundaries(name):
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))["services"]
    service = services[name]
    assert service["read_only"] and service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["mem_limit"] and service["cpus"] > 0 and service["pids_limit"] > 0
    assert not service.get("ports") or name == "frontend"


def test_compose_database_is_private_and_roles_are_separate():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))["services"]
    db = services["db"]
    assert not db.get("ports") and db["mem_limit"] and db["pids_limit"] > 0
    assert "sso_runtime:" in str(services["backend"]["environment"]["DATABASE_URL"])
    assert "sso_migrator:" in str(services["migrate"]["environment"]["DATABASE_URL"])


@pytest.mark.parametrize(
    "path", ["frontend/Dockerfile", "frontend/Dockerfile.release", "backend/Dockerfile"]
)
def test_container_images_pin_digests_and_nonroot_users(path):
    source = (ROOT / path).read_text("utf-8")
    for image in re.findall(r"^FROM\s+(\S+)", source, re.M):
        assert re.search(r"@sha256:[0-9a-f]{64}$", image)
    assert re.search(r"^USER\s+(?!root\b|0\b)\S+", source, re.M)


def test_container_role_proof_is_executable_python():
    tree = ast.parse((ROOT / "scripts/check_container_runtime.py").read_text("utf-8"))
    proof = next(
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "proof" for target in node.targets)
    )
    parsed = ast.parse(proof)
    embedded = next(
        node.args[0].value
        for node in ast.walk(parsed)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "exec"
    )
    compile(embedded, "container-role-check", "exec")
    assert "require_runtime_database_role(db)" in embedded
