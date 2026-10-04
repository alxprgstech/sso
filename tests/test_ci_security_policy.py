"""Release/security gates cannot silently lose mandatory execution or isolation."""

import ast
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def commands(job):
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def test_required_security_windows_and_browser_jobs_have_no_bypass():
    ci = yaml.load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"), Loader=yaml.BaseLoader)
    for name in (
        "windows-safety",
        "telemetry-container-check",
        "backend-lint-and-test",
        "playwright-e2e",
        "sdk-build-and-test",
    ):
        job = ci["jobs"][name]
        assert "if" not in job and "continue-on-error" not in job
        assert all("continue-on-error" not in step for step in job["steps"])
    windows = commands(ci["jobs"]["windows-safety"])
    assert "powershell.exe -ErrorAction Stop" in windows and "pwsh.exe -ErrorAction Stop" in windows
    for path in re.findall(r"tests/[\w/]+\.py", windows):
        assert (ROOT / path).is_file(), f"Missing required Windows regression: {path}"
    container = commands(ci["jobs"]["telemetry-container-check"])
    assert "python scripts/check_container_runtime.py" in container
    assert "--exit-code 1" in container and "--severity HIGH,CRITICAL" in container
    assert "--ignore-unfixed" not in container
    browser = commands(ci["jobs"]["playwright-e2e"])
    assert "e2e/protocol_lifecycle.spec.ts" in browser and "e2e/totp.spec.ts" in browser
    for job in ci["jobs"].values():
        for service in job.get("services", {}).values():
            assert re.search(r"@sha256:[0-9a-f]{64}$", service["image"])


def test_runtime_compose_and_both_frontend_images_enforce_boundaries():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))["services"]
    for name in ("backend", "migrate", "frontend"):
        service = services[name]
        assert service["read_only"] and service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["mem_limit"] and service["cpus"] > 0 and service["pids_limit"] > 0
        assert not service.get("ports") or name == "frontend"
    db = services["db"]
    assert not db.get("ports") and db["mem_limit"] and db["pids_limit"] > 0
    for path in ("frontend/Dockerfile", "frontend/Dockerfile.release", "backend/Dockerfile"):
        source = (ROOT / path).read_text("utf-8")
        for image in re.findall(r"^FROM\s+(\S+)", source, re.M):
            assert re.search(r"@sha256:[0-9a-f]{64}$", image)
        assert re.search(r"^USER\s+(?!root\b|0\b)\S+", source, re.M)
    assert "sso_runtime:" in str(services["backend"]["environment"]["DATABASE_URL"])
    assert "sso_migrator:" in str(services["migrate"]["environment"]["DATABASE_URL"])


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
