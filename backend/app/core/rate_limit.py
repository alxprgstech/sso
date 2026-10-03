from __future__ import annotations

import ipaddress
import time
from collections import defaultdict
from typing import Dict, List, Sequence
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings

# Внутрипроцессный фильтр скользящего окна (защита от исчерпания CPU быстрым флудом)
_IN_MEMORY_REQUESTS: Dict[str, List[float]] = defaultdict(list)
IN_MEMORY_MAX_REQUESTS = 10
IN_MEMORY_WINDOW_SECONDS = 10

# Межпроцессный лимит через PostgreSQL (REG-07)
DB_MAX_ATTEMPTS_PER_WINDOW = 5
DB_WINDOW_SECONDS = 60

# Межпроцессный лимит подтверждения email (G4-EMAIL, SEC-FLAG-07)
DB_EMAIL_MAX_ATTEMPTS = 3
DB_EMAIL_WINDOW_SECONDS = 60


def is_ip_in_network(ip_str: str, network_or_ip: str) -> bool:
    """Проверка принадлежности IP к указанному адресу или CIDR-подсети."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if "/" in network_or_ip:
            net = ipaddress.ip_network(network_or_ip, strict=False)
            return ip in net
        else:
            trusted_ip = ipaddress.ip_address(network_or_ip)
            return ip == trusted_ip
    except ValueError:
        return False


def is_trusted_proxy(client_ip: str, trusted_proxies: Sequence[str]) -> bool:
    """Проверка, является ли непосредственный peer доверенным прокси."""
    for trusted in trusted_proxies:
        if is_ip_in_network(client_ip, trusted):
            return True
    return False


def get_client_ip(request: Request, trusted_proxies: Sequence[str] | None = None) -> str:
    """
    Извлечение IP клиента с валидацией доверенных proxy (G4-LIMITS, ARCH-04, SEC-PROX-01).
    Заголовки X-Forwarded-For и X-Real-IP учитываются ТОЛЬКО если непосредственный peer
    входит в список доверенных proxy (TRUSTED_PROXIES).
    Любые попытки подделки заголовков от недоверенных клиентов игнорируются.
    """
    if trusted_proxies is None:
        try:
            trusted_proxies = get_settings().TRUSTED_PROXIES
        except Exception:
            trusted_proxies = ["127.0.0.1", "::1"]

    peer_ip = request.client.host if request.client else "127.0.0.1"

    # Если непосредственный отправитель НЕ доверенный прокси, игнорируем любые форвардинг-заголовки
    if not is_trusted_proxy(peer_ip, trusted_proxies):
        return peer_ip

    # Если отправитель доверен, извлекаем реальный клиентский IP из X-Forwarded-For
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # X-Forwarded-For содержит цепочку: client, proxy1, proxy2
        # Берём первый IP (клиентский)
        client_candidate = xff.split(",")[0].strip()
        try:
            ipaddress.ip_address(client_candidate)
            return client_candidate
        except ValueError:
            pass

    x_real = request.headers.get("X-Real-IP")
    if x_real:
        client_candidate = x_real.strip()
        try:
            ipaddress.ip_address(client_candidate)
            return client_candidate
        except ValueError:
            pass

    return peer_ip


def check_in_memory_rate_limit(ip: str) -> None:
    now = time.time()
    timestamps = _IN_MEMORY_REQUESTS[ip]
    # Очищаем устаревшие метки
    _IN_MEMORY_REQUESTS[ip] = [ts for ts in timestamps if now - ts < IN_MEMORY_WINDOW_SECONDS]
    if len(_IN_MEMORY_REQUESTS[ip]) >= IN_MEMORY_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "detail": "Слишком много запросов. Пожалуйста, повторите позже.",
            },
        )
    _IN_MEMORY_REQUESTS[ip].append(now)


async def check_registration_rate_limit(db: AsyncSession, ip: str) -> None:
    """
    Межпроцессное ограничение частоты регистрации через PostgreSQL (REG-07, G4-LIMITS).
    Fail-closed: при сбое БД регистрация блокируется безопасным образом (HTTP 503 Service Unavailable).
    """
    check_in_memory_rate_limit(ip)

    from app.services.privacy_service import RateLimit, consume_rate_limit

    await consume_rate_limit(
        db,
        get_settings(),
        RateLimit("registration", ip, DB_MAX_ATTEMPTS_PER_WINDOW, DB_WINDOW_SECONDS),
    )


async def check_email_request_rate_limit(db: AsyncSession, ip: str) -> None:
    """
    Межпроцессное ограничение частоты запросов подтверждения email (G4-EMAIL, SEC-FLAG-07, G4-LIMITS).
    Fail-closed: при сбое БД запросы блокируются безопасным образом (HTTP 503 Service Unavailable).
    """
    check_in_memory_rate_limit(f"email_req_{ip}")

    from app.services.privacy_service import RateLimit, consume_rate_limit

    await consume_rate_limit(
        db, get_settings(), RateLimit("email", ip, DB_EMAIL_MAX_ATTEMPTS, DB_EMAIL_WINDOW_SECONDS)
    )
