from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from typing import Any
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import jwt
from app.config import get_settings

settings = get_settings()

# Инициализация Argon2id с параметрами RFC 9106
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Хеширует пароль алгоритмом Argon2id с индивидуальной солью."""
    if len(password) < 8 or len(password) > 128:
        raise ValueError("Длина пароля должна быть от 8 до 128 символов")
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль с постоянным временем выполнения."""
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, Exception):
        return False


def needs_rehash(hashed_password: str) -> bool:
    """Определяет, требуется ли повторное хеширование при изменении параметров."""
    return _password_hasher.check_needs_rehash(hashed_password)


def hash_token(token: str) -> str:
    """Вычисляет SHA-256 хеш строки для безопасного хранения одноразовых секретов в БД."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_random_token(bytes_count: int = 32) -> str:
    """Генерирует криптографически стойкую строку случайных байт (URL-safe)."""
    return secrets.token_urlsafe(bytes_count)


# --- Шифрование TOTP секретов через Fernet (AES-128-CBC + HMAC-SHA256) ---

def _get_fernet() -> Fernet:
    key = settings.TOTP_ENCRYPTION_KEY.encode("utf-8")
    return Fernet(key)


def encrypt_totp_secret(secret_base32: str) -> str:
    """Шифрует TOTP секрет для безопасного хранения в БД."""
    f = _get_fernet()
    return f.encrypt(secret_base32.encode("utf-8")).decode("utf-8")


def decrypt_totp_secret(encrypted_secret: str) -> str:
    """Расшифровывает TOTP секрет в памяти."""
    f = _get_fernet()
    return f.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")


# --- Управление ключами асимметричной подписи RSA для OIDC ---

_cached_private_key: rsa.RSAPrivateKey | None = None


def get_rsa_private_key() -> rsa.RSAPrivateKey:
    """Возвращает приватный ключ RSA 2048 для подписи токенов."""
    global _cached_private_key
    if _cached_private_key is not None:
        return _cached_private_key

    pem_str = settings.JWT_PRIVATE_KEY_PEM.strip()
    if pem_str:
        if os.path.exists(pem_str):
            with open(pem_str, "rb") as f:
                pem_data = f.read()
        else:
            pem_data = pem_str.encode("utf-8")
        _cached_private_key = serialization.load_pem_private_key(pem_data, password=None)
    else:
        # Автоматическая генерация ключа для dev/test окружения
        _cached_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
    return _cached_private_key


def get_rsa_public_key() -> rsa.RSAPublicKey:
    return get_rsa_private_key().public_key()


def get_jwks() -> dict[str, Any]:
    """Экспортирует публичный ключ RSA в формате JWKS (RFC 7517)."""
    pub_key = get_rsa_public_key()
    numbers = pub_key.public_numbers()

    def _to_base64url_uint(val: int) -> str:
        data = val.to_bytes((val.bit_length() + 7) // 8, byteorder="big")
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": settings.JWT_KEY_ID,
                "n": _to_base64url_uint(numbers.n),
                "e": _to_base64url_uint(numbers.e),
            }
        ]
    }


def create_jwt(payload: dict[str, Any], expires_in_seconds: int) -> str:
    """Создаёт подписанный JWT токен (RS256) с kid в заголовке."""
    now = int(time.time())
    full_payload = {
        **payload,
        "iat": now,
        "nbf": now,
        "exp": now + expires_in_seconds,
        "iss": settings.OIDC_ISSUER,
    }
    private_key = get_rsa_private_key()
    return jwt.encode(
        full_payload,
        private_key,
        algorithm="RS256",
        headers={"kid": settings.JWT_KEY_ID},
    )


def decode_jwt(
    token: str,
    audience: str | None = None,
    verify_exp: bool = True,
) -> dict[str, Any]:
    """Декодирует и проверяет подпись JWT токена с использованием публичного RSA-ключа."""
    pub_key = get_rsa_public_key()
    options = {"verify_exp": verify_exp}
    kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
        "issuer": settings.OIDC_ISSUER,
        "options": options,
    }
    if audience is not None:
        kwargs["audience"] = audience
    else:
        options["verify_aud"] = False

    return jwt.decode(token, pub_key, **kwargs)


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """
    Проверяет PKCE S256 (RFC 7636).
    code_challenge = BASE64URL-ENCODE(SHA256(ASCII(code_verifier)))
    """
    if method != "S256":
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return secrets.compare_digest(expected, code_challenge)
