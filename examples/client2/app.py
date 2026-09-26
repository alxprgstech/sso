from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from alxprgs_sso import SSOClient, UserClaims
from alxprgs_sso.fastapi import SSOFastAPISecurity
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

SSO_SERVER_URL = os.getenv("SSO_SERVER_URL", "http://localhost:8000")
CLIENT_ID = os.getenv("CLIENT_ID", "client_docs_app")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "docs_client_secret_123")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8002/callback")
APP_SECRET = os.getenv("APP_SECRET", "client2-secret-key-32-bytes-long-67890")

sso_client = SSOClient(
    server_url=SSO_SERVER_URL,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    expected_issuer=os.getenv("OIDC_ISSUER", "https://auth.alxprgs.tech"),
    expected_audience=CLIENT_ID,
)
security = SSOFastAPISecurity(sso_client)

app = FastAPI(title="ALXPRGS Documentation (Client 2)")


def sign_cookie_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    sig = hmac.new(APP_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(raw).decode("ascii") + "." + sig


def verify_cookie_payload(cookie_val: str | None) -> dict[str, Any] | None:
    if not cookie_val or "." not in cookie_val:
        return None
    try:
        raw_b64, sig = cookie_val.split(".", 1)
        raw = base64.urlsafe_b64decode(raw_b64.encode("ascii"))
        expected_sig = hmac.new(APP_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, expected_sig):
            return None
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = verify_cookie_payload(request.cookies.get("client2_session"))
    if user:
        return f"""
        <html>
            <head><title>ALXPRGS Documentation (Client 2)</title></head>
            <body style="font-family: sans-serif; padding: 2rem;">
                <h1>Сервис 2: Портал документации</h1>
                <p>Вы вошли как <strong>{user.get("preferred_username")}</strong> ({user.get("email")}).</p>
                <p><a id="link-dashboard" href="/dashboard" style="display:inline-block; padding: 10px 20px; background: #059669; color: white; text-decoration: none; border-radius: 4px;">Перейти в Портал документации</a></p>
                <p><a id="link-logout" href="/logout" style="color: #dc2626;">Выйти из системы</a></p>
            </body>
        </html>
        """
    return """
    <html>
        <head><title>ALXPRGS Documentation (Client 2)</title></head>
        <body style="font-family: sans-serif; padding: 2rem;">
            <h1>Сервис 2: Портал документации</h1>
            <p>Второй независимый клиент в инфраструктуре ALXPRGS SSO.</p>
            <a id="btn-login" href="/login" style="display:inline-block; padding: 10px 20px; background: #059669; color: white; text-decoration: none; border-radius: 4px;">Войти через ALXPRGS SSO</a>
        </body>
    </html>
    """


@app.get("/login")
async def login():
    auth_url, code_verifier, state, nonce = sso_client.start_authorization(
        redirect_uri=REDIRECT_URI,
        scope="openid profile email",
    )
    flow_data = {
        "state": state,
        "verifier": code_verifier,
        "nonce": nonce,
        "ts": time.time(),
    }
    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key="client2_auth_flow",
        value=sign_cookie_payload(flow_data),
        httponly=True,
        samesite="lax",
        max_age=300,
    )
    return response


@app.get("/callback")
async def callback(request: Request, code: str, state: str):
    cookie_val = request.cookies.get("client2_auth_flow")
    if not cookie_val:
        raise HTTPException(status_code=400, detail="Отсутствует сессия авторизации")

    flow = verify_cookie_payload(cookie_val)
    if not flow or time.time() - flow.get("ts", 0) > 300:
        raise HTTPException(status_code=400, detail="Истекла сессия авторизации")

    if not secrets.compare_digest(state, flow.get("state", "")):
        raise HTTPException(
            status_code=400, detail="Недействительный параметр state (CSRF detected)"
        )

    session_info = await sso_client.handle_web_callback(
        code=code,
        state=state,
        expected_state=flow["state"],
        code_verifier=flow["verifier"],
        redirect_uri=REDIRECT_URI,
        expected_nonce=flow.get("nonce"),
    )

    user_data = {
        "sub": session_info.user.sub,
        "preferred_username": session_info.user.preferred_username,
        "email": session_info.user.email,
        "roles": session_info.user.roles,
    }

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.delete_cookie(key="client2_auth_flow")
    response.set_cookie(
        key="client2_session",
        value=sign_cookie_payload(user_data),
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = verify_cookie_payload(request.cookies.get("client2_session"))
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return f"""
    <html>
        <head><title>Портал документации — Client 2</title></head>
        <body style="font-family: sans-serif; padding: 2rem;">
            <h1>Сервис 2: База знаний и документация</h1>
            <div id="user-info" style="background: #f3f4f6; padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem;">
                <p><strong>Пользователь:</strong> <span id="username">{user.get("preferred_username")}</span></p>
                <p><strong>Email:</strong> <span id="email">{user.get("email")}</span></p>
                <p><strong>Роли:</strong> <span id="roles">{", ".join(user.get("roles", []))}</span></p>
            </div>
            <div style="margin-bottom: 1.5rem;">
                <h3>Доступные разделы документации</h3>
                <ul>
                    <li>Руководство по интеграции SSO SDK</li>
                    <li>Справочник API endpoints и протоколов OIDC</li>
                    <li>Инварианты безопасности и управление ключами</li>
                </ul>
            </div>
            <hr style="margin: 1.5rem 0;" />
            <p>
                <a id="link-client1" href="http://localhost:8001/login" style="display:inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 4px; margin-right: 1rem;">
                    &larr; Перейти в Сервис 1 (Аналитика)
                </a>
                <a id="btn-logout" href="/logout" style="display:inline-block; padding: 10px 20px; background: #dc2626; color: white; text-decoration: none; border-radius: 4px;">
                    Выйти из аккаунта (Logout)
                </a>
            </p>
        </body>
    </html>
    """


@app.get("/logout")
async def logout():
    logout_url = sso_client.create_logout_url(post_logout_redirect_uri="http://localhost:8002/")
    response = RedirectResponse(url=logout_url, status_code=302)
    response.delete_cookie(key="client2_session")
    return response


@app.get("/api/me")
async def api_me(request: Request):
    user = verify_cookie_payload(request.cookies.get("client2_session"))
    if not user:
        raise HTTPException(status_code=401, detail="Не авторизован")
    return {"client": "client_docs_app", "user": user}


@app.get("/api/docs")
async def get_docs(user: UserClaims = Depends(security.get_current_user)):
    return {
        "service": "documentation",
        "user": user.preferred_username,
        "articles": ["Введение в архитектуру", "Начало работы с SSO", "Безопасность"],
    }
