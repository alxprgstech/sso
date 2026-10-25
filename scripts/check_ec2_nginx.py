"""Run in the isolated Ubuntu check image: real nginx/TLS, synthetic backend, no AWS."""

import http.server
import importlib.util
import json
import secrets
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def run(*args):
    return subprocess.run(args, check=True, capture_output=True).stdout


def main():
    for script in ("bootstrap.sh", "upload.sh"):
        run("bash", "-n", f"/check/ec2/{script}")
    certs = Path("/etc/letsencrypt/live/auth.alxprgs.tech")
    certs.mkdir(parents=True)
    run(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-subj",
        "/CN=auth.alxprgs.tech",
        "-addext",
        "subjectAltName=DNS:auth.alxprgs.tech",
        "-keyout",
        str(certs / "privkey.pem"),
        "-out",
        str(certs / "fullchain.pem"),
    )
    release = Path("/opt/alxprgs-sso/current")
    (release / "public").mkdir(parents=True)
    (release / "public/index.html").write_text("synthetic frontend")
    (release / "csp.conf").write_text(
        "add_header Content-Security-Policy \"default-src 'self'\" always;"
    )
    state = Path("/var/lib/alxprgs-sso")
    state.mkdir()
    state.chmod(0o711)
    (Path("/var/www/alxprgs-sso")).mkdir()
    Path("/var/www/alxprgs-sso/maintenance.html").write_text("maintenance")
    challenge = Path("/var/www/letsencrypt/.well-known/acme-challenge")
    challenge.mkdir(parents=True)
    (challenge / "probe").write_text("acme challenge")
    Path("/etc/nginx/sites-enabled/default").unlink(missing_ok=True)
    Path("/etc/nginx/conf.d/ec2.conf").write_bytes(Path("/check/ec2/nginx.conf").read_bytes())
    with Path("/etc/hosts").open("a") as hosts:
        hosts.write("\n127.0.0.1 auth.alxprgs.tech\n")

    class Backend(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = json.dumps(dict(self.headers)).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    backend = http.server.HTTPServer(("127.0.0.1", 8000), Backend)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    run("nginx", "-t")
    run("nginx")
    context = ssl.create_default_context(cafile=str(certs / "fullchain.pem"))
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
    )
    with opener.open("https://auth.alxprgs.tech/") as response:
        assert response.read() == b"synthetic frontend"
        assert response.headers["Strict-Transport-Security"]
        assert response.headers["Content-Security-Policy"]
    request = urllib.request.Request(
        "https://auth.alxprgs.tech/api/check?secret=do-not-log",
        headers={
            "X-Forwarded-For": "203.0.113.1",
            "X-Forwarded-Proto": "http",
            "Forwarded": "for=attacker",
            "X-ALX-Geo-City": "spoofed",
        },
    )
    with opener.open(request) as response:
        headers = json.load(response)
        assert headers["X-Forwarded-For"] == "127.0.0.1"
        assert headers["X-Forwarded-Proto"] == "https"
        assert headers["Host"] == "auth.alxprgs.tech"
        assert "Forwarded" not in headers and "X-ALX-Geo-City" not in headers
    (state / "maintenance").touch()
    for path in ("/", "/api/check", "/health/ready"):
        try:
            opener.open("https://auth.alxprgs.tech" + path)
            raise AssertionError("maintenance bypass")
        except urllib.error.HTTPError as error:
            assert error.code == 503 and error.read() == b"maintenance"
    with opener.open("http://auth.alxprgs.tech/.well-known/acme-challenge/probe") as response:
        assert response.read() == b"acme challenge"
    (state / "maintenance").unlink()
    with opener.open("https://auth.alxprgs.tech/") as response:
        assert response.status == 200
    run("nginx", "-s", "quit")
    log = Path("/var/log/nginx/sso-access.log").read_text()
    assert "do-not-log" not in log and "secret=" not in log and "203.0.113.1" not in log
    backend.shutdown()
    print(
        "PASS: Ubuntu nginx config, trusted TLS, forwarded-header overwrite, maintenance, ACME, safe logs, bash syntax"
    )

    spec = importlib.util.spec_from_file_location("ssoctl", "/check/ec2/ssoctl.py")
    ctl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ctl)
    ctl.CONFIG = Path("/tmp/synthetic-runtime.env")
    ctl.getpass.getpass = lambda _: secrets.token_urlsafe(32)
    ctl.configure()
    generated = ctl.CONFIG.read_bytes()
    cfg = ctl.settings()
    assert ctl.CONFIG.stat().st_mode & 0o777 == 0o600
    assert len(set(cfg["SESSION_SECRET_KEY"])) >= 16
    assert cfg["FEATURE_EMAIL_VERIFICATION_ENABLED"] == "true"
    for flag in (
        "FEATURE_TOTP_ENABLED",
        "FEATURE_PASSKEY_ENABLED",
        "FEATURE_RECOVERY_CODES_ENABLED",
    ):
        assert cfg[flag] == "false"
    private_key = Path("/tmp/synthetic-rsa.pem")
    private_key.write_text(cfg["JWT_PRIVATE_KEY_PEM"])
    run("openssl", "pkey", "-in", str(private_key), "-check", "-noout")
    ctl.configure()
    assert ctl.CONFIG.read_bytes() == generated
    print(
        "PASS: real OpenSSL persistent configuration, permissions, default-off flags and idempotent configure"
    )
    # Prove actual flock exclusion between independent processes.
    marker = state / "child-acquired"
    with ctl.locked():
        process = subprocess.Popen(
            [
                "python3",
                "-c",
                'import sys; sys.path.insert(0,"/check/ec2"); import ssoctl; '
                "exec(\"with ssoctl.locked():\\n    (ssoctl.STATE / 'child-acquired').touch()\")",
            ]
        )
        time.sleep(0.2)
        assert not marker.exists()
    assert process.wait(timeout=5) == 0
    assert marker.exists()
    print("PASS: independent-process deployment flock")


if __name__ == "__main__":
    main()
