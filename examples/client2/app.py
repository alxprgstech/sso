from __future__ import annotations

import os

from alxprgs_sso import SSOClient, UserClaims
from alxprgs_sso.fastapi import SSOFastAPISecurity
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

SSO_SERVER_URL = os.getenv("SSO_SERVER_URL", "http://localhost:8000")
CLIENT_ID = os.getenv("CLIENT_ID", "client_docs_app")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8002/callback")

sso_client = SSOClient(
    server_url=SSO_SERVER_URL,
    client_id=CLIENT_ID,
)
security = SSOFastAPISecurity(sso_client)

app = FastAPI(title="ALXPRGS Documentation (Client 2)")

# In-memory storage for demonstration PKCE states
oauth_states: dict[str, str] = {}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <html>
        <head><title>ALXPRGS Documentation (Client 2)</title></head>
        <body style="font-family: sans-serif; padding: 2rem;">
            <h1>Сервис 2: Портал документации</h1>
            <p>Второй независимый клиент в инфраструктуре ALXPRGS SSO.</p>
            <a href="/login" style="display:inline-block; padding: 10px 20px; background: #059669; color: white; text-decoration: none; border-radius: 4px;">Войти через ALXPRGS SSO</a>
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
        "client": "Client 2 (Documentation)",
        "message": "Успешная авторизация в Сервисе 2 через единый SSO",
        "user": claims.model_dump(),
        "access_token": tokens.access_token,
    }


@app.get("/api/docs")
async def get_docs(user: UserClaims = Depends(security.get_current_user)):
    return {
        "service": "documentation",
        "user": user.preferred_username,
        "articles": ["Введение в архитектуру", "Начало работы с SSO", "Безопасность"],
    }
