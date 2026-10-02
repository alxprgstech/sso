"""Check Bash first-run configuration with an isolated Docker stub."""

import base64
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class StartBashTests(unittest.TestCase):
    def test_generated_env_matches_compose(self) -> None:
        bash = shutil.which("bash")
        if os.name == "nt" and Path(r"C:\Program Files\Git\bin\bash.exe").exists():
            bash = r"C:\Program Files\Git\bin\bash.exe"
        if bash is None:
            self.skipTest("Bash is unavailable")

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            shutil.copyfile(root / "start.sh", tmp_path / "start.sh")
            shutil.copyfile(root / ".env.example", tmp_path / ".env.example")
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            docker = bin_dir / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                "  'compose up -d --build') exit 17 ;;\n"
                "  'compose ps -q frontend') echo owned-frontend ;;\n"
                "esac\n"
                "exit 0\n",
                encoding="ascii",
            )
            docker.chmod(0o755)
            git = bin_dir / "git"
            git.write_text("#!/bin/sh\nprintf '%s\\n' " + "a" * 40 + "\n", encoding="ascii")
            git.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")
            result = subprocess.run(
                [bash, "-c", 'export PATH="$PWD/bin:$PATH"; exec bash start.sh'],
                cwd=tmp_path,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 17, result.stderr)
            generated = (tmp_path / ".env").read_bytes().decode("utf-8", errors="strict")
            self.assertIn(
                (root / ".env.example").read_text(encoding="utf-8").splitlines()[1], generated
            )
            values = dict(re.findall(r"^([A-Z_]+)=(.*)$", generated, flags=re.MULTILINE))
            password = values["POSTGRES_PASSWORD"]
            self.assertRegex(password, r"^[0-9a-f]{48}$")
            expected = f"postgresql+psycopg://sso_user:{password}@db:5432/sso_db"
            self.assertEqual(values["DATABASE_URL"], expected)
            self.assertEqual(values["DATABASE_URL_SYNC"], expected)
            self.assertEqual(values["FRONTEND_URL"], "http://localhost:3000")
            self.assertEqual(values["BASE_URL"], "http://localhost:3000")
            self.assertEqual(values["WEBAUTHN_RP_ID"], "localhost")
            self.assertEqual(values["WEBAUTHN_ORIGIN"], "http://localhost:3000")
            self.assertEqual(len(base64.urlsafe_b64decode(values["TOTP_ENCRYPTION_KEY"])), 32)
            for name in (
                "FEATURE_TOTP_ENABLED",
                "FEATURE_PASSKEY_ENABLED",
                "FEATURE_RECOVERY_CODES_ENABLED",
            ):
                self.assertEqual(values[name], "false")
            self.assertNotIn(password, result.stdout + result.stderr)
            self.assertNotIn("ALX_BUILD_SHA", generated)
            git.write_text("#!/bin/sh\necho invalid\n", encoding="ascii")
            invalid = subprocess.run(
                [bash, "-c", 'export PATH="$PWD/bin:$PATH"; exec bash start.sh'],
                cwd=tmp_path,
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(invalid.returncode, 1)
            self.assertIn("Cannot determine the full Git revision", invalid.stderr)
            self.assertEqual((tmp_path / ".env").read_bytes().decode("utf-8"), generated)
