from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditEvent

# Внутрипроцессный фильтр скользящего окна (защита от исчерпания CPU быстрым флудом)
_IN_MEMORY_REQUESTS: Dict[str, List[float]] = defaultdict(list)
IN_MEMORY_MAX_REQUESTS = 10
IN_MEMORY_WINDOW_SECONDS = 10

# Межпроцессный лимит через PostgreSQL (REG-07)
DB_MAX_ATTEMPTS_PER_WINDOW = 5
DB_WINDOW_SECONDS = 60


def get_client_ip(request: Request) -> str:
    """Извлечение IP с учетом доверенных proxy-заголовков (Nginx)."""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    x_real = request.headers.get("X-Real-IP")
    if x_real:
        return x_real.strip()
    if request.client:
        return request.client.host
    return "127.0.0.1"


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
    Межпроцессное ограничение частоты регистрации через PostgreSQL (REG-07).
    """
    check_in_memory_rate_limit(ip)

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=DB_WINDOW_SECONDS)
    stmt = select(func.count(AuditEvent.id)).where(
        AuditEvent.event_type.in_(["registration_attempt", "user_registered"]),
        AuditEvent.ip_address == ip,
        AuditEvent.created_at >= cutoff,
    )
    result = await db.execute(stmt)
    count = result.scalar_one_or_none() or 0

    if count >= DB_MAX_ATTEMPTS_PER_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "detail": "Превышен лимит попыток регистрации. Повторите попытку через минуту.",
            },
        )
