from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.config import get_settings
from app.core.exceptions import OAuthErrorException
from app.core.key_material import load_private_key, load_public_key, validate_key_id
from app.core.token_profiles import validate_claims

settings = get_settings()

# Инициализация Argon2id с параметрами RFC 9106
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)
_dummy_password_hash = _password_hasher.hash(secrets.token_urlsafe(32))
_password_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="argon2")
_password_capacity = threading.BoundedSemaphore(4)
_Result = TypeVar("_Result")
_common_passwords = frozenset(
    (Path(__file__).resolve().parents[1] / "data" / "common-passwords.txt")
    .read_text(encoding="utf-8")
    .splitlines()
)


async def password_work(operation: Callable[..., _Result], *arguments: Any) -> _Result:
    if not _password_capacity.acquire(blocking=False):
        raise HTTPException(
            503, detail={"error": "authentication_busy", "detail": "Повторите позже"}
        )

    def execute() -> _Result:
        try:
            return operation(*arguments)
        finally:
            _password_capacity.release()

    # Shield keeps the capacity reserved until the actual worker completes even
    # if the request disconnects; cancellation cannot create an unbounded queue.
    loop = asyncio.get_running_loop()
    try:
        future = loop.run_in_executor(_password_executor, execute)
    except BaseException:
        _password_capacity.release()
        raise
    return await asyncio.shield(future)


async def async_hash_password(password: str) -> str:
    return await password_work(hash_password, password)


async def async_rehash_password(password: str) -> str:
    """Rehash an already verified legacy password without changing its policy."""
    return await password_work(_password_hasher.hash, password)


async def async_verify_password(password: str, encoded: str | None) -> bool:
    return await password_work(verify_password, password, encoded or _dummy_password_hash)


def hash_password(password: str) -> str:
    """Хеширует пароль алгоритмом Argon2id с индивидуальной солью."""
    validate_new_password(password)
    return _password_hasher.hash(password)


def validate_new_password(password: str) -> str:
    if not 15 <= len(password) <= 128:
        raise ValueError("Длина пароля должна быть от 15 до 128 символов")
    # Deliberately whole-password comparisons; spaces and Unicode are allowed.
    blocked = {
        "passwordpassword",
        "password123456789",
        "123456789012345",
        "1234567890123456",
        "qwertyuiopasdfgh",
        "letmeinletmeinletmein",
        "correcthorsebatterystaple",
        "парольпарольпароль",
        "alxprgsalxprgsalxprgs",
        "iloveyouiloveyou",
    }
    if password.casefold() in blocked | _common_passwords or len(set(password)) == 1:
        raise ValueError("Этот пароль слишком распространён; выберите другой")
    return password


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
        _retired_public_keys[prev_kid] = load_public_key(prev_pem)


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
        _cached_private_key = load_private_key(pem_str)
    else:
        if settings.ENVIRONMENT == "production":
            raise ValueError("Production cannot generate ephemeral RSA signing keys")
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

    if settings.ENVIRONMENT == "production":
        raise ValueError(
            "Production RSA rotation requires persistent configuration and worker restart"
        )
    if new_kid is not None:
        validate_key_id(new_kid)
        if new_kid == _active_key_id or new_kid in _retired_public_keys:
            raise ValueError("Signing key identifiers cannot be reused")

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


def _expire_retired_keys() -> None:
    deadline = settings.JWT_PREVIOUS_KEY_VALID_UNTIL
    if deadline is not None and datetime.now(timezone.utc) >= deadline:
        retire_key(settings.JWT_PREVIOUS_KEY_ID)


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
    _expire_retired_keys()
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


def _decode_signed_jwt(
    token: str,
    audience: str | None = None,
    verify_exp: bool = True,
) -> dict[str, Any]:
    """
    Декодирует и проверяет подпись JWT токена с использованием kid из заголовка (SSO-06).
    Поддерживает валидацию токенов как активным, так и retired ключами периода перекрытия.
    При неизвестном kid отклоняет токен с ошибкой 401 invalid_token.
    """
    if not isinstance(token, str) or len(token) > 16384:
        raise OAuthErrorException("invalid_token", "Некорректный размер JWT", 401)
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception:
        raise OAuthErrorException("invalid_token", "Некорректный заголовок JWT", 401) from None

    kid = unverified_header.get("kid")
    if unverified_header.get("alg") != "RS256":
        raise OAuthErrorException("invalid_token", "Недопустимый алгоритм JWT", 401)
    if not isinstance(kid, str) or not 1 <= len(kid) <= 128:
        raise OAuthErrorException("invalid_token", "Некорректный идентификатор ключа", 401)
    _expire_retired_keys()
    pub_key: rsa.RSAPublicKey | None = None

    if kid == get_active_key_id():
        pub_key = get_rsa_public_key()
    elif kid in _retired_public_keys:
        pub_key = _retired_public_keys[kid]
    else:
        raise OAuthErrorException(
            "invalid_token", "Неизвестный идентификатор ключа подписи (kid)", 401
        )

    options: dict[str, Any] = {"verify_exp": verify_exp, "require": ["iss", "sub", "exp", "iat"]}
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
        payload = jwt.decode(token, pub_key, **kwargs)
        return payload
    except jwt.ExpiredSignatureError:
        raise OAuthErrorException("invalid_token", "Срок действия токена истёк", 401) from None
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise OAuthErrorException(
            "invalid_token", "Недействительная подпись или атрибуты токена", 401
        ) from None


def decode_jwt(
    token: str, audience: str | None = None, expected_use: str | None = None
) -> dict[str, Any]:
    payload = _decode_signed_jwt(token, audience=audience)
    try:
        validate_claims(payload, audience, expected_use)
    except (ValueError, TypeError):
        raise OAuthErrorException("invalid_token", "Некорректные атрибуты токена", 401) from None
    return payload


def decode_logout_hint(token: str) -> tuple[dict[str, Any], str]:
    """Expiration exception only for logout; caller must bind an expired hint to a live session."""
    payload = _decode_signed_jwt(token, verify_exp=False)
    aud = payload.get("aud")
    client_id = aud if isinstance(aud, str) else payload.get("azp")
    try:
        if not isinstance(client_id, str) or (isinstance(aud, list) and client_id not in aud):
            raise ValueError("Invalid logout client")
        validate_claims(payload, client_id, "id_token")
    except (ValueError, TypeError):
        raise OAuthErrorException(
            "invalid_token", "Некорректный ID Token для выхода", 401
        ) from None
    return payload, client_id


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """
    Проверяет PKCE S256 (RFC 7636) с использованием Authlib.
    """
    if (
        method != "S256"
        or not isinstance(code_verifier, str)
        or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", code_verifier)
        or not valid_pkce_challenge(code_challenge)
    ):
        return False
    expected = create_s256_code_challenge(code_verifier)
    return secrets.compare_digest(expected, code_challenge)


def valid_pkce_challenge(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is not None
