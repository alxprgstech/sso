from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

from authlib.oauth2.rfc6749.util import extract_basic_authorization, scope_to_list
from fastapi import APIRouter, Depends, Form, Header, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_cookie_name
from app.config import Settings, get_settings
from app.core.exceptions import OAuthErrorException
from app.core.security import decode_jwt, hash_token
from app.database import get_db
from app.models.session import Session
from app.models.user import User
from app.schemas.oidc import TokenResponse, UserInfoResponse
from app.services.oidc_service import OIDCService

router = APIRouter(prefix="/oauth", tags=["OpenID Connect"])


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
    if auth_header and auth_header.startswith("Basic "):
        if client_id is not None or client_secret is not None:
            raise OAuthErrorException(
                "invalid_request",
                "Использование более одного метода аутентификации клиента запрещено (RFC 6749 Section 2.3)",
                400,
            )
        try:
            creds = extract_basic_authorization(dict(request.headers))
            if not creds:
                raise ValueError("Empty credentials")
            cid, csec = creds
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
    response: Response,
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    response_type: str = Query(...),
    scope: str = Query("openid profile email"),
    state: str | None = Query(None),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    nonce: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    Эндпоинт авторизации OIDC (SSO-01..03).
    Поддерживает бесшовный Single Sign-On, если пользователь уже аутентифицирован.
    """
    if response_type != "code":
        raise OAuthErrorException(
            "unsupported_response_type", "Поддерживается только response_type=code", 400
        )

    # Валидация запрошенного scope (SSO-04)
    SUPPORTED_SCOPES = {"openid", "profile", "email"}
    requested_scopes = set(scope_to_list(scope))
    if "openid" not in requested_scopes:
        raise OAuthErrorException(
            "invalid_scope", "Запрос OpenID Connect должен содержать scope 'openid'", 400
        )
    unsupported_scopes = requested_scopes - SUPPORTED_SCOPES
    if unsupported_scopes:
        raise OAuthErrorException(
            "invalid_scope",
            f"Неподдерживаемые scopes: {', '.join(sorted(unsupported_scopes))}",
            400,
        )

    # 1. Валидация клиента и точного redirect_uri
    client = await OIDCService.get_and_validate_client(
        db, client_id=client_id, require_secret=False
    )
    OIDCService.validate_redirect_uri(client, redirect_uri)

    # 2. Проверка активной валидной сессии пользователя в SSO (G8-SEC, FINAL-02)
    cookie_name = get_cookie_name(settings, request)
    raw_token = request.cookies.get(cookie_name)
    user: User | None = None
    session_invalid = False

    if raw_token:
        token_hash = hash_token(raw_token)
        sess_stmt = select(Session).where(Session.session_token_hash == token_hash)
        session_obj = (await db.execute(sess_stmt)).scalar_one_or_none()
        if session_obj:
            now = datetime.now(timezone.utc)
            # Проверка абсолютного срока жизни (7 дней)
            if session_obj.expires_at <= now:
                await db.delete(session_obj)
                await db.commit()
                session_invalid = True
            # Проверка срока неактивности (idle timeout: 12 часов)
            elif (
                now - session_obj.last_activity_at
            ).total_seconds() > settings.SESSION_IDLE_TIMEOUT_SECONDS:
                await db.delete(session_obj)
                await db.commit()
                session_invalid = True
            else:
                user_stmt = select(User).where(User.id == session_obj.user_id)
                user_candidate = (await db.execute(user_stmt)).scalar_one_or_none()
                if not user_candidate or not user_candidate.is_active:
                    session_invalid = True
                elif (
                    settings.REQUIRE_VERIFIED_EMAIL
                    and settings.FEATURE_EMAIL_VERIFICATION_ENABLED
                    and not user_candidate.email_verified
                ):
                    session_invalid = True
                else:
                    user = user_candidate
                    session_obj.last_activity_at = now
                    await db.commit()
        else:
            session_invalid = True

    # Если пользователь не аутентифицирован или сессия недействительна, перенаправляем на страницу входа
    if not user:
        return_url = str(request.url)
        login_url = f"{settings.FRONTEND_URL}/login?return_to={urllib.parse.quote(return_url)}"
        redirect_res = RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)
        if raw_token or session_invalid:
            redirect_res.delete_cookie(key=cookie_name, path="/")
        return redirect_res

    # 3. Пользователь авторизован в SSO -> моментальный выпуск single-use authorization code
    code = await OIDCService.create_authorization_code(
        db=db,
        client=client,
        user=user,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        nonce=nonce,
        scope=scope,
    )

    # Формирование URL возврата в клиентское приложение
    parsed = urllib.parse.urlparse(redirect_uri)
    query_params = urllib.parse.parse_qs(parsed.query)
    query_params["code"] = [code]
    if state:
        query_params["state"] = [state]
    new_query = urllib.parse.urlencode(query_params, doseq=True)
    target_url = urllib.parse.urlunparse(parsed._replace(query=new_query))

    return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)


@router.post("/token", response_model=TokenResponse)
async def token(
    request: Request,
    grant_type: str = Form(...),
    code: str | None = Form(None),
    code_verifier: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    refresh_token: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Эндпоинт обмена токенов (SSO-01, SSO-03, SSO-05).
    Поддерживает:
      - grant_type=authorization_code (PKCE S256)
      - grant_type=refresh_token (Token Rotation & Replay Detection)
    """
    cid, csec = _extract_client_credentials(request, client_id, client_secret)
    ip = request.client.host if request.client else None
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
            f"Неподдерживаемый grant_type: '{grant_type}'. Разрешены authorization_code и refresh_token.",
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


@router.get("/logout")
async def logout(
    request: Request,
    response: Response,
    id_token_hint: str | None = Query(None),
    post_logout_redirect_uri: str | None = Query(None),
    state: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    RP-Initiated Logout (SSO-07).
    Завершает сессию SSO и перенаправляет обратно в клиентское приложение.
    """
    if not id_token_hint:
        raise OAuthErrorException("invalid_request", "id_token_hint обязателен для выхода RP", 400)
    # The first decode verifies signature, issuer and time. The audience is then
    # checked explicitly against the active client selected by that signed claim.
    hint_claims = decode_jwt(id_token_hint)
    audience = hint_claims.get("aud")
    if hint_claims.get("token_use") != "id_token" or not isinstance(audience, str):
        raise OAuthErrorException("invalid_token", "Требуется действительный ID Token клиента", 401)
    hint_claims = decode_jwt(id_token_hint, audience=audience)
    client = await OIDCService.get_and_validate_client(db, client_id=audience, require_secret=False)
    if post_logout_redirect_uri:
        OIDCService.validate_redirect_uri(client, post_logout_redirect_uri)

    cookie_name = get_cookie_name(settings, request)
    raw_token = request.cookies.get(cookie_name)
    if raw_token:
        token_hash = hash_token(raw_token)
        stmt = select(Session).where(Session.session_token_hash == token_hash)
        sess = (await db.execute(stmt)).scalar_one_or_none()
        if sess and str(sess.user_id) == str(hint_claims.get("sub")):
            await db.delete(sess)
            await db.commit()
        elif sess:
            raise OAuthErrorException(
                "invalid_token", "ID Token не относится к текущей SSO-сессии", 401
            )

    target = post_logout_redirect_uri or settings.FRONTEND_URL
    if state and post_logout_redirect_uri:
        delim = "&" if "?" in target else "?"
        target = f"{target}{delim}state={urllib.parse.quote(state)}"

    redirect_res = RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
    redirect_res.delete_cookie(key=cookie_name, path="/")
    return redirect_res
