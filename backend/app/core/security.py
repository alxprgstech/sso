from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from typing import Any
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from app.config import get_settings
from app.core.exceptions import OAuthErrorException

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


# --- Управление ключами асимметричной подписи RSA для OIDC (SSO-06) ---

_active_key_id: str = settings.JWT_KEY_ID
_cached_private_key: rsa.RSAPrivateKey | None = None
_retired_public_keys: dict[str, rsa.RSAPublicKey] = {}


def _init_retired_keys() -> None:
    global _retired_public_keys
    prev_pem = settings.JWT_PREVIOUS_PUBLIC_KEY_PEM.strip()
    prev_kid = settings.JWT_PREVIOUS_KEY_ID.strip()
    if prev_pem and prev_kid:
        if os.path.exists(prev_pem):
            with open(prev_pem, "rb") as f:
                pem_data = f.read()
        else:
            pem_data = prev_pem.encode("utf-8")
        pub_key = serialization.load_pem_public_key(pem_data)
        if isinstance(pub_key, rsa.RSAPublicKey):
            _retired_public_keys[prev_kid] = pub_key


_init_retired_keys()


def get_active_key_id() -> str:
    global _active_key_id
    return _active_key_id


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
        loaded_key = serialization.load_pem_private_key(pem_data, password=None)
        if not isinstance(loaded_key, rsa.RSAPrivateKey):
            raise ValueError("JWT_PRIVATE_KEY_PEM must be an RSA private key")
        _cached_private_key = loaded_key
    else:
        # Автоматическая генерация ключа для dev/test окружения
        _cached_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
    assert _cached_private_key is not None
    return _cached_private_key


def get_rsa_public_key() -> rsa.RSAPublicKey:
    return get_rsa_private_key().public_key()


def rotate_active_signing_key(
    new_kid: str | None = None,
    new_private_key: rsa.RSAPrivateKey | None = None,
) -> str:
    """
    Выполняет ротацию ключа подписи токенов (SSO-06).
    Текущий активный публичный ключ перемещается в словарь retired для периода перекрытия.
    Генерируется или устанавливается новый активный ключ подписи с новым kid.
    """
    global _active_key_id, _cached_private_key, _retired_public_keys

    # Сохраняем текущий публичный ключ в retired
    current_pub = get_rsa_public_key()
    _retired_public_keys[_active_key_id] = current_pub

    # Устанавливаем новый ключ
    _active_key_id = new_kid or f"rsa-key-{int(time.time())}"
    if new_private_key is not None:
        _cached_private_key = new_private_key
    else:
        _cached_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
    return _active_key_id


def retire_key(kid: str) -> None:
    """Удаляет устаревший публичный ключ после завершения периода перекрытия."""
    global _retired_public_keys
    _retired_public_keys.pop(kid, None)


def _rsa_pub_to_jwk(pub_key: rsa.RSAPublicKey, kid: str) -> dict[str, Any]:
    numbers = pub_key.public_numbers()

    def _to_base64url_uint(val: int) -> str:
        data = val.to_bytes((val.bit_length() + 7) // 8, byteorder="big")
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _to_base64url_uint(numbers.n),
        "e": _to_base64url_uint(numbers.e),
    }


def get_jwks() -> dict[str, Any]:
    """Экспортирует активный и все непросроченные публичные ключи RSA в формате JWKS (RFC 7517, SSO-06)."""
    keys = [_rsa_pub_to_jwk(get_rsa_public_key(), get_active_key_id())]
    for kid, pub in _retired_public_keys.items():
        keys.append(_rsa_pub_to_jwk(pub, kid))
    return {"keys": keys}


def create_jwt(payload: dict[str, Any], expires_in_seconds: int) -> str:
    """Создаёт подписанный JWT токен (RS256) с актуальным kid в заголовке."""
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
        headers={"kid": get_active_key_id()},
    )


def decode_jwt(
    token: str,
    audience: str | None = None,
    verify_exp: bool = True,
) -> dict[str, Any]:
    """
    Декодирует и проверяет подпись JWT токена с использованием kid из заголовка (SSO-06).
    Поддерживает валидацию токенов как активным, так и retired ключами периода перекрытия.
    При неизвестном kid отклоняет токен с ошибкой 401 invalid_token.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception:
        raise OAuthErrorException("invalid_token", "Некорректный заголовок JWT", 401) from None

    kid = unverified_header.get("kid")
    pub_key: rsa.RSAPublicKey | None = None

    if kid is None or kid == get_active_key_id():
        pub_key = get_rsa_public_key()
    elif kid in _retired_public_keys:
        pub_key = _retired_public_keys[kid]
    else:
        raise OAuthErrorException(
            "invalid_token", "Неизвестный идентификатор ключа подписи (kid)", 401
        )

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

    try:
        return jwt.decode(token, pub_key, **kwargs)
    except jwt.ExpiredSignatureError:
        raise OAuthErrorException("invalid_token", "Срок действия токена истёк", 401) from None
    except jwt.InvalidTokenError:
        raise OAuthErrorException(
            "invalid_token", "Недействительная подпись или атрибуты токена", 401
        ) from None


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """
    Проверяет PKCE S256 (RFC 7636) с использованием Authlib.
    """
    if method != "S256":
        return False
    expected = create_s256_code_challenge(code_verifier)
    return secrets.compare_digest(expected, code_challenge)
