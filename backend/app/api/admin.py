from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import require_admin_user, verify_csrf
from app.database import get_db
from app.models.user import User
from app.schemas.admin import (
    AdminAuditEventResponse,
    AdminClientCreateRequest,
    AdminClientResponse,
    AdminUserCreateRequest,
    AdminUserResponse,
    AdminUserUpdateRequest,
    RegistrationModeUpdateRequest,
    SystemStatusResponse,
)
from app.services.admin_service import AdminService
from app.services.system_service import SystemService
from app.core.rate_limit import get_client_ip
from fastapi import Request

router = APIRouter(prefix="/api/v1/admin", tags=["Admin Panel"])


# ==============================================================================
# 1. ПОЛЬЗОВАТЕЛИ (USR-01..03, USR-07, USR-08)
# ==============================================================================


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: str | None = Query(None),
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserResponse]:
    users = await AdminService.list_users(db, offset=offset, limit=limit, search=search)
    return [
        AdminUserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            is_active=u.is_active,
            is_superuser=u.is_superuser,
            email_verified=u.email_verified,
            roles=[r.name for r in u.roles],
            created_at=u.created_at,
            updated_at=u.updated_at,
        )
        for u in users
    ]


@router.post(
    "/users",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
async def create_user(
    payload: AdminUserCreateRequest,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserResponse:
    user = await AdminService.create_user(
        db=db,
        username=payload.username,
        email=payload.email,
        password=payload.password,
        roles=payload.roles,
        is_superuser=payload.is_superuser,
        admin_user_id=admin.id,
    )
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        email_verified=user.email_verified,
        roles=[r.name for r in user.roles],
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserResponse:
    user = await AdminService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        email_verified=user.email_verified,
        roles=[r.name for r in user.roles],
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.patch(
    "/users/{user_id}", response_model=AdminUserResponse, dependencies=[Depends(verify_csrf)]
)
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdateRequest,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserResponse:
    user = await AdminService.update_user(
        db=db,
        user_id=user_id,
        current_admin=admin,
        email=payload.email,
        is_active=payload.is_active,
        is_superuser=payload.is_superuser,
        roles=payload.roles,
        new_password=payload.new_password,
    )
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        email_verified=user.email_verified,
        roles=[r.name for r in user.roles],
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.post("/users/{user_id}/sessions/revoke", dependencies=[Depends(verify_csrf)])
async def revoke_user_sessions(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    count = await AdminService.revoke_all_user_sessions(db, user_id=user_id, admin_user_id=admin.id)
    return {"status": "ok", "revoked_count": count}


# ==============================================================================
# 2. OIDC-КЛИЕНТЫ (USR-09, SSO-02)
# ==============================================================================


@router.get("/clients", response_model=list[AdminClientResponse])
async def list_clients(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[AdminClientResponse]:
    clients = await AdminService.list_clients(db, offset=offset, limit=limit)
    return [
        AdminClientResponse(
            id=c.id,
            client_id=c.client_id,
            client_name=c.client_name,
            client_type=c.client_type,
            is_active=c.is_active,
            redirect_uris=[r.uri for r in c.redirect_uris],
            client_secret=None,  # Секрет никогда не отдается при обычном листинге
            created_at=c.created_at,
        )
        for c in clients
    ]


@router.post(
    "/clients",
    response_model=AdminClientResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
async def create_client(
    payload: AdminClientCreateRequest,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> AdminClientResponse:
    client, raw_secret = await AdminService.create_client(
        db=db,
        client_name=payload.client_name,
        client_type=payload.client_type,
        redirect_uris=payload.redirect_uris,
        admin_user_id=admin.id,
    )
    return AdminClientResponse(
        id=client.id,
        client_id=client.client_id,
        client_name=client.client_name,
        client_type=client.client_type,
        is_active=client.is_active,
        redirect_uris=[r.uri for r in client.redirect_uris],
        client_secret=raw_secret,  # Возвращается ТОЛЬКО ОДИН РАЗ при регистрации
        created_at=client.created_at,
    )


@router.post(
    "/clients/{client_id}/rotate-secret",
    response_model=AdminClientResponse,
    dependencies=[Depends(verify_csrf)],
)
async def rotate_client_secret(
    client_id: str,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> AdminClientResponse:
    client, new_secret = await AdminService.rotate_client_secret(
        db=db,
        client_id=client_id,
        admin_user_id=admin.id,
    )
    return AdminClientResponse(
        id=client.id,
        client_id=client.client_id,
        client_name=client.client_name,
        client_type=client.client_type,
        is_active=client.is_active,
        redirect_uris=[r.uri for r in client.redirect_uris],
        client_secret=new_secret,  # Возвращается ТОЛЬКО ОДИН РАЗ при ротации
        created_at=client.created_at,
    )


@router.delete("/clients/{client_id}", dependencies=[Depends(verify_csrf)])
async def delete_client(
    client_id: str,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    deleted = await AdminService.delete_client(db=db, client_id=client_id, admin_user_id=admin.id)
    if not deleted:
        return {"status": "not_found", "message": "Клиент не найден"}
    return {"status": "ok"}


# ==============================================================================
# 3. АУДИТ (AUDIT-01..03)
# ==============================================================================


@router.get("/audit", response_model=list[AdminAuditEventResponse])
async def list_audit(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user_id: uuid.UUID | None = Query(None),
    event_type: str | None = Query(None),
    q: str | None = Query(None, max_length=128),
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[AdminAuditEventResponse]:
    events = await AdminService.list_audit_events(
        db=db,
        offset=offset,
        limit=limit,
        user_id=user_id,
        event_type=event_type,
        query=q,
    )
    return [
        AdminAuditEventResponse(
            id=e.id,
            event_type=e.event_type,
            user_id=e.user_id,
            ip_address=e.ip_address,
            user_agent=e.user_agent,
            details=e.details or {},
            created_at=e.created_at,
        )
        for e in events
    ]


@router.get("/audit/export")
async def export_audit(
    format: str = Query("jsonl", pattern="^(jsonl|csv)$"),
    user_id: uuid.UUID | None = Query(None),
    event_type: str | None = Query(None),
    q: str | None = Query(None, max_length=128),
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Потоковая выгрузка всего отфильтрованного журнала, доступная администратору."""

    async def rows() -> AsyncIterator[str]:
        stmt = AdminService.audit_statement(user_id=user_id, event_type=event_type, query=q)
        result = await db.stream_scalars(stmt)
        if format == "csv":
            yield "id,event_type,user_id,ip_address,user_agent,details,created_at\r\n"
        async for event in result:
            item = AdminAuditEventResponse.model_validate(event)
            if format == "jsonl":
                yield item.model_dump_json() + "\n"
            else:
                buffer = io.StringIO()
                writer = csv.writer(buffer)

                def safe(value: str) -> str:
                    return (
                        "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
                    )

                writer.writerow(
                    [
                        str(item.id),
                        safe(item.event_type),
                        str(item.user_id) if item.user_id else "",
                        safe(item.ip_address or ""),
                        safe(item.user_agent or ""),
                        json.dumps(item.details, ensure_ascii=False),
                        item.created_at.isoformat(),
                    ]
                )
                yield buffer.getvalue()

    filename = f"alxprgs-audit.{format}"
    media_type = "application/x-ndjson" if format == "jsonl" else "text/csv; charset=utf-8"
    return StreamingResponse(
        rows(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


# ==============================================================================
# 4. СОСТОЯНИЕ СИСТЕМЫ И РЕЖИМ РЕГИСТРАЦИИ (REG-02, SETUP-05)
# ==============================================================================


@router.get("/system/status", response_model=SystemStatusResponse)
async def get_system_status(
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> SystemStatusResponse:
    """Получение текущего среза состояния системы и режима регистрации (REG-02)."""
    config = await SystemService.get_or_create_configuration(db)
    total_users, total_active_admins = await AdminService.system_counts(db)
    return SystemStatusResponse(
        bootstrap_completed=config.bootstrap_completed,
        bootstrap_completed_at=config.bootstrap_completed_at,
        registration_mode=config.registration_mode,
        updated_at=config.updated_at,
        total_users=total_users,
        total_active_admins=total_active_admins,
    )


@router.post(
    "/system/registration-mode",
    response_model=SystemStatusResponse,
    dependencies=[Depends(verify_csrf)],
)
async def update_registration_mode(
    payload: RegistrationModeUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> SystemStatusResponse:
    """
    Переключение режима регистрации (closed / open) с обязательной повторной аутентификацией пароля (REG-02).
    """
    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent")

    config = await SystemService.update_registration_mode(
        db=db,
        admin_user=admin,
        admin_password=payload.current_admin_password,
        new_mode=payload.mode,
        ip_address=ip,
        user_agent=ua,
    )
    total_users, total_active_admins = await AdminService.system_counts(db)
    return SystemStatusResponse(
        bootstrap_completed=config.bootstrap_completed,
        bootstrap_completed_at=config.bootstrap_completed_at,
        registration_mode=config.registration_mode,
        updated_at=config.updated_at,
        total_users=total_users,
        total_active_admins=total_active_admins,
    )
