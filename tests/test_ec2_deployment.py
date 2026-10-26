"""EC2 unit/contract regressions. Mocked commands do not prove AWS operation."""

import hashlib
import importlib.util
import io
import json
import secrets
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sso_ec2", ROOT / "deploy/ec2/ssoctl.py")
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)
COMMIT = hashlib.sha1(b"ec2 regression", usedforsecurity=False).hexdigest()
IMAGE = "sha256:" + hashlib.sha256(b"image").hexdigest()


def bundle(path, *, sha=COMMIT, migrations="unchanged"):
    files = {
        "images.tar": b"image archive",
        "compose.yml": b"services: {}",
        "nginx.conf": b"# site",
        "public/index.html": b"frontend",
        "csp.conf": b"# csp",
    }
    manifest = {
        "sha": sha,
        "backend_image": IMAGE,
        "postgres_image": IMAGE,
        "schema_revision": "revision",
        "migrations": migrations,
        "image_bytes": 13,
        "files": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()},
    }
    files["manifest.json"] = json.dumps(manifest).encode()
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return manifest


@pytest.mark.parametrize(
    "name,kind",
    [("../escape", "file"), ("/absolute", "file"), ("linked", "symlink"), ("device", "device")],
)
def test_archive_rejects_traversal_links_and_devices(tmp_path, name, kind):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        member = tarfile.TarInfo(name)
        if kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/shadow"
        elif kind == "device":
            member.type = tarfile.CHRTYPE
        target.addfile(member)
    with pytest.raises(ctl.OperationError):
        ctl.unpack(archive, tmp_path / "out", COMMIT)
    assert not (tmp_path / "escape").exists()


def test_archive_checks_exact_sha_inventory_and_content(tmp_path):
    archive = tmp_path / "bundle.tar.gz"
    bundle(archive)
    assert ctl.unpack(archive, tmp_path / "good", COMMIT)["backend_image"] == IMAGE
    with pytest.raises(ctl.OperationError, match="identity"):
        ctl.unpack(archive, tmp_path / "wrong", "a" * 40)
    # A file changed after hashing must be rejected.
    with tarfile.open(archive, "r:gz") as source:
        members = [(m, source.extractfile(m).read()) for m in source.getmembers()]
    with tarfile.open(archive, "w:gz") as target:
        for member, data in members:
            data = b"changed" if member.name == "compose.yml" else data
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
    with pytest.raises(ctl.OperationError, match="checksum"):
        ctl.unpack(archive, tmp_path / "corrupt", COMMIT)


def test_stale_deploy_cannot_override_newer_even_after_failure():
    record = {"sequence": 12, "sha": COMMIT}
    with pytest.raises(ctl.OperationError, match="Stale"):
        ctl.validate_sequence(record, 11, COMMIT)
    with pytest.raises(ctl.OperationError, match="reused"):
        ctl.validate_sequence(record, 12, "a" * 40)
    ctl.validate_sequence(record, 12, COMMIT)  # Same run retry is permitted.
    ctl.validate_sequence(record, 13, "b" * 40)


def test_backup_checksum_rejects_modified_dump_and_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(ctl, "STATE", tmp_path)
    (tmp_path / "backups").mkdir()
    name = "sso_backup_sso_db_20261025_120000.sql"
    dump = tmp_path / "backups" / name
    dump.write_bytes(b"synthetic snapshot")
    (tmp_path / "backup-checksums.json").write_text(
        json.dumps({name: hashlib.sha256(dump.read_bytes()).hexdigest()})
    )
    ctl.verify_backup(name)
    dump.write_bytes(b"modified")
    with pytest.raises(ctl.OperationError, match="mismatch"):
        ctl.verify_backup(name)
    with pytest.raises(ctl.OperationError, match="filename"):
        ctl.verify_backup("../runtime.env")


def test_rollback_requires_same_migrations_and_actual_schema():
    old = {"migrations": "same", "schema_revision": "revision"}
    assert ctl.can_rollback(old, old, "revision")
    assert not ctl.can_rollback(old, old | {"migrations": "changed"}, "revision")
    assert not ctl.can_rollback(old, old, "unknown")


def test_existing_configuration_is_never_regenerated(tmp_path, monkeypatch):
    config = tmp_path / "runtime.env"
    config.write_text("RESEND_API_KEY=" + json.dumps(secrets.token_urlsafe(24)) + "\n")
    monkeypatch.setattr(ctl, "CONFIG", config)
    before = config.read_bytes()
    monkeypatch.setattr(ctl.getpass, "getpass", lambda _: pytest.fail("must not prompt"))
    monkeypatch.setattr(ctl, "run", lambda *a, **k: pytest.fail("must not generate new keys"))
    ctl.configure()
    assert config.read_bytes() == before


def test_new_configuration_enables_mfa_and_admin_policy(tmp_path, monkeypatch):
    config = tmp_path / "runtime.env"
    monkeypatch.setattr(ctl, "CONFIG", config)
    monkeypatch.setattr(ctl.getpass, "getpass", lambda _: "re_" + secrets.token_hex(16))
    monkeypatch.setattr(ctl, "run", lambda *a, **k: b"synthetic-private-key-material")
    ctl.configure()
    values = ctl.settings()
    assert values["FEATURE_TOTP_ENABLED"] == "true"
    assert values["FEATURE_PASSKEY_ENABLED"] == "true"
    assert values["FEATURE_RECOVERY_CODES_ENABLED"] == "true"
    assert values["REQUIRE_ADMIN_MFA"] == "true"
    assert values["WEBAUTHN_ORIGIN"] == "https://auth.alxprgs.tech"
    assert values["WEBAUTHN_RP_ID"] == "auth.alxprgs.tech"


def test_enable_mfa_is_targeted_and_preserves_existing_configuration(tmp_path, monkeypatch, capsys):
    config = tmp_path / "runtime.env"
    secret = secrets.token_hex(24)
    config.write_text(
        "# operator comment\n"
        f"RESEND_API_KEY={json.dumps(secret)}\n"
        'FEATURE_TOTP_ENABLED="false"\n'
        'FEATURE_PASSKEY_ENABLED="false"\n'
        'FEATURE_RECOVERY_CODES_ENABLED="false"\n'
        'CUSTOM_SETTING="preserve-me"\n'
    )
    monkeypatch.setattr(ctl, "CONFIG", config)
    original = config.read_bytes()
    ctl.enable_mfa()
    values = ctl.settings()
    assert values["FEATURE_TOTP_ENABLED"] == "true"
    assert values["FEATURE_PASSKEY_ENABLED"] == "true"
    assert values["FEATURE_RECOVERY_CODES_ENABLED"] == "true"
    assert values["REQUIRE_ADMIN_MFA"] == "true"
    assert values["RESEND_API_KEY"] == secret
    assert values["CUSTOM_SETTING"] == "preserve-me"
    assert "# operator comment" in config.read_text()
    backups = list(tmp_path.glob("runtime.env.bak-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    output = capsys.readouterr()
    assert secret not in output.out + output.err


def test_mfa_status_reports_absent_keys_and_never_prints_secrets(tmp_path, monkeypatch, capsys):
    config = tmp_path / "runtime.env"
    secret = secrets.token_hex(24)
    config.write_text(f'RESEND_API_KEY={json.dumps(secret)}\nFEATURE_TOTP_ENABLED="false"\n')
    monkeypatch.setattr(ctl, "CONFIG", config)
    ctl.mfa_status()
    output = capsys.readouterr()
    assert "FEATURE_TOTP_ENABLED=false [explicit]" in output.out
    assert "FEATURE_PASSKEY_ENABLED=true [absent (code default)]" in output.out
    assert secret not in output.out + output.err


def test_compose_does_not_expose_owner_or_migration_password(tmp_path, monkeypatch):
    config = tmp_path / "runtime.env"
    values = {
        key: secrets.token_hex(32)
        for key in (
            "POSTGRES_PASSWORD",
            "SSO_MIGRATOR_PASSWORD",
            "SSO_RUNTIME_PASSWORD",
            "SESSION_SECRET_KEY",
        )
    }
    config.write_text("".join(f"{k}={json.dumps(v)}\n" for k, v in values.items()))
    (tmp_path / "manifest.json").write_text(
        json.dumps({"backend_image": IMAGE, "postgres_image": IMAGE})
    )
    monkeypatch.setattr(ctl, "CONFIG", config)
    ctl.compose(tmp_path, "up")
    app_env = (tmp_path / "app.env").read_text()
    assert values["SESSION_SECRET_KEY"] in app_env
    for key in ("POSTGRES_PASSWORD", "SSO_MIGRATOR_PASSWORD", "SSO_RUNTIME_PASSWORD"):
        assert key not in app_env and values[key] not in app_env


@pytest.fixture
def operator(tmp_path, monkeypatch):
    root = tmp_path / "root"
    state = tmp_path / "state"
    inbox = tmp_path / "incoming"
    for path in (root / "releases", root / "current", state, inbox):
        path.mkdir(parents=True)
    monkeypatch.setattr(ctl, "ROOT", root)
    monkeypatch.setattr(ctl, "STATE", state)
    monkeypatch.setattr(ctl, "INBOX", inbox)
    monkeypatch.setattr(ctl, "SITE", tmp_path / "site.conf")
    old = root / "releases/old"
    old.mkdir()
    (old / "nginx.conf").write_text("# old site")
    (old / "manifest.json").write_text(
        json.dumps({"migrations": "unchanged", "schema_revision": "revision"})
    )
    monkeypatch.setattr(ctl, "current", lambda: old)
    commands = []

    def run(*args, **kwargs):
        commands.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps([{"Architecture": "amd64"}]).encode()
        if args[:2] == ("docker", "run"):
            return json.dumps({"commit_sha": COMMIT}).encode()
        return b""

    monkeypatch.setattr(ctl, "run", run)
    monkeypatch.setattr(ctl, "compose", lambda release, *args: ["compose", str(release), *args])
    monkeypatch.setattr(ctl, "schema", lambda _: "revision")
    monkeypatch.setattr(ctl, "backup", lambda _: commands.append(("backup",)))
    monkeypatch.setattr(ctl, "ready", lambda: commands.append(("ready",)))
    monkeypatch.setattr(ctl, "public_ready", lambda: commands.append(("public_ready",)))
    monkeypatch.setattr(ctl, "switch", lambda path: commands.append(("switch", str(path))))
    # Pure unit simulation of sufficient capacity, independent of developer disk size.
    monkeypatch.setattr(
        ctl.shutil, "disk_usage", lambda _: type("Usage", (), {"free": 20 * 1024**3})()
    )
    return root, state, inbox, old, commands


def test_update_orders_stop_backup_migrate_and_ready(operator):
    root, state, inbox, old, commands = operator
    archive = inbox / "bundle.tar.gz"
    bundle(archive)
    ctl.deploy(archive, 1, COMMIT)
    stop = next(i for i, cmd in enumerate(commands) if cmd[-2:] == ("stop", "backend"))
    backup = commands.index(("backup",))
    migrate = next(i for i, cmd in enumerate(commands) if cmd[-1] == "migrate")
    assert stop < backup < migrate < commands.index(("ready",))
    assert not (state / "maintenance").exists()
    assert json.loads((state / "deployed.json").read_text())["sha"] == COMMIT
    assert not any("down" in cmd or "prune" in cmd for cmd in commands)


def test_backup_failure_never_runs_migration_and_restores_old_app(operator, monkeypatch):
    root, state, inbox, old, commands = operator
    archive = inbox / "bundle.tar.gz"
    bundle(archive, migrations="new")
    monkeypatch.setattr(
        ctl, "backup", lambda _: (_ for _ in ()).throw(ctl.OperationError("backup failed"))
    )
    with pytest.raises(ctl.OperationError, match="backup failed"):
        ctl.deploy(archive, 2, COMMIT)
    assert not any(cmd[-1] == "migrate" for cmd in commands)
    assert ("switch", str(old)) in commands
    assert not (state / "maintenance").exists()
    assert not (state / "deployed.json").exists()


def test_disk_exhaustion_rejected_before_maintenance_or_image_load(operator, monkeypatch):
    root, state, inbox, old, commands = operator
    archive = inbox / "bundle.tar.gz"
    bundle(archive)
    monkeypatch.setattr(ctl.shutil, "disk_usage", lambda _: type("Usage", (), {"free": 0})())
    with pytest.raises(ctl.OperationError, match="disk space"):
        ctl.deploy(archive, 4, COMMIT)
    assert not commands
    assert not (state / "maintenance").exists()


def test_candidate_readiness_failure_restores_only_compatible_old_application(
    operator, monkeypatch
):
    root, state, inbox, old, commands = operator
    archive = inbox / "bundle.tar.gz"
    bundle(archive)
    calls = []

    def ready():
        calls.append(True)
        if len(calls) == 1:
            raise ctl.OperationError("candidate not ready")

    monkeypatch.setattr(ctl, "ready", ready)
    with pytest.raises(ctl.OperationError, match="candidate not ready"):
        ctl.deploy(archive, 5, COMMIT)
    assert len(calls) == 2
    assert ("switch", str(old)) in commands
    assert not (state / "maintenance").exists()
    assert not (state / "deployed.json").exists()


@pytest.mark.parametrize("changed", [False, True])
def test_migration_failure_rollback_is_conservative(operator, monkeypatch, changed):
    root, state, inbox, old, commands = operator
    archive = inbox / "bundle.tar.gz"
    bundle(archive, migrations="changed" if changed else "unchanged")
    original = ctl.run

    def fail_migration(*args, **kwargs):
        if args[-1] == "migrate":
            commands.append(args)
            raise ctl.OperationError("migration failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(ctl, "run", fail_migration)
    with pytest.raises(ctl.OperationError, match="Migration failed"):
        ctl.deploy(archive, 3, COMMIT)
    assert (state / "maintenance").exists() == changed
    assert (("switch", str(old)) in commands) != changed
    assert not (state / "deployed.json").exists()


def test_cd_preserves_automatic_gate_and_adds_explicit_manual_mode():
    workflow = yaml.load((ROOT / ".github/workflows/cd.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["on"] == {
        "workflow_dispatch": {},
        "workflow_run": {"workflows": ["CI"], "types": ["completed"], "branches": ["main"]},
    }
    gate = workflow["jobs"]["build"]["if"]
    for condition in (
        "conclusion == 'success'",
        "event == 'push'",
        "head_branch == 'main'",
        "head_repository.full_name == github.repository",
    ):
        assert condition in gate
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    steps = workflow["jobs"]["build"]["steps"]
    assert steps[0]["with"]["ref"] == "${{ env.DEPLOY_SHA }}"
    assert workflow["env"]["DEPLOY_SHA"] == (
        "${{ github.event_name == 'workflow_dispatch' && github.sha || github.event.workflow_run.head_sha }}"
    )
    transport = next(
        step
        for step in workflow["jobs"]["verify"]["steps"]
        if step["name"] == "Verify the transport to be installed"
    )
    assert "scripts.check_ec2_runtime" in transport["run"]
    assert workflow["jobs"]["verify"]["if"] == "needs.build.outputs.current == 'true'"
    all_steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    assert all("continue-on-error" not in step for step in all_steps)
    for step in all_steps:
        if "uses" in step:
            assert __import__("re").search(r"@[a-f0-9]{40}$", step["uses"])
    install = workflow["jobs"]["deploy"]["steps"][-1]["run"]
    assert "latest" in install and "deploy/ec2/upload.sh" in install


@pytest.mark.parametrize(
    "event,ref,conclusion,origin,branch,same_repo,allowed",
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
def test_cd_event_gate_matrix(event, ref, conclusion, origin, branch, same_repo, allowed):
    from types import SimpleNamespace as NS

    workflow = yaml.load((ROOT / ".github/workflows/cd.yml").read_text(), Loader=yaml.BaseLoader)
    expression = workflow["jobs"]["build"]["if"].replace("&&", "and").replace("||", "or")
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


def test_production_compose_boundary_and_defaults():
    config = yaml.safe_load((ROOT / "deploy/ec2/compose.yml").read_text())
    services = config["services"]
    assert not services["db"].get("ports")
    assert services["backend"]["ports"] == ["127.0.0.1:8000:8000"]
    assert services["backend"]["environment"]["TRUSTED_PROXIES"] == '["172.29.40.1"]'
    for name in ("backend", "migrate"):
        assert services[name]["read_only"] and services[name]["cap_drop"] == ["ALL"]
        assert services[name]["env_file"].endswith("/app.env")
    assert "sso_runtime:" in services["backend"]["environment"]["DATABASE_URL"]
    assert "sso_migrator:" in services["migrate"]["environment"]["DATABASE_URL"]


def test_nginx_overwrites_client_forwarding_and_excludes_sensitive_logs():
    source = (ROOT / "deploy/ec2/nginx.conf").read_text()
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in source
    assert "proxy_set_header X-Forwarded-Proto https;" in source
    assert "$proxy_add_x_forwarded_for" not in source
    log = source.splitlines()[0]
    for field in ("$request_uri", "$args", "$remote_addr", "$http_authorization"):
        assert field not in log
    assert "ssl_reject_handshake on;" in source


def bundle_spec():
    spec = importlib.util.spec_from_file_location(
        "sso_bundle", ROOT / "scripts/build_ec2_bundle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def legacy_images_tar(path, entries):
    payload = json.dumps(entries).encode()
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo("manifest.json")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


BACKEND_TAG = "alxprgs-sso-backend:" + COMMIT
POSTGRES_TAG = "alxprgs-sso-postgres:721873c34ceb"
EXPECTED_TAGS = {BACKEND_TAG, POSTGRES_TAG}


@pytest.mark.parametrize(
    "backend_config,postgres_config",
    [
        # Docker <=24 classic archives use "<digest>.json"; Docker 25+ hybrid
        # docker-archives reference the same config under blobs/sha256/.
        ("a" * 64 + ".json", "b" * 64 + ".json"),
        ("blobs/sha256/" + "a" * 64, "blobs/sha256/" + "b" * 64),
    ],
)
def test_transport_identity_comes_from_saved_archive_not_the_daemon(
    tmp_path, backend_config, postgres_config
):
    archive = tmp_path / "images.tar"
    legacy_images_tar(
        archive,
        [
            {"Config": backend_config, "RepoTags": [BACKEND_TAG]},
            {"Config": postgres_config, "RepoTags": [POSTGRES_TAG]},
        ],
    )
    identity = bundle_spec().archive_config_digests(archive, EXPECTED_TAGS)
    assert identity == {
        BACKEND_TAG: "sha256:" + "a" * 64,
        POSTGRES_TAG: "sha256:" + "b" * 64,
    }


@pytest.mark.parametrize(
    "entries,member,match",
    [
        # OCI archives from the containerd image store carry different IDs on load.
        (
            [{"Config": "a" * 64 + ".json", "RepoTags": [BACKEND_TAG]}],
            "index.json",
            "containerd-snapshotter",
        ),
        (
            [{"Config": "a" * 64 + ".json", "RepoTags": [BACKEND_TAG]}],
            "manifest.json",
            "exactly the expected images",
        ),
        (
            [
                {"Config": "a" * 64 + ".json", "RepoTags": [BACKEND_TAG]},
                {"Config": "b" * 64 + ".json", "RepoTags": [POSTGRES_TAG]},
                {"Config": "c" * 64 + ".json", "RepoTags": ["unexpected:latest"]},
            ],
            "manifest.json",
            "exactly the expected images",
        ),
        (
            [
                {"Config": "a" * 64 + ".json", "RepoTags": [BACKEND_TAG]},
                {"Config": "b" * 64 + ".json", "RepoTags": [None]},
            ],
            "manifest.json",
            "config digest or tags",
        ),
        (
            [
                {"Config": "a" * 64 + ".json", "RepoTags": [BACKEND_TAG]},
                {"Config": "notahex.json", "RepoTags": [POSTGRES_TAG]},
            ],
            "manifest.json",
            "config digest or tags",
        ),
    ],
)
def test_transport_identity_rejects_ambiguous_archives(tmp_path, entries, member, match):
    archive = tmp_path / "images.tar"
    payload = json.dumps(entries).encode()
    with tarfile.open(archive, "w") as target:
        info = tarfile.TarInfo(member)
        info.size = len(payload)
        target.addfile(info, io.BytesIO(payload))
    with pytest.raises(ValueError, match=match):
        bundle_spec().archive_config_digests(archive, EXPECTED_TAGS)


def test_operation_error_names_failing_command_without_child_output(monkeypatch):
    def fail(*args, **kwargs):
        raise ctl.subprocess.CalledProcessError(1, args[0], stderr=b"PRIVATE-OUTPUT")

    monkeypatch.setattr(ctl.subprocess, "run", fail)
    image = "sha256:" + "c" * 64
    with pytest.raises(ctl.OperationError) as failure:
        ctl.run("docker", "image", "inspect", image)
    assert f"docker failed (docker image inspect {image})" in str(failure.value)
    assert "PRIVATE-OUTPUT" not in str(failure.value)


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


def test_cd_retry_uses_same_immutable_bundle_and_requires_verification():
    workflow = yaml.load((ROOT / ".github/workflows/cd.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    assert set(jobs) == {"build", "verify", "deploy", "public-check"}
    assert jobs["verify"]["needs"] == "build"
    assert jobs["deploy"]["needs"] == ["build", "verify"]
    assert "if" not in jobs["deploy"]  # Default success() keeps verification mandatory.
    assert jobs["deploy"]["environment"] == "production"
    assert all("environment" not in jobs[name] for name in ("build", "verify"))
    upload = next(step for step in jobs["build"]["steps"] if step.get("id") == "bundle")
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == "7"
    assert "github.run_attempt" in upload["with"]["name"]
    assert "overwrite" not in upload["with"]
    assert jobs["build"]["outputs"]["artifact_id"] == "${{ steps.bundle.outputs.artifact-id }}"
    assert jobs["build"]["outputs"]["artifact_name"] == upload["with"]["name"]
    for name in ("verify", "deploy"):
        steps = jobs[name]["steps"]
        download = next(step for step in steps if "download-artifact@" in step.get("uses", ""))
        assert download["with"]["name"] == "${{ needs.build.outputs.artifact_name }}"
        assert "run-id" not in download["with"]  # Only artifacts of this workflow run.
        assert "pattern" not in download["with"]
        assert steps[0]["with"]["ref"] == "${{ env.DEPLOY_SHA }}"
        assert not any("build_ec2_bundle.py" in step.get("run", "") for step in steps)
    install = jobs["deploy"]["steps"][-1]
    assert install["env"]["DEPLOY_SEQUENCE"] == "${{ github.run_number }}"
    assert 'latest" != "$DEPLOY_SHA' in install["run"]
    assert "scripts.check_ec2_runtime" in jobs["verify"]["steps"][-1]["run"]


def test_public_check_runs_only_after_actual_install_and_can_retry_independently():
    workflow = yaml.load((ROOT / ".github/workflows/cd.yml").read_text(), Loader=yaml.BaseLoader)
    deploy = workflow["jobs"]["deploy"]
    install = deploy["steps"][-1]
    assert install["id"] == "install"
    assert deploy["outputs"]["installed"] == "${{ steps.install.outputs.installed }}"
    assert install["run"].index("exit 0") < install["run"].index("bash deploy/ec2/upload.sh")
    assert install["run"].index("bash deploy/ec2/upload.sh") < install["run"].index(
        "installed=true"
    )
    check = workflow["jobs"]["public-check"]
    assert check["needs"] == "deploy"
    assert check["if"] == "needs.deploy.outputs.installed == 'true'"
    assert "environment" not in check
    assert check["steps"][0]["with"]["ref"] == "${{ env.DEPLOY_SHA }}"
    assert check["steps"][-1]["run"] == "python3 scripts/check_public_readiness.py"
    assert "continue-on-error" not in check
    assert not any("upload.sh" in step.get("run", "") for step in check["steps"])
