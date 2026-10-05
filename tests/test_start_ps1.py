"""Regression checks for the Windows first-run command and configuration."""

import base64
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell startup script")
class StartPowerShellTests(unittest.TestCase):
    def run_start(
        self, tmp_path: Path, fallback: bool, revision: str = "a" * 40
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        shell = shutil.which(getattr(self, "shell_executable", "powershell.exe"))
        self.assertIsNotNone(shell, "Windows PowerShell is required for this check")
        source = Path(__file__).resolve().parents[1] / "start.ps1"
        script = tmp_path / "start.ps1"
        shutil.copyfile(source, script)
        log = tmp_path / "docker-args.txt"

        # Stop at Compose up; no real daemon, containers, or HTTP server are used.
        ps_script = f"""
$env:COMPOSE_DISABLE_ENV_FILE = '1'
$env:COMPOSE_ENV_FILES = 'unrelated.env'
$logPath = '{str(log).replace("'", "''")}'
function git {{ $global:LASTEXITCODE = 0; '{revision}' }}
function docker {{
    $operation = if ($args[1] -eq 'version') {{ 'version' }} else {{ $args[5] }}
    $commandLine = 'docker ' + ($args -join ' ')
    Add-Content -LiteralPath $logPath -Value $commandLine -Encoding UTF8
    if ($args[0] -eq 'compose' -and $args[1] -eq 'version' -and ${str(fallback).lower()}) {{
        $global:LASTEXITCODE = 1
    }} elseif ($args[0] -eq 'compose' -and $operation -eq 'up') {{
        $global:LASTEXITCODE = 17
    }} else {{
        $global:LASTEXITCODE = 0
        if ($args[0] -eq 'compose' -and $operation -eq 'ps') {{ 'owned-frontend' }}
    }}
}}
function docker-compose {{
    $operation = $args[4]
    Add-Content -LiteralPath $logPath -Value ('docker-compose ' + ($args -join ' ')) -Encoding UTF8
    if ($operation -eq 'up') {{ $global:LASTEXITCODE = 17 }}
    else {{ $global:LASTEXITCODE = 0; if ($operation -eq 'ps') {{ 'owned-frontend' }} }}
}}
& '{str(script).replace("'", "''")}' -NonInteractive -NoBrowser
"""
        result = subprocess.run(
            [
                shell,
                "-NoProfile",
                "-ExecutionPolicy",
                "RemoteSigned",
                "-NonInteractive",
                "-Command",
                ps_script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        return result, log

    def test_start_passes_compose_as_separate_arguments(self) -> None:
        for fallback in (False, True):
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as directory:
                tmp_path = Path(directory)
                fixture = (
                    "SSO_RUNTIME_PASSWORD=synthetic-runtime\n"  # pragma: allowlist secret
                    "SSO_MIGRATOR_PASSWORD=synthetic-migrator\n"  # pragma: allowlist secret
                )
                (tmp_path / ".env").write_text(fixture, encoding="utf-8")
                result, log = self.run_start(tmp_path, fallback)
                executable = "docker-compose" if fallback else "docker compose"
                expected = (
                    f"{executable} --env-file {tmp_path / '.env'} "
                    f"-f {tmp_path / 'docker-compose.yml'} up -d --build"
                )
                self.assertTrue(log.exists(), f"stdout={result.stdout!r}; stderr={result.stderr!r}")
                self.assertIn(expected, log.read_text(encoding="utf-8").splitlines())
                self.assertEqual(result.returncode, 1)
                self.assertIn("Docker Compose (TEST-SETUP-04)", result.stdout)
                self.assertNotIn("CommandNotFoundException", result.stderr)
                self.assertNotIn("ALX_BUILD_SHA", (tmp_path / ".env").read_text(encoding="utf-8"))
                self.assertEqual(
                    (tmp_path / ".env").read_text(encoding="utf-8"),
                    fixture,
                )

    def test_legacy_env_refuses_start_with_recovery_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = b"# legacy configuration\n"
            (root / ".env").write_bytes(original)
            result, log = self.run_start(root, False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SSO_RUNTIME_PASSWORD", result.stdout)
            self.assertIn("SSO_MIGRATOR_PASSWORD", result.stdout)
            self.assertIn("docs/operations.md", result.stdout)
            self.assertIn("reset-local.ps1", result.stdout)
            self.assertNotIn("up -d --build", log.read_text(encoding="utf-8"))
            self.assertEqual((root / ".env").read_bytes(), original)

    def test_generated_env_is_utf8_and_compose_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            template = Path(__file__).resolve().parents[1] / ".env.example"
            shutil.copyfile(template, tmp_path / ".env.example")
            result, log = self.run_start(tmp_path, False)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue(log.exists(), result.stderr)
            raw = (tmp_path / ".env").read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            generated = raw.decode("utf-8", errors="strict")
            self.assertIn(template.read_text(encoding="utf-8").splitlines()[1], generated)
            values = dict(re.findall(r"^([A-Z_]+)=(.*)$", generated, flags=re.MULTILINE))
            db_password = values["POSTGRES_PASSWORD"]
            self.assertRegex(db_password, r"^[0-9a-f]{48}$")
            passwords = [
                values[name]
                for name in ("POSTGRES_PASSWORD", "SSO_RUNTIME_PASSWORD", "SSO_MIGRATOR_PASSWORD")
            ]
            self.assertEqual(len(set(passwords)), 3)
            self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", value) for value in passwords[1:]))
            url = (
                f"postgresql+psycopg://sso_runtime:{values['SSO_RUNTIME_PASSWORD']}@db:5432/sso_db"
            )
            self.assertTrue(
                values["DATABASE_URL"] == url,
                "Runtime URL must use the limited role and its independent password",
            )
            self.assertTrue(values["DATABASE_URL_SYNC"] == url)
            self.assertEqual(values["BASE_URL"], "http://localhost:3000")
            self.assertEqual(values["FRONTEND_URL"], "http://localhost:3000")
            self.assertEqual(values["WEBAUTHN_RP_ID"], "localhost")
            self.assertEqual(values["WEBAUTHN_ORIGIN"], "http://localhost:3000")
            self.assertEqual(values["DEBUG"], "false")
            self.assertRegex(values["SESSION_SECRET_KEY"], r"^[0-9a-f]{128}$")
            self.assertEqual(len(base64.urlsafe_b64decode(values["TOTP_ENCRYPTION_KEY"])), 32)
            for name in (
                "FEATURE_TOTP_ENABLED",
                "FEATURE_PASSKEY_ENABLED",
                "FEATURE_RECOVERY_CODES_ENABLED",
                "REQUIRE_VERIFIED_EMAIL",
            ):
                self.assertEqual(values[name], "false")
            self.assertTrue(all(value not in result.stdout + result.stderr for value in passwords))

    def test_invalid_build_revision_refuses_compose_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / ".env").write_text("# preserved\n", encoding="utf-8")
            result, log = self.run_start(tmp_path, False, revision="invalid")
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(
                "up -d --build", log.read_text(encoding="utf-8") if log.exists() else ""
            )
            self.assertEqual((tmp_path / ".env").read_text(encoding="utf-8"), "# preserved\n")


class StartPwshTests(StartPowerShellTests):
    shell_executable = "pwsh.exe"
