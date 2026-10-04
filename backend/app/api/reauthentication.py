from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_current_user, verify_csrf
from app.config import Settings, get_settings
from app.database import get_db
from app.models.session import Session
from app.models.user import User
from app.services import reauthentication_service as service

router = APIRouter(
    prefix="/api/v1/auth/reauthentication",
    tags=["Authentication"],
    dependencies=[Depends(verify_csrf)],
)


class StartRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=255)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FactorRequest(BaseModel):
    authorization: str = Field(min_length=1, max_length=256)
    method: str = Field(pattern=r"^(totp|recovery_code|passkey)$")
    code: str | None = Field(default=None, max_length=128)
    credential: dict[str, Any] | None = None


@router.post("")
async def start(
    payload: StartRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return await service.start(
        db, user, session, settings, payload.current_password, payload.action, payload.payload_hash
    )


@router.post("/factor")
async def factor(
    payload: FactorRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return await service.confirm(
        db,
        user,
        session,
        settings,
        payload.authorization,
        payload.method,
        payload.code,
        payload.credential,
    )
