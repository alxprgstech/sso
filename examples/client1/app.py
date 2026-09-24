from __future__ import annotations

import os

from alxprgs_sso import SSOClient, UserClaims
from alxprgs_sso.fastapi import SSOFastAPISecurity
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

SSO_SERVER_URL = os.getenv("SSO_SERVER_URL", "http://localhost:8000")
CLIENT_ID = os.getenv("CLIENT_ID", "client_analytics_app")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8001/callback")

sso_client = SSOClient(
    server_url=SSO_SERVER_URL,
    client_id=CLIENT_ID,
)
security = SSOFastAPISecurity(sso_client)

app = FastAPI(title="ALXPRGS Analytics (Client 1)")

# In-memory storage for demonstration PKCE states
oauth_states: dict[str, str] = {}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <html>
        <head><title>ALXPRGS Analytics (Client 1)</title></head>
        <body style="font-family: sans-serif; padding: 2rem;">
            <h1>Сервис 1: Портал аналитики</h1>
            <p>Интеграция с единой системой входа ALXPRGS SSO через alxprgs-sso SDK.</p>
            <a href="/login" style="display:inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 4px;">Войти через ALXPRGS SSO</a>
        </body>
    </html>
    """


@app.get("/login")
async def login():
    auth_url, code_verifier, state = sso_client.generate_authorization_url(
        redirect_uri=REDIRECT_URI,
        scope="openid profile email",
    )
    oauth_states[state] = code_verifier
    return RedirectResponse(url=auth_url)


@app.get("/callback")
async def callback(code: str, state: str):
    code_verifier = oauth_states.pop(state, None)
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Недействительный параметр state")

    tokens = await sso_client.exchange_code_for_tokens(
        code=code,
        redirect_uri=REDIRECT_URI,
        code_verifier=code_verifier,
    )

    claims = sso_client.verify_access_token(tokens.access_token)
    return {
        "client": "Client 1 (Analytics)",
        "message": "Успешная авторизация в Сервисе 1",
        "user": claims.model_dump(),
        "access_token": tokens.access_token,
        "cross_sso_hint": "Пользователь вошел в SSO. Теперь переход на Сервис 2 (http://localhost:8002/login) произойдет бесшовно без повторного ввода пароля!",
    }


@app.get("/api/analytics")
async def get_analytics(user: UserClaims = Depends(security.get_current_user)):
    return {
        "service": "analytics",
        "user": user.preferred_username,
        "metrics": {"total_events": 1024, "status": "active"},
    }
