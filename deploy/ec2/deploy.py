#!/usr/bin/env python3
"""Shared EC2 delivery driver. Python 3.11+, standard library only.

Canonical source: alxprgstech/.github, deploy/ec2/deploy.py.
Project adapters live in project.json; privileged ctl deliveries are separate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[2]
MAX_BUNDLE_BYTES = 3 * 1024**3
SHA = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"[a-f0-9]{64}")


class DeployError(Exception):
    """Only sanitized diagnostics may be printed by the CLI."""


class Result(NamedTuple):
    result: str
    installed: bool
    sha: str
    reason: str
    legacy: bool = False


def outputs(values: dict[str, str], destination: str | None = None) -> None:
    path = destination or os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise DeployError("GITHUB_OUTPUT is required")
    if any("\n" in str(v) or "\r" in str(v) for v in values.values()):
        raise DeployError("Invalid multiline output")
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.writelines(f"{key}={value}\n" for key, value in values.items())


def result_outputs(result: Result) -> None:
    outputs(
        {
            "result": result.result,
            "installed": str(result.installed).lower(),
            "installed_sha": result.sha,
            "reason": result.reason,
            "legacy": str(result.legacy).lower(),
        }
    )


def config() -> dict:
    value = json.loads((ROOT / "deploy/ec2/project.json").read_text(encoding="utf-8"))
    required = {"format", "repository", "bundle", "transport", "user", "verify", "public_check"}
    if set(value) != required or value["format"] != 1:
        raise DeployError("Unsupported deployment profile")
    if value["transport"] not in {"stream", "inbox"}:
        raise DeployError("Unsupported transport")
    if not re.fullmatch(r"[a-z][a-z0-9-]*\.tar\.gz", value["bundle"]):
        raise DeployError("Invalid bundle filename")
    expected_user = "mpdeploy" if value["transport"] == "stream" else "ssodeploy"
    if value["user"] != expected_user:
        raise DeployError("Deployment user does not match the transport contract")
    if os.environ.get("GITHUB_REPOSITORY") != value["repository"]:
        raise DeployError("Deployment profile does not match GITHUB_REPOSITORY")
    return value


def target() -> str:
    sha = os.environ.get("DEPLOY_SHA", "")
    if not SHA.fullmatch(sha):
        raise DeployError("DEPLOY_SHA must be a full lowercase commit SHA")
    return sha


def run(command: list[str], **kwargs) -> bytes:
    # Child output can contain private host diagnostics. Never forward it to CI.
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        timeout=kwargs.pop("timeout", 1500),
        **kwargs,
    )
    if completed.returncode:
        raise DeployError("Deployment command failed; inspect private runner/server diagnostics")
    return completed.stdout


def current(sha: str, profile: dict) -> bool:
    latest = (
        run(
            [
                "gh",
                "api",
                f"repos/{profile['repository']}/git/ref/heads/main",
                "--jq",
                ".object.sha",
            ],
            timeout=30,
        )
        .decode()
        .strip()
    )
    if not SHA.fullmatch(latest):
        raise DeployError("GitHub returned an invalid main revision")
    return latest == sha


def bundle_file(profile: dict, expected: str | None = None):
    path = ROOT / profile["bundle"]
    # Hash and send the same open regular file; never follow a replaced symlink.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    stream = os.fdopen(fd, "rb")
    try:
        info = os.fstat(stream.fileno())
        if (
            path.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or not 0 < info.st_size <= MAX_BUNDLE_BYTES
        ):
            raise DeployError("Transport must be a regular nonempty file of at most 3 GiB")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if expected is not None and (not DIGEST.fullmatch(expected) or digest != expected):
            raise DeployError("Transport digest does not match the build job output")
        stream.seek(0)
        return stream, digest
    except BaseException:
        stream.close()
        raise


def parse_result(raw: str, sha: str, sequence: int, transport: str) -> Result:
    if transport == "stream":
        # MP's fixed forced-command contract reports success through exit status.
        return Result("deployed", True, sha, "verified stream installation completed")
    lines = [line for line in raw.splitlines() if line.startswith("ssoctl-result:")]
    if not lines:
        return Result(
            "deployed_legacy",
            True,
            sha,
            "legacy operator: server-side idempotency guard is not active",
            True,
        )
    if len(lines) != 1:
        raise DeployError("Server returned multiple deployment protocol lines")
    try:
        value = json.loads(lines[0].removeprefix("ssoctl-result:"))
    except ValueError:
        raise DeployError("Server deployment protocol is not valid JSON") from None
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "result", "sha", "sequence"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["result"] not in ("deployed", "already_deployed")
        or value["sha"] != sha
        or type(value["sequence"]) is not int
        or value["sequence"] != sequence
    ):
        raise DeployError("Server deployment protocol does not match this run")
    installed = value["result"] == "deployed"
    return Result(
        value["result"],
        installed,
        sha,
        "new installation completed"
        if installed
        else "server confirmed the same revision is installed",
    )


def upload(profile: dict, sha: str) -> None:
    result_outputs(Result("error", False, "", "installation has not completed"))
    expected = os.environ.get("BUNDLE_SHA256", "")
    sequence = os.environ.get("DEPLOY_SEQUENCE", "")
    host, port = os.environ.get("SSH_HOST", ""), os.environ.get("SSH_PORT", "22")
    if (
        not re.fullmatch(r"[1-9][0-9]{0,17}", sequence)
        or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", host)
        or not re.fullmatch(r"[0-9]{1,5}", port)
        or not 1 <= int(port) <= 65535
    ):
        raise DeployError("Invalid deployment sequence or SSH address")
    if os.environ.get("SSH_USER", profile["user"]) != profile["user"]:
        raise DeployError("SSH_USER does not match the deployment profile")
    if not DIGEST.fullmatch(expected):
        raise DeployError("BUNDLE_SHA256 from the build job is required")
    with bundle_file(profile, expected)[0] as bundle:
        if not current(sha, profile):
            result_outputs(Result("superseded", False, "", "main advanced before installation"))
            return
        with tempfile.TemporaryDirectory(prefix="ec2-delivery-") as private:
            directory = Path(private)
            for name, variable in (("key", "SSH_PRIVATE_KEY"), ("known_hosts", "SSH_KNOWN_HOSTS")):
                content = os.environ.pop(variable, "")
                if not content.strip():
                    raise DeployError(
                        "Dedicated SSH key and independently verified known hosts are required"
                    )
                path = directory / name
                with path.open("x", encoding="utf-8", newline="\n") as stream:
                    path.chmod(0o600)
                    stream.write(content + "\n")
            options = [
                "-i",
                str(directory / "key"),
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={directory / 'known_hosts'}",
                "-o",
                "ConnectTimeout=15",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=4",
            ]
            destination = f"{profile['user']}@{host}"
            ssh = ["ssh", "-T", *options, "-p", port, destination]
            # Never pass CI credentials to gh, scp, ssh or other child processes.
            env = {
                k: v
                for k, v in os.environ.items()
                if k not in {"GH_TOKEN", "GITHUB_TOKEN", "SSH_PRIVATE_KEY", "SSH_KNOWN_HOSTS"}
            }
            if profile["transport"] == "stream":
                raw = run([*ssh, f"deploy {sha} {sequence}"], stdin=bundle, env=env)
            else:
                raw = upload_inbox(
                    profile, sha, sequence, bundle, ssh, options, port, destination, env
                )
    result = parse_result(
        raw.decode("utf-8", errors="replace"), sha, int(sequence), profile["transport"]
    )
    result_outputs(result)
    print(f"Deployment result: {result.result}")


def upload_inbox(profile, sha, sequence, bundle, ssh, options, port, destination, env):
    run_id, attempt = os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not all(re.fullmatch(r"[1-9][0-9]{0,19}", v) for v in (run_id, attempt)):
        raise DeployError("Invalid GitHub run identity")
    remote = f"/home/ssodeploy/incoming/{run_id}-{attempt}"
    archive = f"{remote}/{profile['bundle']}"
    run([*ssh, f"umask 077; mkdir '{remote}'"], env=env, timeout=30)
    try:
        # /proc/self/fd keeps scp bound to the already verified open file on Linux.
        # scp must dereference this local path; no shell interpolation is involved.
        run(
            [
                "scp",
                *options,
                "-P",
                port,
                f"/proc/self/fd/{bundle.fileno()}",
                f"{destination}:{archive}",
            ],
            pass_fds=(bundle.fileno(),),
            env=env,
        )
        return run(
            [*ssh, f"sudo -n /usr/local/sbin/ssoctl deploy '{archive}' '{sequence}' '{sha}'"],
            env=env,
        )
    finally:
        try:
            run([*ssh, f"rm -f '{archive}'; rmdir '{remote}'"], env=env, timeout=30)
        except (DeployError, subprocess.TimeoutExpired, OSError):
            print("Warning: run-specific inbox cleanup failed", file=sys.stderr)


def hooks(commands: list[list[str]], sha: str, profile: dict) -> None:
    for command in commands:
        args = [
            part.replace("{sha}", sha).replace("{bundle}", profile["bundle"]) for part in command
        ]
        # Verification logs are needed for diagnosis. These hooks never receive SSH secrets.
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"SSH_PRIVATE_KEY", "SSH_KNOWN_HOSTS", "GH_TOKEN", "GITHUB_TOKEN"}
        }
        subprocess.run([sys.executable, *args], cwd=ROOT, env=env, check=True, timeout=2400)


def report() -> int:
    def get(key: str) -> str:
        return os.environ.get(key, "")

    decision, outcome = get("DECISION"), get("DEPLOY_OUTCOME")
    public = get("PUBLIC_RESULT")
    failed = any(
        get(key) in {"failure", "cancelled"}
        for key in (
            "PREFLIGHT_RESULT",
            "BUILD_RESULT",
            "VERIFY_RESULT",
            "DEPLOY_RESULT",
            "PUBLIC_RESULT",
        )
    )
    if failed:
        result = "error"
    elif decision == "superseded" or outcome == "superseded":
        result = "superseded"
    elif public == "success" and (decision == "already_deployed" or outcome == "already_deployed"):
        result = "already_deployed"
    elif public == "success" and outcome in {"deployed", "deployed_legacy"}:
        result = outcome
    elif get("PREFLIGHT_RESULT") == "skipped":
        result = "not_run"
    else:
        result = "error"
    sha = get("DEPLOY_INSTALLED_SHA") or get("PREFLIGHT_INSTALLED_SHA")
    sha = sha if SHA.fullmatch(sha) else "unknown"
    if result in {"deployed", "deployed_legacy", "already_deployed"} and sha != target():
        result = "error"
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(
            f"### EC2 deployment\n\nTarget: `{target()}`\n\nInstalled: `{sha}`\n\nResult: `{result}`\n"
        )
        if outcome == "deployed_legacy":
            stream.write(
                "\nLegacy server operator: server-side idempotency is not active; update ctl separately.\n"
            )
        if get("QUALITY_EXCEPTION") == "true":
            stream.write("\nOwner-approved Quality exception; Quality remains unpassed.\n")
        stream.write("\n| Stage | Result |\n| --- | --- |\n")
        for stage in ("PREFLIGHT", "BUILD", "VERIFY", "DEPLOY", "PUBLIC"):
            status = get(f"{stage}_RESULT")
            status = (
                status if status in {"success", "failure", "cancelled", "skipped"} else "unknown"
            )
            stream.write(f"| {stage.lower()} | {status} |\n")
    return int(result == "error")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("build", "verify", "upload", "public-check", "report"))
    args = parser.parse_args(argv)
    try:
        if args.phase == "report":
            return report()
        profile, sha = config(), target()
        if args.phase == "build":
            hooks(
                [["-m", "scripts.build_ec2_bundle", "--sha", "{sha}", "--output", "{bundle}"]],
                sha,
                profile,
            )
            stream, digest = bundle_file(profile)
            stream.close()
            outputs({"sha256": digest})
        elif args.phase == "verify":
            stream, _ = bundle_file(profile, os.environ.get("BUNDLE_SHA256", ""))
            stream.close()
            hooks(profile["verify"], sha, profile)
        elif args.phase == "upload":
            upload(profile, sha)
        else:
            hooks(profile["public_check"], sha, profile)
        return 0
    except DeployError as error:
        print(f"EC2 deployment failed: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print(
            "EC2 deployment failed; check profile, immutable digest, credentials and private diagnostics",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
