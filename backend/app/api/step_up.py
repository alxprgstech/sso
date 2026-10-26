"""Cross-application transaction step-up endpoints.

Browser endpoints use the existing host-only SSO session and CSRF protection.
Server-to-server endpoints use the same confidential-client authentication as
the OIDC token endpoint; no client secret or proof is accepted from the browser
for those operations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_current_user, require_feature, verify_csrf
from app.config import Settings, get_settings
from app.core.client_auth import extract_client_credentials
from app.core.rate_limit import get_client_ip
from app.database import get_db
from app.models.session import Session
from app.models.user import User
from app.schemas.step_up import (
    StepUpDenyResponse,
    StepUpDetailsResponse,
    StepUpPasskeyOptionsRequest,
    StepUpProofResponse,
    StepUpRedeemRequest,
    StepUpRequestCreate,
    StepUpRequestResponse,
    StepUpVerifyRequest,
    StepUpVerifyResponse,
)
from app.services import step_up_service
from app.services.oidc_service import OIDCService

router = APIRouter(
    prefix="/api/v1/step-up",
    tags=["Transaction Step-Up"],
    dependencies=[Depends(require_feature("FEATURE_EXTERNAL_STEP_UP_ENABLED"))],
)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


async def _authenticated_actor(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_current_session),
) -> tuple[User, Session]:
    return user, session


async def _client(request: Request, db: AsyncSession):
    client_id, client_secret = extract_client_credentials(request)
    return await OIDCService.get_and_validate_client(
        db, client_id, client_secret, require_secret=True
    )


@router.post("/requests", response_model=StepUpRequestResponse, status_code=201)
async def create_request(
    payload: StepUpRequestCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StepUpRequestResponse:
    _no_store(response)
    client = await _client(request, db)
    result = await step_up_service.create_request(
        db,
        client,
        payload,
        settings,
        ip_address=get_client_ip(request, settings.TRUSTED_PROXIES),
    )
    return StepUpRequestResponse(**result)


@router.get("/requests/{request_token}", response_model=StepUpDetailsResponse)
async def request_details(
    response: Response,
    request_token: str = Path(..., min_length=16, max_length=128),
    actor: tuple[User, Session] = Depends(_authenticated_actor),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StepUpDetailsResponse:
    _no_store(response)
    user, session = actor
    return StepUpDetailsResponse(
        **await step_up_service.details(db, user, session, request_token, settings)
    )


@router.post(
    "/requests/{request_token}/passkey/options",
    dependencies=[Depends(verify_csrf)],
)
async def passkey_options(
    payload: StepUpPasskeyOptionsRequest,
    response: Response,
    request_token: str = Path(..., min_length=16, max_length=128),
    actor: tuple[User, Session] = Depends(_authenticated_actor),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _no_store(response)
    user, session = actor
    return await step_up_service.passkey_options(
        db, user, session, request_token, payload.plan, settings
    )


@router.post(
    "/requests/{request_token}/verify",
    response_model=StepUpVerifyResponse,
    dependencies=[Depends(verify_csrf)],
)
async def verify(
    payload: StepUpVerifyRequest,
    response: Response,
    request_token: str = Path(..., min_length=16, max_length=128),
    actor: tuple[User, Session] = Depends(_authenticated_actor),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StepUpVerifyResponse:
    _no_store(response)
    user, session = actor
    return StepUpVerifyResponse(
        **await step_up_service.verify(
            db,
            user,
            session,
            request_token,
            payload.plan,
            payload.method,
            settings,
            password=payload.password,
            code=payload.code,
            credential=payload.credential,
        )
    )


@router.post(
    "/requests/{request_token}/deny",
    response_model=StepUpDenyResponse,
    dependencies=[Depends(verify_csrf)],
)
async def deny(
    response: Response,
    request_token: str = Path(..., min_length=16, max_length=128),
    actor: tuple[User, Session] = Depends(_authenticated_actor),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StepUpDenyResponse:
    _no_store(response)
    user, session = actor
    await step_up_service.deny(db, user, session, request_token, settings)
    return StepUpDenyResponse(status="denied")


@router.post("/redeem", response_model=StepUpProofResponse)
async def redeem(
    payload: StepUpRedeemRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StepUpProofResponse:
    _no_store(response)
    client = await _client(request, db)
    result = await step_up_service.redeem(
        db,
        client,
        payload.code,
        payload.code_verifier,
        payload.redirect_uri,
        settings,
        ip_address=get_client_ip(request, settings.TRUSTED_PROXIES),
    )
    return StepUpProofResponse(**result)
