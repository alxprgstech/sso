import os
import sys
import uuid

sys.path.insert(0, os.path.abspath("backend"))

from app.api.deps import generate_csrf_token
from app.config import get_settings
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_capabilities_default_off():
    """Проверка витрины возможностей: все 4 фичи выключены по умолчанию (SEC-FLAG-01)."""
    res = client.get("/api/v1/auth/capabilities")
    assert res.status_code == 200
    data = res.json()
    assert data["totp_enabled"] is False
    assert data["passkey_enabled"] is False
    assert data["recovery_codes_enabled"] is False
    assert data["email_verification_enabled"] is False
    assert data["require_verified_email"] is False


def test_unauthenticated_me():
    """Запрос без сессионной cookie возвращает 401."""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert res.json()["error"] == "invalid_credentials"


def test_csrf_token_validation():
    """Проверка генерации и валидации CSRF-токена."""
    settings = get_settings()
    session_id = uuid.uuid4()
    csrf_token = generate_csrf_token(session_id, settings)
    assert isinstance(csrf_token, str)
    assert len(csrf_token) == 64

    # Другая сессия имеет другой токен
    other_session_id = uuid.uuid4()
    other_token = generate_csrf_token(other_session_id, settings)
    assert csrf_token != other_token


if __name__ == "__main__":
    test_capabilities_default_off()
    test_unauthenticated_me()
    test_csrf_token_validation()
    print("ALL AUTH & SESSIONS TESTS PASSED!")
