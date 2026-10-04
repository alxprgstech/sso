"""The local reset must require confirmation and preserve .env on Docker errors."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell reset script")
class ResetLocalPowerShellTests(unittest.TestCase):
    def run_reset(
        self, answer: str, down_exit: int, volume: str = "sso_db_data"
    ) -> tuple[subprocess.CompletedProcess[str], list[str], bool]:
        with tempfile.TemporaryDirectory(prefix="sso-проверка-") as directory:
            root = Path(directory)
            shutil.copyfile(
                Path(__file__).resolve().parents[1] / "reset-local.ps1", root / "reset-local.ps1"
            )
            (root / "docker-compose.yml").write_text("volumes:\n  sso_db_data:\n", encoding="utf-8")
            env_file = root / ".env"
            env_file.write_text("keep-me\n", encoding="utf-8")
            call_log = root / "calls.txt"
            shell = shutil.which(getattr(self, "shell_executable", "powershell.exe"))
            self.assertIsNotNone(shell)
            script = f"""
$callLog = '{str(call_log).replace("'", "''")}'
function docker {{
    Add-Content -LiteralPath $callLog -Value ($args -join ' ') -Encoding UTF8
    if ($args[0] -eq 'context') {{ $global:LASTEXITCODE = 0; return 'default' }}
    if ($args[-2] -eq 'config') {{ $global:LASTEXITCODE = 0; return '{volume}' }}
    if ($args[-2] -eq 'down') {{ $global:LASTEXITCODE = {down_exit}; return }}
    $global:LASTEXITCODE = 1
}}
function Read-Host {{ return '{answer}' }}
& '{str(root / "reset-local.ps1").replace("'", "''")}'
"""
            result = subprocess.run(
                [shell, "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
            return result, calls, env_file.exists()

    def test_cancel_keeps_database_and_env(self) -> None:
        result, calls, env_exists = self.run_reset("нет", 0)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(env_exists)
        self.assertFalse(any(" down --volumes" in call for call in calls))

    def test_docker_failure_keeps_env(self) -> None:
        result, calls, env_exists = self.run_reset("УДАЛИТЬ SSO", 17)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(env_exists)
        self.assertTrue(any(" -p sso down --volumes" in call for call in calls))

    def test_unexpected_volume_refuses_reset(self) -> None:
        result, calls, env_exists = self.run_reset("УДАЛИТЬ SSO", 0, "unexpected_data")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(env_exists)
        self.assertFalse(any(" down --volumes" in call for call in calls))

    def test_confirmed_success_removes_env(self) -> None:
        result, calls, env_exists = self.run_reset("УДАЛИТЬ SSO", 0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(env_exists)
        self.assertTrue(any(" -p sso down --volumes" in call for call in calls))


class ResetLocalPwshTests(ResetLocalPowerShellTests):
    shell_executable = "pwsh.exe"


if __name__ == "__main__":
    unittest.main()
