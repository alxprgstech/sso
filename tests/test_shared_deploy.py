"""Shared deployment behavior; synthetic files and mocked processes, no production access."""

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("shared_deploy", ROOT / "deploy/ec2/deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
SHA = "a" * 40


class SharedDeployTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profile = {
            "format": 1,
            "repository": "alxprgstech/sso",
            "bundle": "sso-ec2.tar.gz",
            "transport": "inbox",
            "user": "ssodeploy",
            "verify": [],
            "public_check": [],
        }
        (self.root / "deploy/ec2").mkdir(parents=True)
        (self.root / "deploy/ec2/project.json").write_text(json.dumps(self.profile))
        (self.root / self.profile["bundle"]).write_bytes(b"synthetic immutable archive")
        self.output = self.root / "output"
        self.env = {
            "GITHUB_REPOSITORY": "alxprgstech/sso",
            "DEPLOY_SHA": SHA,
            "DEPLOY_SEQUENCE": "42",
            "SSH_HOST": "example.invalid",
            "SSH_PORT": "22",
            "SSH_PRIVATE_KEY": "synthetic private key",
            "SSH_KNOWN_HOSTS": "synthetic host pin",
            "GH_TOKEN": "synthetic token",
            "GITHUB_OUTPUT": str(self.output),
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "2",
        }
        self.root_patch = patch.object(deploy, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.env_patch = patch.dict(os.environ, self.env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        stream, digest = deploy.bundle_file(self.profile)
        stream.close()
        os.environ["BUNDLE_SHA256"] = digest

    def protocol(self, result="deployed", **changes):
        value = {"version": 1, "result": result, "sha": SHA, "sequence": 42}
        value.update(changes)
        return "ssoctl-result:" + json.dumps(value)

    def test_wrong_repository_cannot_use_profile(self):
        os.environ["GITHUB_REPOSITORY"] = "attacker/fork"
        with self.assertRaises(deploy.DeployError):
            deploy.config()

    def test_protocol_identity_and_noop(self):
        result = deploy.parse_result(self.protocol("already_deployed"), SHA, 42, "inbox")
        self.assertFalse(result.installed)
        self.assertEqual(result.sha, SHA)
        for raw in (
            self.protocol(sha="b" * 40),
            self.protocol(sequence=True),
            self.protocol(version=True),
            self.protocol(result=[]),
            self.protocol() + "\n" + self.protocol(),
            "ssoctl-result:[]",
            "ssoctl-result:{",
        ):
            with self.subTest(raw=raw), self.assertRaises(deploy.DeployError):
                deploy.parse_result(raw, SHA, 42, "inbox")
        self.assertTrue(deploy.parse_result("old success", SHA, 42, "inbox").legacy)

    def test_tampered_bundle_fails_before_any_process(self):
        (self.root / self.profile["bundle"]).write_bytes(b"tampered")
        with patch.object(deploy, "run") as run, self.assertRaises(deploy.DeployError):
            deploy.upload(self.profile, SHA)
        run.assert_not_called()
        self.assertNotIn("installed=true", self.output.read_text())

    def test_empty_and_oversized_files_are_rejected(self):
        (self.root / self.profile["bundle"]).write_bytes(b"")
        with self.assertRaises(deploy.DeployError):
            deploy.bundle_file(self.profile)
        (self.root / self.profile["bundle"]).write_bytes(b"123")
        with patch.object(deploy, "MAX_BUNDLE_BYTES", 2), self.assertRaises(deploy.DeployError):
            deploy.bundle_file(self.profile)

    def test_missing_digest_and_invalid_address_fail_closed(self):
        for key, value in (
            ("BUNDLE_SHA256", ""),
            ("SSH_HOST", "-oProxyCommand=bad"),
            ("SSH_PORT", "65536"),
            ("DEPLOY_SEQUENCE", "0"),
            ("SSH_USER", "root"),
        ):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                with patch.object(deploy, "run") as run, self.assertRaises(deploy.DeployError):
                    deploy.upload(self.profile, SHA)
                run.assert_not_called()

    def test_superseded_never_contacts_server(self):
        with (
            patch.object(deploy, "current", return_value=False),
            patch.object(deploy, "run") as run,
        ):
            deploy.upload(self.profile, SHA)
        run.assert_not_called()
        self.assertIn("result=superseded", self.output.read_text())

    def test_stream_uses_verified_bytes_pinned_host_and_cleans_keys(self):
        self.profile.update(transport="stream", user="mpdeploy")
        private_paths = []

        def command(args, **kwargs):
            self.assertEqual(args[0], "ssh")
            self.assertIn("StrictHostKeyChecking=yes", args)
            self.assertIn("IdentitiesOnly=yes", args)
            self.assertEqual(args[-1], f"deploy {SHA} 42")
            self.assertEqual(kwargs["stdin"].read(), b"synthetic immutable archive")
            self.assertNotIn("GH_TOKEN", kwargs["env"])
            self.assertNotIn("SSH_PRIVATE_KEY", kwargs["env"])
            private_paths.append(Path(args[args.index("-i") + 1]))
            self.assertEqual(private_paths[-1].read_text().strip(), "synthetic private key")
            return b"private server stdout is not printed"

        with (
            patch.object(deploy, "current", return_value=True),
            patch.object(deploy, "run", side_effect=command),
        ):
            deploy.upload(self.profile, SHA)
        self.assertFalse(private_paths[0].exists())
        self.assertIn("result=deployed", self.output.read_text())

    def test_inbox_cleanup_on_server_failure_and_no_false_success(self):
        calls = []

        def command(args, **kwargs):
            calls.append(args)
            if args[-1].startswith("sudo "):
                raise deploy.DeployError("synthetic installation failure")
            return b""

        with (
            patch.object(deploy, "current", return_value=True),
            patch.object(deploy, "run", side_effect=command),
            self.assertRaises(deploy.DeployError),
        ):
            deploy.upload(self.profile, SHA)
        self.assertEqual(calls[1][0], "scp")
        self.assertIn("/proc/self/fd/", calls[1][-2])
        self.assertEqual(
            calls[-1][-1],
            "rm -f '/home/ssodeploy/incoming/123-2/sso-ec2.tar.gz'; rmdir '/home/ssodeploy/incoming/123-2'",
        )
        self.assertNotIn("installed=true", self.output.read_text())

    def test_nonzero_process_and_timeout_do_not_forward_private_output(self):
        completed = subprocess.CompletedProcess(["ssh"], 1, b"private stdout", b"private stderr")
        with (
            patch.object(deploy.subprocess, "run", return_value=completed),
            self.assertRaisesRegex(deploy.DeployError, "Deployment command failed"),
        ):
            deploy.run(["ssh"])
        with (
            patch.object(deploy.subprocess, "run", side_effect=subprocess.TimeoutExpired("ssh", 1)),
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            deploy.run(["ssh"])

    def test_report_requires_public_success_and_reports_cancelled_as_error(self):
        summary = self.root / "summary"
        os.environ.update(
            GITHUB_STEP_SUMMARY=str(summary),
            PREFLIGHT_RESULT="success",
            DEPLOY_OUTCOME="deployed",
            DEPLOY_INSTALLED_SHA=SHA,
            PUBLIC_RESULT="skipped",
        )
        self.assertEqual(deploy.report(), 1)
        os.environ["PUBLIC_RESULT"] = "success"
        self.assertEqual(deploy.report(), 0)
        os.environ["VERIFY_RESULT"] = "cancelled"
        self.assertEqual(deploy.report(), 1)

    def test_report_never_accepts_missing_or_wrong_installed_identity(self):
        os.environ.update(
            GITHUB_STEP_SUMMARY=str(self.root / "summary"),
            PREFLIGHT_RESULT="success",
            DEPLOY_OUTCOME="deployed",
            PUBLIC_RESULT="success",
        )
        for sha in ("", "b" * 40):
            with self.subTest(sha=sha), patch.dict(os.environ, {"DEPLOY_INSTALLED_SHA": sha}):
                self.assertEqual(deploy.report(), 1)

    def test_symlink_bundle_is_rejected(self):
        with (
            patch.object(Path, "is_symlink", return_value=True),
            self.assertRaises(deploy.DeployError),
        ):
            deploy.bundle_file(self.profile)

    def test_verify_cli_rejects_tampering_before_runtime_hook(self):
        (self.root / self.profile["bundle"]).write_bytes(b"changed after build")
        with patch.object(deploy, "hooks") as hooks:
            self.assertEqual(deploy.main(["verify"]), 1)
        hooks.assert_not_called()

    def test_build_cli_records_digest_from_actual_bundle(self):
        with patch.object(deploy, "hooks") as hooks:
            self.assertEqual(deploy.main(["build"]), 0)
        self.assertIn(f"sha256={os.environ['BUNDLE_SHA256']}", self.output.read_text())
        self.assertEqual(
            hooks.call_args.args[0],
            [["-m", "scripts.build_ec2_bundle", "--sha", "{sha}", "--output", "{bundle}"]],
        )

    def test_hooks_preserve_sha_and_remove_secrets(self):
        with patch.object(deploy.subprocess, "run") as run:
            deploy.hooks([["check.py", "--sha", "{sha}", "{bundle}"]], SHA, self.profile)
        self.assertEqual(run.call_args.args[0][1:], ["check.py", "--sha", SHA, "sso-ec2.tar.gz"])
        self.assertNotIn("SSH_PRIVATE_KEY", run.call_args.kwargs["env"])
        self.assertNotIn("GH_TOKEN", run.call_args.kwargs["env"])

    def test_vendored_delivery_matches_recorded_digests(self):
        pin = ROOT / "deploy/ec2/shared-deploy.json"
        if pin.is_file():
            provenance = json.loads(pin.read_text(encoding="utf-8"))
            self.assertEqual(provenance["source"], "alxprgstech/.github")
            self.assertEqual(
                set(provenance["files"]),
                {
                    "deploy/ec2/deploy.py",
                    "deploy/ec2/upload.sh",
                    "deploy/ec2/project.json",
                    "tests/test_shared_deploy.py",
                },
            )
            for name, digest in provenance["files"].items():
                self.assertEqual(
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name
                )
        else:
            # The canonical repository carries both adapter profiles, no active target.
            for project in ("mp", "sso"):
                profile = json.loads((ROOT / f"deploy/ec2/profiles/{project}.json").read_text())
                self.assertTrue(profile["verify"])
                self.assertTrue(profile["public_check"])


if __name__ == "__main__":
    unittest.main()
