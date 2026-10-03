"""Public legal documents and authenticated privacy controls."""

from typing import Any, Literal
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import (
    generate_csrf_token,
    get_cookie_name,
    get_current_session,
    get_current_user,
    verify_csrf,
)
from app.config import Settings, get_settings
from app.database import get_db
from app.legal import DOCUMENTS, REQUIRED_DOCUMENTS
from app.models.session import Session
from app.models.user import User
from app.services import privacy_service as privacy

router = APIRouter(tags=["Privacy"])


class AcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terms_accepted: Literal[True]
    data_processing_consent: Literal[True]
    legal_versions: dict[str, str]

    @field_validator("terms_accepted", "data_processing_consent", mode="before")
    @classmethod
    def explicit_consent(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("Требуется явное согласие")
        return value


class ReauthenticationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["request", "cancel"]
    current_password: str = Field(min_length=1, max_length=128)


class FactorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["request", "cancel"]
    authorization: str = Field(min_length=32, max_length=128)
    method: Literal["totp", "recovery_code", "passkey"]
    code: str | None = Field(default=None, max_length=128)
    credential: dict[str, Any] | None = None


class AuthorizedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorization: str = Field(min_length=32, max_length=128)


@router.get("/api/v1/legal/documents")
async def documents(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-cache"
    return {"documents": DOCUMENTS, "required_versions": REQUIRED_DOCUMENTS}


@router.post("/api/v1/auth/legal-acceptance", dependencies=[Depends(verify_csrf)])
async def accept_documents(
    payload: AcceptanceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    from sqlalchemy import select

    current = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not current or not current.is_active:
        raise privacy.rejection("invalid_credentials", "Аккаунт недоступен.", 401)
    if current.deletion_scheduled_for:
        raise privacy.rejection(
            "account_deletion_pending", "Доступно только управление удалением.", 403
        )
    await privacy.record_acceptance(
        db, user.id, payload.legal_versions, await privacy.database_now(db)
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/api/v1/auth/account-deletion")
async def deletion_status(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return privacy.deletion_status(user)


@router.post("/api/v1/auth/account-deletion/reauthenticate", dependencies=[Depends(verify_csrf)])
async def reauthenticate(
    payload: ReauthenticationRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return await privacy.start_reauthentication(
        db, user, session, settings, payload.action, payload.current_password
    )


@router.post("/api/v1/auth/account-deletion/confirm-factor", dependencies=[Depends(verify_csrf)])
async def confirm_factor(
    payload: FactorRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return await privacy.confirm_factor(
        db,
        user,
        session,
        settings,
        payload.authorization,
        payload.action,
        payload.method,
        payload.code,
        payload.credential,
    )


@router.post("/api/v1/auth/account-deletion", status_code=202, dependencies=[Depends(verify_csrf)])
async def request_deletion(
    payload: AuthorizedRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    result, raw = await privacy.request_deletion(db, user, session, payload.authorization)
    response.set_cookie(
        get_cookie_name(settings, request),
        raw,
        httponly=True,
        secure=request.url.scheme == "https" or settings.ENVIRONMENT == "production",
        samesite="lax",
        path="/",
        max_age=3600,
    )
    # Re-read the new limited session to bind the next CSRF proof to its ID.
    from sqlalchemy import select
    from app.core.security import hash_token

    replacement = await db.scalar(
        select(Session).where(Session.session_token_hash == hash_token(raw))
    )
    if replacement is None:
        raise privacy.rejection("service_unavailable", "Сессия управления недоступна.", 503)
    response.headers["X-CSRF-Token"] = generate_csrf_token(replacement.id, settings)
    return result


@router.delete("/api/v1/auth/account-deletion", dependencies=[Depends(verify_csrf)])
async def cancel_deletion(
    payload: AuthorizedRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    result = await privacy.cancel_deletion(db, user, session, payload.authorization)
    response.delete_cookie(get_cookie_name(settings, request), path="/")
    return result
