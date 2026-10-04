"""Real cryptography and process checks for F-01/F-13/F-20; no production secrets."""

import base64
import json
import os
import secrets
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from app.api.deps import generate_csrf_token, verify_csrf
from app.config import Settings
from app.core import security
from app.core.exceptions import OAuthErrorException
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException, Request
from pydantic import ValidationError

from scripts.migrate_totp_key import rotate_ciphertexts
from scripts.rotate_keys import generate_bundle, generate_session_secret


@pytest.fixture
def production_values(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "rsa.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return dict(
        _env_file=None,
        ENVIRONMENT="production",
        DEBUG=False,
        SESSION_SECRET_KEY=generate_session_secret(),
        TOTP_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        JWT_PRIVATE_KEY_PEM=str(path),
        JWT_KEY_ID="test-persistent-v1",
        OIDC_ISSUER="https://auth.example.test",
        BASE_URL="https://auth.example.test",
        FRONTEND_URL="https://auth.example.test",
        WEBAUTHN_ORIGIN="https://auth.example.test",
        WEBAUTHN_RP_ID="auth.example.test",
        EMAIL_PROVIDER="smtp",
        SMTP_USE_TLS=True,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("SESSION_SECRET_KEY", ""),
        ("SESSION_SECRET_KEY", "x" * 128),
        ("SESSION_SECRET_KEY", Settings.model_fields["SESSION_SECRET_KEY"].default),
        ("SESSION_SECRET_KEY", "change-me-to-a-secure-random-string-at-least-64-characters-long"),
        ("TOTP_ENCRYPTION_KEY", ""),
        ("TOTP_ENCRYPTION_KEY", "invalid"),
        ("TOTP_ENCRYPTION_KEY", Settings.model_fields["TOTP_ENCRYPTION_KEY"].default),
        ("JWT_PRIVATE_KEY_PEM", ""),
        ("JWT_PRIVATE_KEY_PEM", "missing-file.pem"),
        ("JWT_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----\nmalformed"),
        ("JWT_KEY_ID", "default-rsa-key-1"),
        ("JWT_KEY_ID", ""),
        ("JWT_KEY_ID", "bad kid"),
        ("JWT_KEY_ID", "x" * 129),
        ("OIDC_ISSUER", "http://auth.example.test"),
        ("BASE_URL", "https://other.example.test"),
        ("FRONTEND_URL", "https://auth.example.test/path"),
        ("FRONTEND_URL", "https://user:pass@auth.example.test"),
        ("FRONTEND_URL", "https://auth.example.test#fragment"),
        ("WEBAUTHN_ORIGIN", "https://other.example.test"),
        ("WEBAUTHN_RP_ID", "example.test"),
        ("ACCESS_TOKEN_TTL_SECONDS", 301),
        ("ACCESS_TOKEN_TTL_SECONDS", 0),
        ("AUTH_CODE_TTL_SECONDS", 61),
        ("SESSION_ABSOLUTE_TIMEOUT_SECONDS", 604801),
        ("SESSION_IDLE_TIMEOUT_SECONDS", 43201),
        ("REFRESH_TOKEN_TTL_SECONDS", 604801),
        ("REFRESH_FAMILY_MAX_LIFETIME_SECONDS", 2592001),
        ("MFA_STEP_TTL_SECONDS", 301),
        ("SMTP_USE_TLS", False),
        ("DEBUG", True),
        ("SESSION_COOKIE_NAME", "alx_session"),
        ("TOTP_ENCRYPTION_KEY", base64.urlsafe_b64encode(bytes(32)).decode()),
    ],
)
def test_production_rejects_unsafe_config(production_values, field, value):
    production_values[field] = value
    with pytest.raises(ValidationError):
        Settings(**production_values)


def test_defaults_remain_development_and_mfa_off(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.ENVIRONMENT == "development"
    assert not settings.FEATURE_TOTP_ENABLED
    assert not settings.FEATURE_PASSKEY_ENABLED
    assert not settings.FEATURE_RECOVERY_CODES_ENABLED
    assert settings.FEATURE_EMAIL_VERIFICATION_ENABLED


def test_production_valid_config_and_no_secret_error(production_values):
    assert Settings(**production_values).ENVIRONMENT == "production"
    secret = "change-me-" + secrets.token_hex(64)
    production_values["SESSION_SECRET_KEY"] = secret
    with pytest.raises(ValidationError) as error:
        Settings(**production_values)
    assert secret not in str(error.value)


@pytest.mark.parametrize("size", [1024, "ec"])
def test_rejects_inappropriate_signing_material(production_values, tmp_path, size):
    key = (
        ec.generate_private_key(ec.SECP256R1())
        if size == "ec"
        else rsa.generate_private_key(public_exponent=65537, key_size=size)
    )
    path = tmp_path / "bad.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    production_values["JWT_PRIVATE_KEY_PEM"] = str(path)
    with pytest.raises(ValidationError):
        Settings(**production_values)


def test_workers_and_restart_share_persistent_key(production_values, tmp_path):
    # Two independent imports/processes; second verifies the first worker's signed JWT.
    env = {**os.environ, "PYTHONPATH": str(Path("backend").absolute())}
    for name, value in production_values.items():
        if name != "_env_file":
            env[name] = str(value).lower() if isinstance(value, bool) else str(value)
    token_path = tmp_path / "worker-token"
    env["SYNTHETIC_TOKEN_FILE"] = str(token_path)
    issue = "from app.core.security import create_jwt; from pathlib import Path; import os; Path(os.environ['SYNTHETIC_TOKEN_FILE']).write_text(create_jwt({'sub':'synthetic','aud':'rp','token_use':'access_token','scope':'openid'},60),encoding='ascii')"
    verify = "from app.core.security import decode_jwt,get_jwks; from pathlib import Path; import os,json; assert decode_jwt(Path(os.environ['SYNTHETIC_TOKEN_FILE']).read_text(),audience='rp')['sub']=='synthetic'; print(json.dumps(get_jwks(),sort_keys=True))"
    issued = subprocess.run(
        [sys.executable, "-c", issue], env=env, cwd=tmp_path, capture_output=True
    )
    assert issued.returncode == 0, issued.stderr.decode("utf-8", errors="replace")

    def verify_worker(_):
        return subprocess.run(
            [sys.executable, "-c", verify],
            env=env,
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(verify_worker, range(2)))
    assert results[0] == results[1]
    assert json.loads(results[0])["keys"][0]["kid"] == production_values["JWT_KEY_ID"]


def test_rotation_overlap_and_retirement(production_values, monkeypatch):
    previous = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    production_values.update(
        JWT_PREVIOUS_KEY_ID="previous-v0",
        JWT_PREVIOUS_PUBLIC_KEY_PEM=previous.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
        JWT_PREVIOUS_KEY_VALID_UNTIL=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    settings = Settings(**production_values)
    monkeypatch.setattr(security, "settings", settings)
    monkeypatch.setattr(security, "_active_key_id", settings.JWT_KEY_ID)
    monkeypatch.setattr(security, "_cached_private_key", None)
    monkeypatch.setattr(security, "_retired_public_keys", {})
    security._init_retired_keys()
    old_token = jwt.encode(
        dict(
            iss=settings.OIDC_ISSUER,
            sub="synthetic",
            aud="rp",
            iat=int(datetime.now().timestamp()),
            exp=int(datetime.now().timestamp()) + 60,
        ),
        previous,
        algorithm="RS256",
        headers={"kid": "previous-v0"},
    )
    assert security.decode_jwt(old_token, audience="rp")["sub"] == "synthetic"
    assert len(security.get_jwks()["keys"]) == 2
    with pytest.raises(ValueError):
        security.rotate_active_signing_key()
    settings.JWT_PREVIOUS_KEY_VALID_UNTIL = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert len(security.get_jwks()["keys"]) == 1
    with pytest.raises(OAuthErrorException):
        security.decode_jwt(old_token, audience="rp")


@pytest.mark.parametrize("kid", [[], {}, None, "x" * 129])
def test_hostile_key_identifier_has_controlled_failure(kid):
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "kid": kid}).encode())
        .decode()
        .rstrip("=")
    )
    token = header + ".e30.c3ludGhldGlj"
    with pytest.raises(OAuthErrorException) as failure:
        security.decode_jwt(token)
    assert failure.value.status_code == 401


@pytest.mark.parametrize(
    "kind,filename",
    [
        ("rsa", "oidc_private.pem"),
        ("session", "SESSION_SECRET_KEY"),
        ("totp", "TOTP_ENCRYPTION_KEY"),
    ],
)
def test_generator_private_files_no_output_or_overwrite(tmp_path, capsys, kind, filename):
    destination = tmp_path / "Ключи"
    generate_bundle(destination, kind, "synthetic-kid", 2048)
    contents = (destination / filename).read_bytes()
    assert contents
    assert capsys.readouterr().out == ""
    with pytest.raises(FileExistsError):
        generate_bundle(destination, kind, "another", 2048)
    assert (destination / filename).read_bytes() == contents
    if os.name != "nt":
        assert destination.stat().st_mode & 0o777 == 0o700
        assert (destination / filename).stat().st_mode & 0o777 == 0o600
    else:
        from scripts.rotate_keys import write_private

        with pytest.raises(FileExistsError):
            write_private(destination / filename, b"replacement")
        acl = subprocess.run(["icacls", str(destination)], capture_output=True, check=True).stdout
        assert b"(I)" not in acl  # Native utility output is OEM bytes, not UTF-8.


def test_session_generator_rejects_samples_that_fail_startup_policy(monkeypatch, production_values):
    samples = iter(("a" * 128, "0123456789abcdef" * 8))
    monkeypatch.setattr("scripts.rotate_keys.secrets.token_hex", lambda size: next(samples))
    generated = generate_session_secret()
    assert generated == "0123456789abcdef" * 8
    assert (
        Settings(**{**production_values, "SESSION_SECRET_KEY": generated}).ENVIRONMENT
        == "production"
    )


def test_totp_rotation_drill_preserves_plaintext_and_timestamp():
    old, new = Fernet.generate_key(), Fernet.generate_key()
    cipher = Fernet(old).encrypt_at_time(b"SYNTHETIC_BASE32", 1234567890).decode()
    rotated = rotate_ciphertexts([cipher], old, new)[0].encode()
    assert Fernet(new).decrypt(rotated) == b"SYNTHETIC_BASE32"
    assert Fernet(new).extract_timestamp(rotated) == 1234567890
    with pytest.raises(InvalidToken):
        Fernet(old).decrypt(rotated)
    with pytest.raises(InvalidToken):
        rotate_ciphertexts([cipher, "broken"], old, new)


@pytest.mark.asyncio
async def test_session_key_rotation_invalidates_previous_csrf(production_values):
    old_settings = Settings(**production_values)
    new_settings = Settings(
        **{**production_values, "SESSION_SECRET_KEY": generate_session_secret()}
    )
    identity = uuid.uuid4()
    old_proof = generate_csrf_token(identity, old_settings)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/synthetic",
            "headers": [(b"x-csrf-token", old_proof.encode())],
        }
    )
    from app.models.session import Session

    session = Session(id=identity)
    with pytest.raises(HTTPException) as failure:
        await verify_csrf(request, session, new_settings)
    assert failure.value.status_code == 403
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/synthetic",
            "headers": [(b"x-csrf-token", generate_csrf_token(identity, new_settings).encode())],
        }
    )
    await verify_csrf(request, session, new_settings)


@pytest.mark.parametrize(
    "overrides",
    [
        {"JWT_PREVIOUS_KEY_ID": "previous"},
        {"JWT_PREVIOUS_KEY_VALID_UNTIL": datetime.now(timezone.utc)},
        {"JWT_PREVIOUS_KEY_VALID_UNTIL": datetime.now()},
    ],
)
def test_incomplete_overlap_refused(production_values, overrides):
    with pytest.raises(ValidationError):
        Settings(**{**production_values, **overrides})
