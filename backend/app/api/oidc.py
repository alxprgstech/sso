from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from typing import TypeGuard

from authlib.oauth2.rfc6749.util import extract_basic_authorization, scope_to_list
from fastapi import APIRouter, Depends, Form, Header, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_cookie_name, get_current_session, limit_security_endpoint
from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationException, OAuthErrorException
from app.core.rate_limit import get_client_ip
from app.core.security import create_jwt, decode_jwt, hash_token, valid_pkce_challenge
from app.database import get_db
from app.models.session import Session
from app.models.user import User
from app.schemas.oidc import TokenResponse, UserInfoResponse
from app.services.oidc_service import OIDCService


async def reject_duplicate_parameters(request: Request) -> None:
    parameters = request.query_params if request.method == "GET" else await request.form()
    if any(len(parameters.getlist(name)) > 1 for name in parameters):
        raise OAuthErrorException("invalid_request", "Повторяющиеся параметры запрещены", 400)


router = APIRouter(
    prefix="/oauth",
    tags=["OpenID Connect"],
    dependencies=[Depends(reject_duplicate_parameters), Depends(limit_security_endpoint)],
)


def _interaction_started_at(value: object) -> TypeGuard[int | float]:
    return type(value) in (int, float)


def redirect_parameters(uri: str, values: dict[str, str]) -> RedirectResponse:
    parsed = urllib.parse.urlsplit(uri)
    parameters = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    parameters = [(key, value) for key, value in parameters if key not in values]
    parameters.extend(values.items())
    return RedirectResponse(
        urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(parameters))), 302
    )


def _extract_client_credentials(
    request: Request,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> tuple[str, str | None]:
    """
    Извлекает client_id и client_secret из HTTP Basic Auth или параметров формы (RFC 6749 Section 2.3).
    Запрещает одновременное использование нескольких методов аутентификации.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and (len(auth_header) > 4096 or not auth_header.lower().startswith("basic ")):
        raise OAuthErrorException("invalid_client", "Неверный метод аутентификации клиента", 401)
    if auth_header and auth_header.lower().startswith("basic "):
        if client_id is not None or client_secret is not None:
            raise OAuthErrorException(
                "invalid_request",
                "Использование более одного метода аутентификации клиента запрещено (RFC 6749 Section 2.3)",
                400,
            )
        try:
            creds = extract_basic_authorization(
                {"Authorization": "Basic " + auth_header.split(" ", 1)[1]}
            )
            if not creds:
                raise ValueError("Empty credentials")
            cid, csec = creds
            if not 1 <= len(cid) <= 64 or (csec is not None and len(csec) > 128):
                raise ValueError("Invalid client credentials length")
            return cid, csec
        except Exception:
            raise OAuthErrorException(
                "invalid_client", "Некорректный заголовок Basic авторизации", 401
            )
    if not client_id:
        raise OAuthErrorException("invalid_client", "Отсутствует client_id", 401)
    return client_id, client_secret


@router.get("/authorize")
async def authorize(
    request: Request,
    client_id: str = Query(..., max_length=64),
    redirect_uri: str = Query(..., max_length=512),
    response_type: str = Query(..., max_length=32),
    scope: str = Query("openid profile email", max_length=255),
    state: str | None = Query(None, max_length=128),
    code_challenge: str = Query(..., max_length=128),
    code_challenge_method: str = Query("S256", max_length=10),
    nonce: str | None = Query(None, max_length=128),
    prompt: str | None = Query(None, max_length=32),
    max_age: int | None = Query(None, ge=0, le=604800),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    client = await OIDCService.get_and_validate_client(
        db, client_id=client_id, require_secret=False
    )
    OIDCService.validate_redirect_uri(client, redirect_uri)

    def error_redirect(error: str) -> Response:
        return redirect_parameters(
            redirect_uri, {"error": error, **({"state": state} if state else {})}
        )

    if response_type != "code":
        return error_redirect("unsupported_response_type")
    if (
        prompt not in {None, "login", "none"}
        or code_challenge_method != "S256"
        or not valid_pkce_challenge(code_challenge)
    ):
        return error_redirect("invalid_request")
    requested = set(scope_to_list(scope))
    if "openid" not in requested or not requested <= set(client.allowed_scopes.split()):
        return error_redirect("invalid_scope")

    user = None
    session = None
    try:
        session = await get_current_session(request, db, settings)
        user = await db.scalar(select(User).where(User.id == session.user_id))
        if user is None or (settings.REQUIRE_VERIFIED_EMAIL and not user.email_verified):
            user = None
    except AuthenticationException:
        await db.rollback()

    # A signed short-lived interaction cookie binds a forced login to this exact
    # request. A new session must have been authenticated after its creation;
    # refreshing/last_activity does not satisfy prompt=login or max_age=0.
    flow_cookie = (
        "__Host-oidc_interaction"
        if settings.ENVIRONMENT == "production" or request.url.scheme == "https"
        else "oidc_interaction"
    )
    digest = hash_token(request.url.query)
    completed_interaction = False
    marker = request.cookies.get(flow_cookie)
    if marker and session:
        try:
            claims = decode_jwt(
                marker, audience="alxprgs:interaction", expected_use="authorization_interaction"
            )
            began = claims.get("started_at")
            completed_interaction = (
                claims.get("flow") == digest
                and _interaction_started_at(began)
                and session.auth_time.timestamp() >= began
            )
        except OAuthErrorException:
            pass
    stale = bool(
        session
        and max_age is not None
        and (
            max_age == 0
            or (datetime.now(timezone.utc) - session.auth_time).total_seconds() > max_age
        )
    )
    interaction_required = not user or ((prompt == "login" or stale) and not completed_interaction)
    if interaction_required:
        if prompt == "none":
            return error_redirect("login_required")
        return_to = urllib.parse.quote(request.url.path + "?" + request.url.query, safe="")
        result = RedirectResponse(
            f"{settings.FRONTEND_URL}/login?force_login=1&return_to={return_to}", 302
        )
        interaction = create_jwt(
            {
                "sub": "authorization_interaction",
                "aud": "alxprgs:interaction",
                "token_use": "authorization_interaction",
                "flow": digest,
                "started_at": datetime.now(timezone.utc).timestamp(),
            },
            300,
        )
        result.set_cookie(
            flow_cookie,
            interaction,
            max_age=300,
            httponly=True,
            secure=settings.ENVIRONMENT == "production" or request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
        return result

    from app.services.privacy_service import has_current_acceptance

    if user is None or session is None:
        return error_redirect("login_required")
    if session.purpose == "password_change":
        return (
            error_redirect("interaction_required")
            if prompt == "none"
            else RedirectResponse(f"{settings.FRONTEND_URL}/change-password", 302)
        )
    if user.deletion_scheduled_for or session.purpose == "deletion_management":
        return (
            error_redirect("interaction_required")
            if prompt == "none"
            else RedirectResponse(f"{settings.FRONTEND_URL}/account-deletion", 302)
        )
    if not await has_current_acceptance(db, user.id):
        if prompt == "none":
            return error_redirect("interaction_required")
        return_to = urllib.parse.quote(request.url.path + "?" + request.url.query, safe="")
        return RedirectResponse(f"{settings.FRONTEND_URL}/accept-terms?return_to={return_to}", 302)
    try:
        code = await OIDCService.create_authorization_code(
            db=db,
            client=client,
            user=user,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            nonce=nonce,
            scope=scope,
            auth_time=session.auth_time,
            session_id=session.id,
        )
    except (AuthenticationException, OAuthErrorException):
        await db.rollback()
        return error_redirect("login_required")
    result = redirect_parameters(
        redirect_uri, {"code": code, **({"state": state} if state else {})}
    )
    result.delete_cookie(flow_cookie, path="/")
    return result


@router.post("/token", response_model=TokenResponse)
async def token(
    request: Request,
    grant_type: str = Form(..., max_length=64),
    code: str | None = Form(None, max_length=128),
    code_verifier: str | None = Form(None, max_length=128),
    redirect_uri: str | None = Form(None, max_length=512),
    client_id: str | None = Form(None, max_length=64),
    client_secret: str | None = Form(None, max_length=128),
    refresh_token: str | None = Form(None, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Эндпоинт обмена токенов (SSO-01, SSO-03, SSO-05).
    Поддерживает:
      - grant_type=authorization_code (PKCE S256)
      - grant_type=refresh_token (Token Rotation & Replay Detection)
    """
    cid, csec = _extract_client_credentials(request, client_id, client_secret)
    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent")

    if grant_type == "authorization_code":
        if not code or not code_verifier or not redirect_uri:
            raise OAuthErrorException(
                "invalid_request",
                "Параметры code, code_verifier и redirect_uri обязательны для grant_type=authorization_code",
                400,
            )
        return await OIDCService.exchange_code(
            db=db,
            client_id=cid,
            client_secret=csec,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            ip_address=ip,
            user_agent=ua,
        )

    elif grant_type == "refresh_token":
        if not refresh_token:
            raise OAuthErrorException("invalid_request", "Параметр refresh_token обязателен", 400)
        return await OIDCService.rotate_refresh_token(
            db=db,
            client_id=cid,
            client_secret=csec,
            raw_refresh_token=refresh_token,
            ip_address=ip,
            user_agent=ua,
        )

    else:
        raise OAuthErrorException(
            "unsupported_grant_type",
            "Поддерживаются authorization_code и refresh_token",
            400,
        )


@router.get("/userinfo", response_model=UserInfoResponse, response_model_exclude_none=True)
@router.post("/userinfo", response_model=UserInfoResponse, response_model_exclude_none=True)
async def userinfo(
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> UserInfoResponse:
    """
    Эндпоинт UserInfo (SSO-01, SSO-04).
    Принимает только Bearer Access Token.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise OAuthErrorException(
            "invalid_token", "Требуется заголовок Authorization: Bearer <token>", 401
        )

    access_token = authorization.split(" ", 1)[1]
    return await OIDCService.get_userinfo(db, access_token)


@router.post("/revoke")
async def revoke(
    request: Request,
    token: str = Form(...),
    token_type_hint: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    RFC 7009 Token Revocation endpoint (SSO-07).
    """
    cid, csec = _extract_client_credentials(request, client_id, client_secret)
    await OIDCService.revoke_token(
        db=db,
        client_id=cid,
        client_secret=csec,
        token=token,
        token_type_hint=token_type_hint,
    )
    return {}


async def logout_parameters(request: Request) -> dict[str, str]:
    values = request.query_params if request.method == "GET" else await request.form()
    allowed = {"id_token_hint", "post_logout_redirect_uri", "state", "client_id", "csrf_token"}
    if any(key not in allowed for key in values):
        raise OAuthErrorException("invalid_request", "Неизвестные параметры выхода", 400)
    result = {}
    for name in allowed:
        value = values.get(name)
        if value is not None:
            limit = (
                16384
                if name == "id_token_hint"
                else 512
                if name == "post_logout_redirect_uri"
                else 128
            )
            if not isinstance(value, str) or len(value) > limit:
                raise OAuthErrorException(
                    "invalid_request", "Неверный формат параметров выхода", 400
                )
            result[name] = value
    return result


async def _logout_claims(db: AsyncSession, values: dict[str, str]):
    from app.core.security import decode_logout_hint

    hint = values.get("id_token_hint")
    redirect_uri = values.get("post_logout_redirect_uri")
    selected_client = values.get("client_id")
    claims = None
    if hint:
        claims, audience = decode_logout_hint(hint)
        if selected_client and selected_client != audience:
            raise OAuthErrorException("invalid_request", "Клиент не совпадает с ID Token", 400)
        selected_client = audience
    if redirect_uri and not selected_client:
        raise OAuthErrorException("invalid_request", "Для redirect URI требуется клиент", 400)
    if selected_client:
        client = await OIDCService.get_and_validate_client(
            db, selected_client, require_secret=False
        )
        if redirect_uri:
            OIDCService.validate_redirect_uri(client, redirect_uri)
    return claims


def _require_hint_session(claims, session: Session | None) -> None:
    if session and str(session.user_id) != claims["sub"]:
        raise OAuthErrorException(
            "invalid_token", "ID Token не относится к текущей SSO-сессии", 401
        )
    if claims["exp"] <= datetime.now(timezone.utc).timestamp():
        if not session or claims.get("auth_time") != int(session.auth_time.timestamp()):
            raise OAuthErrorException(
                "invalid_token", "Истёкший ID Token не связан с текущей сессией", 401
            )


def _logout_confirmation(values: dict[str, str], session: Session, settings: Settings) -> Response:
    import html
    from fastapi.responses import HTMLResponse
    from app.api.deps import generate_csrf_token

    hidden = {key: value for key, value in values.items() if key != "csrf_token"}
    hidden["csrf_token"] = generate_csrf_token(session.id, settings)
    fields = "".join(
        f'<input type="hidden" name="{html.escape(key, quote=True)}" value="{html.escape(value, quote=True)}">'
        for key, value in hidden.items()
    )
    response = HTMLResponse(
        '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Выход из SSO</title><h1>Завершить текущую сессию?</h1><form method="post" action="/oauth/logout">'
        + fields
        + '<button type="submit">Выйти из SSO</button></form><a href="/">Отмена</a></html>'
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    return response


def _require_logout_csrf(
    request: Request, values: dict[str, str], session: Session, settings: Settings
) -> None:
    import hmac
    from app.api.deps import generate_csrf_token

    origin = request.headers.get("Origin")
    supplied = values.get("csrf_token", "")
    if (
        origin and origin not in {settings.BASE_URL, settings.FRONTEND_URL}
    ) or not hmac.compare_digest(supplied, generate_csrf_token(session.id, settings)):
        raise OAuthErrorException("invalid_request", "Подтверждение выхода недействительно", 403)


@router.get("/logout")
@router.post("/logout")
async def logout(
    request: Request,
    values: dict[str, str] = Depends(logout_parameters),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:

    from app.services.security_state import lock_user

    claims = await _logout_claims(db, values)
    redirect_uri = values.get("post_logout_redirect_uri")
    state = values.get("state")
    session = None
    try:
        session = await get_current_session(request, db, settings)
    except AuthenticationException:
        await db.rollback()
    if claims:
        _require_hint_session(claims, session)
    elif session:
        if request.method == "GET":
            return _logout_confirmation(values, session, settings)
        _require_logout_csrf(request, values, session, settings)
    if session:
        # Account before session, matching every security mutation's lock order.
        await lock_user(db, session.user_id)
        current = await db.scalar(select(Session).where(Session.id == session.id).with_for_update())
        if current:
            await db.delete(current)
        await db.commit()
    target = redirect_uri or settings.FRONTEND_URL
    result = redirect_parameters(target, {"state": state} if state and redirect_uri else {})
    result.delete_cookie(get_cookie_name(settings, request), path="/")
    return result
