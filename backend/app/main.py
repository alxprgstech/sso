from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uuid
from contextlib import asynccontextmanager
from typing import Any
from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.mfa import router as mfa_router
from app.api.oidc import router as oidc_router
from app.config import get_settings
from app.core.exceptions import (
    AuthenticationException,
    AuthorizationException,
    FeatureDisabledException,
    OAuthErrorException,
)
from app.core.security import get_jwks
from app.database import get_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Действия при запуске приложения
    yield
    # Действия при остановке приложения


app = FastAPI(
    title="ALXPRGS SSO",
    description="Identity and Access Management Server for alxprgs.tech",
    version="0.1.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Настройка CORS для доверенных клиентских приложений
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:5173",
        "http://localhost:3000",
        "https://auth.alxprgs.tech",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-CSRF-Token"],
)


@app.middleware("http")
async def correlation_id_and_security_headers_middleware(request: Request, call_next):
    """
    Middleware:
    1. Назначает correlation ID (X-Request-ID) для каждого запроса (Section 4.6 GOAL.md).
    2. Устанавливает базовые заголовки безопасности (Content-Security-Policy, nosniff, etc.).
    """
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    response: Response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# --- Обработчики исключений безопасности ---


@app.exception_handler(FeatureDisabledException)
async def feature_disabled_exception_handler(request: Request, exc: FeatureDisabledException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


@app.exception_handler(AuthenticationException)
async def authentication_exception_handler(request: Request, exc: AuthenticationException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


@app.exception_handler(AuthorizationException)
async def authorization_exception_handler(request: Request, exc: AuthorizationException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


@app.exception_handler(OAuthErrorException)
async def oauth_error_exception_handler(request: Request, exc: OAuthErrorException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


# --- Системные эндпоинты Health / Readiness (Section 4.6) ---


@app.get("/health/live", tags=["Health"])
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"])
async def health_ready(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    try:
        await db.execute(text("SELECT 1"))
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ready", "database": "connected"},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "database": "disconnected", "detail": str(e)},
        )


# --- OpenID Connect Discovery & JWKS (SSO-01, SSO-06) ---


@app.get("/.well-known/openid-configuration", tags=["OIDC"])
async def oidc_configuration() -> dict[str, Any]:
    issuer = settings.OIDC_ISSUER
    base_url = settings.BASE_URL
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "userinfo_endpoint": f"{base_url}/oauth/userinfo",
        "jwks_uri": f"{base_url}/.well-known/jwks.json",
        "revocation_endpoint": f"{base_url}/oauth/revoke",
        "end_session_endpoint": f"{base_url}/oauth/logout",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile", "email"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "none",
        ],
        "claims_supported": [
            "sub",
            "iss",
            "aud",
            "exp",
            "iat",
            "nonce",
            "preferred_username",
            "email",
            "email_verified",
            "roles",
        ],
        "code_challenge_methods_supported": ["S256"],
    }


@app.get("/.well-known/jwks.json", tags=["OIDC"])
async def oidc_jwks() -> dict[str, Any]:
    return get_jwks()


# Подключение роутеров приложения
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(mfa_router)
app.include_router(oidc_router)
