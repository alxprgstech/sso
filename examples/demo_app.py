"""FastAPI wiring shared by two single-process SSO demonstration clients."""

from __future__ import annotations

import html
import os
import secrets
from urllib.parse import urlparse

from alxprgs_sso import SSOClient, UserClaims
from alxprgs_sso.exceptions import SSOError
from alxprgs_sso.fastapi import SSOFastAPISecurity
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from examples.demo_sessions import FLOW_TTL, SESSION_ABSOLUTE_TTL, DemoSessions


def make_demo_app(
    *,
    title: str,
    heading: str,
    client_id: str,
    redirect_uri: str,
    peer_url: str,
    api_path: str,
) -> tuple[FastAPI, SSOClient, DemoSessions]:
    client_id = os.getenv("CLIENT_ID", client_id)
    redirect_uri = os.getenv("REDIRECT_URI", redirect_uri)
    peer_url = os.getenv("PEER_URL", peer_url)
    sso_client = SSOClient(
        server_url=os.getenv("SSO_SERVER_URL", "http://localhost:8000"),
        client_id=client_id,
        client_secret=os.getenv("CLIENT_SECRET"),
        expected_issuer=os.getenv("OIDC_ISSUER", "https://auth.alxprgs.tech"),
        expected_audience=client_id,
    )
    security = SSOFastAPISecurity(sso_client)
    store = DemoSessions()
    app = FastAPI(title=title)
    cookie_prefix = "__Host-" if urlparse(redirect_uri).scheme == "https" else "demo_"
    flow_cookie = f"{cookie_prefix}{client_id}_flow"
    session_cookie = f"{cookie_prefix}{client_id}_session"

    def cookie_secure(request: Request) -> bool:
        if request.url.scheme == "https":
            return True
        if (
            request.url.hostname in {"localhost", "127.0.0.1"}
            and os.getenv("DEMO_ALLOW_HTTP_LOCALHOST") == "1"
        ):
            return False
        raise HTTPException(status_code=400, detail="HTTPS required for demo session cookies")

    def current_session(request: Request):
        return store.get_session(request.cookies.get(session_cookie))

    def escaped(value: object) -> str:
        return html.escape(str(value or ""), quote=True)

    def render(session=None) -> str:
        if session is None:
            return (
                f"<html><body><h1>{escaped(heading)}</h1>"
                '<a id="btn-login" href="/login">Войти через ALXPRGS SSO</a>'
                "</body></html>"
            )
        user = session.info.user
        roles = ", ".join(user.roles)
        return (
            f"<html><body><h1>{escaped(heading)}</h1>"
            f'<p id="user-info"><span id="username">{escaped(user.preferred_username)}</span> '
            f'<span id="email">{escaped(user.email)}</span> '
            f'<span id="roles">{escaped(roles)}</span></p>'
            f'<a id="link-client-peer" href="{escaped(peer_url)}">Другой клиент</a>'
            f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{escaped(session.csrf)}">'
            '<button id="btn-logout" type="submit">Локальный выход</button></form>'
            f'<form method="post" action="/sso-logout"><input type="hidden" name="csrf" value="{escaped(session.csrf)}">'
            '<button id="btn-sso-logout" type="submit">Выход из SSO</button></form>'
            "</body></html>"
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> str:
        return render(current_session(request))

    @app.get("/login")
    async def login(request: Request) -> RedirectResponse:
        secure = cookie_secure(request)
        auth_url, verifier, state, nonce = sso_client.start_authorization(redirect_uri=redirect_uri)
        identifier = store.start_flow(state, nonce, verifier)
        response = RedirectResponse(auth_url, status_code=302)
        response.set_cookie(
            flow_cookie,
            identifier,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
            max_age=FLOW_TTL,
        )
        return response

    @app.get("/callback")
    async def callback(request: Request, code: str, state: str) -> RedirectResponse:
        secure = cookie_secure(request)
        flow = store.take_flow(request.cookies.get(flow_cookie), state)
        if flow is None:
            raise HTTPException(
                status_code=400, detail="Invalid, expired, or previously used browser flow"
            )
        try:
            info = await sso_client.handle_web_callback(
                code=code,
                state=state,
                expected_state=flow.state,
                expected_nonce=flow.nonce,
                code_verifier=flow.verifier,
                redirect_uri=redirect_uri,
            )
        except SSOError as exc:
            raise HTTPException(status_code=400, detail="OIDC callback rejected") from exc
        session_id, _ = store.create_session(info)
        response = RedirectResponse("/dashboard", status_code=302)
        response.delete_cookie(flow_cookie, path="/")
        response.set_cookie(
            session_cookie,
            session_id,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
            max_age=SESSION_ABSOLUTE_TTL,
        )
        return response

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        session = current_session(request)
        if session is None:
            return RedirectResponse("/login", status_code=302)
        return render(session)

    def revoke_with_csrf(request: Request, csrf: str):
        identifier = request.cookies.get(session_cookie)
        session = store.get_session(identifier)
        if session is None or not csrf or not secrets.compare_digest(csrf, session.csrf):
            raise HTTPException(status_code=403, detail="Invalid session or CSRF token")
        store.revoke(identifier)
        return session

    @app.post("/logout")
    async def logout(request: Request, csrf: str = Form(...)) -> RedirectResponse:
        revoke_with_csrf(request, csrf)
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(session_cookie, path="/")
        return response

    @app.post("/sso-logout")
    async def sso_logout(request: Request, csrf: str = Form(...)) -> RedirectResponse:
        session = revoke_with_csrf(request, csrf)
        if not session.info.id_token:
            raise HTTPException(status_code=400, detail="Session has no ID Token")
        response = RedirectResponse(
            sso_client.create_logout_url(session.info.id_token), status_code=303
        )
        response.delete_cookie(session_cookie, path="/")
        return response

    @app.get("/api/me")
    async def api_me(request: Request):
        session = current_session(request)
        if session is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"client": client_id, "user": session.info.user.model_dump()}

    @app.get(api_path)
    async def protected_api(user: UserClaims = Depends(security.get_current_user)):
        return {"client": client_id, "subject": user.sub}

    return app, sso_client, store
