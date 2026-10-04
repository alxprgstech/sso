"""Real loopback SMTP/STARTTLS with synthetic certificates, no external delivery (F-08)."""

import smtplib
import socket
import ssl
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import pytest
from app.config import Settings
from app.services.verification_email import _send_smtp
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def certificates(path: Path, hostname: str) -> tuple[Path, Path, Path]:
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic SMTP CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    ca_path, cert_path, key_path = [path / name for name in ("ca.pem", "server.pem", "server.key")]
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_path, cert_path, key_path


@contextmanager
def smtp_server(cert: Path, key: Path, advertise_tls: bool = True):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    verbs: list[tuple[str, bool]] = []
    failures: list[Exception] = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(8)

        def serve():
            connection = None
            try:
                connection, _ = listener.accept()
                connection.settimeout(5)
                stream = connection.makefile("rwb")
                stream.write(b"220 synthetic SMTP\r\n")
                stream.flush()
                tls = False
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    verb = line.split(b" ", 1)[0].strip().decode("ascii").upper()
                    verbs.append((verb, tls))  # No credential values or MIME data recorded.
                    if verb in ("EHLO", "HELO"):
                        stream.write(b"250-synthetic\r\n")
                        if advertise_tls and not tls:
                            stream.write(b"250-STARTTLS\r\n")
                        stream.write(b"250 AUTH PLAIN\r\n")
                    elif verb == "STARTTLS":
                        stream.write(b"220 ready\r\n")
                        stream.flush()
                        stream.close()
                        connection = context.wrap_socket(connection, server_side=True)
                        stream = connection.makefile("rwb")
                        tls = True
                        continue
                    elif verb == "AUTH":
                        stream.write(b"235 authenticated\r\n")
                    elif verb == "DATA":
                        stream.write(b"354 data\r\n")
                        stream.flush()
                        while stream.readline() != b".\r\n":
                            pass
                        stream.write(b"250 queued locally\r\n")
                    elif verb == "QUIT":
                        stream.write(b"221 bye\r\n")
                        stream.flush()
                        break
                    else:
                        stream.write(b"250 ok\r\n")
                    stream.flush()
                stream.close()
            except (ssl.SSLError, ConnectionResetError):
                pass  # Expected peer abort for certificate rejection.
            except Exception as error:
                failures.append(error)
            finally:
                if connection is not None:
                    connection.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield listener.getsockname()[1], verbs
        finally:
            thread.join(9)
            assert not thread.is_alive(), "Local SMTP harness did not terminate"
            assert not failures, "Local SMTP harness failed"


@pytest.mark.parametrize("case", ["trusted", "untrusted", "hostname", "no_starttls"])
def test_verified_starttls_before_credentials(tmp_path, case):
    ca, cert, key = certificates(
        tmp_path, "wrong.example.test" if case == "hostname" else "localhost"
    )
    message = EmailMessage()
    message["From"], message["To"] = "sender@example.test", "recipient@example.test"
    message.set_content("Synthetic local TLS check")
    with smtp_server(cert, key, advertise_tls=case != "no_starttls") as (port, verbs):
        settings = Settings(
            _env_file=None,
            SMTP_HOST="localhost",
            SMTP_PORT=port,
            SMTP_USE_TLS=True,
            SMTP_USER="synthetic-user",
            SMTP_PASSWORD="synthetic-password",
            SMTP_CA_FILE="" if case == "untrusted" else str(ca),
        )
        if case == "trusted":
            _send_smtp(message, settings)
            assert ("AUTH", True) in verbs and ("DATA", True) in verbs
        else:
            error = (
                smtplib.SMTPNotSupportedError
                if case == "no_starttls"
                else ssl.SSLCertVerificationError
            )
            with pytest.raises(error):
                _send_smtp(message, settings)
            assert not any(verb in ("AUTH", "DATA", "MAIL") for verb, _ in verbs)
        assert not any(verb == "AUTH" and not tls for verb, tls in verbs)


def test_credentials_refused_without_tls_before_connection(monkeypatch):
    def must_not_connect(*args, **kwargs):
        pytest.fail("Plaintext credentials must be refused before opening a connection")

    monkeypatch.setattr(smtplib, "SMTP", must_not_connect)
    with pytest.raises(ValueError):
        _send_smtp(
            EmailMessage(),
            Settings(
                _env_file=None, SMTP_USE_TLS=False, SMTP_USER="synthetic", SMTP_PASSWORD="synthetic"
            ),
        )
