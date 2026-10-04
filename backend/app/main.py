from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.mfa import router as mfa_router
from app.api.oidc import router as oidc_router
from app.api.privacy import router as privacy_router
from app.api.reauthentication import router as reauthentication_router
from app.build_info import get_build_info
from app.config import get_settings
from app.core.body_limit import BodyLimitMiddleware
from app.core.database_policy import require_runtime_database_role
from app.core.diagnostics import correlation, diagnostic
from app.core.diagnostics import request_id as request_context_id
from app.core.exceptions import (
    AuthenticationException,
    AuthorizationException,
    FeatureDisabledException,
    OAuthErrorException,
)
from app.core.security import get_jwks
from app.database import get_db
from app.logging_config import configure_logging
from app.telemetry import TelemetryFastAPI, initialize_sentry, register_routes

settings = get_settings()
READINESS_DATABASE_TIMEOUT_SECONDS = 2
configure_logging()
initialize_sentry(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from contextlib import suppress

    from app.services.privacy_service import maintenance_loop

    if settings.ENVIRONMENT == "production":
        from app.database import async_session_maker

        try:
            async with async_session_maker() as db:
                await require_runtime_database_role(db)
        except Exception:
            diagnostic("database_readiness", "database_unavailable", failed=True)
            raise RuntimeError(
                "Production database preflight failed; check role and migrations"
            ) from None

    task = asyncio.create_task(maintenance_loop(settings))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    import sentry_sdk

    sentry_sdk.get_client().close(timeout=2)


app = TelemetryFastAPI(
    title="ALXPRGS SSO",
    description="Identity and Access Management Server for alxprgs.tech",
    version=get_build_info()["version"],
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)
app.include_router(privacy_router)

app.include_router(reauthentication_router)

app.add_middleware(BodyLimitMiddleware)
if settings.ENVIRONMENT == "production":
    production_hostname = urlsplit(settings.BASE_URL).hostname
    if production_hostname is None:
        raise ValueError("Production BASE_URL requires a hostname")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[production_hostname])

# Настройка CORS для доверенных клиентских приложений
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
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
    2. Устанавливает базовые заголовки безопасности; CSP задаётся proxy.
    """
    request_id = correlation(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    context_token = request_context_id.set(request_id)
    try:
        response: Response = await call_next(request)
        diagnostic(
            "http_request",
            "success"
            if response.status_code < 400
            else ("client_rejected" if response.status_code < 500 else "server_failed"),
            failed=response.status_code >= 500,
        )
    except Exception:
        diagnostic("http_request", "server_failed", failed=True)
        raise
    finally:
        request_context_id.reset(context_token)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith("/oauth/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


# --- Обработчики исключений безопасности ---


@app.exception_handler(IntegrityError)
async def safe_integrity_conflict(request: Request, exc: IntegrityError):
    # get_db rolls back the entire mutation, including reauthentication consumption.
    # Never reflect constraint names, SQL parameters or conflicting identity values.
    return JSONResponse(
        status_code=409,
        content={"error": "conflict", "detail": "Изменение конфликтует с существующими данными"},
    )


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
    headers = {}
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = (
            'Basic realm="oauth"'
            if exc.error == "invalid_client"
            else 'Bearer error="invalid_token"'
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/oauth/"):
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "error_description": "Отсутствуют обязательные параметры или неверен их формат",
            },
        )
    # Do not reflect passwords/tokens or raw invalid payloads in validation errors.
    return JSONResponse(
        status_code=422,
        content={
            "error": "invalid_request",
            "detail": "Проверьте формат и допустимые значения полей",
        },
    )


@app.exception_handler(StarletteHTTPException)
async def safe_http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/oauth/"):
        detail: dict[str, Any] = exc.detail if isinstance(exc.detail, dict) else {}
        error = detail.get("error", "invalid_request")
        if exc.status_code >= 500:
            error = "temporarily_unavailable"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": error, "error_description": "Запрос не может быть выполнен"},
            headers=exc.headers,
        )
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
    )


# --- Системные эндпоинты Health / Readiness (Section 4.6) ---


@app.get("/health/live", tags=["Health"])
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"])
async def health_ready(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    try:
        # Bound DNS/connect/pre-ping as well as execution; an unavailable DB
        # must not leave readiness hanging behind the reverse proxy.
        async with asyncio.timeout(READINESS_DATABASE_TIMEOUT_SECONDS):
            await db.execute(text("SELECT 1"))
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ready", "database": "connected"},
        )
    except Exception:
        diagnostic("database_readiness", "database_unavailable", failed=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "database": "disconnected"},
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
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
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
register_routes(app)
