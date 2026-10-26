"""Minimal reference relying party for ALXPRGS transaction step-up.

This is an example, not a production application.  It stores browser sessions
and step-up state in process memory, so it must run as a single worker and is
not suitable for horizontal scaling.  Its purpose is to demonstrate the exact
server-side flow: OIDC login, hosted step-up, server-side proof redemption,
transaction checks and one-use action execution.

Required environment:
  SSO_URL, SSO_CLIENT_ID, SSO_CLIENT_SECRET
  RP_REDIRECT_URI, RP_STEP_UP_REDIRECT_URI, RP_BASE_URL
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
from dataclasses import dataclass, field
from typing import Any

from alxprgs_sso import SSOClient, StepUpProof, StepUpRequest, UserClaims
from alxprgs_sso.exceptions import SSOError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="ALXPRGS Step-Up Reference RP")
ACTION = "critical_settings_change"
PAYLOAD = {"setting": "allow_external_sharing", "value": False}


@dataclass
class BrowserSession:
    user: UserClaims
    access_token: str
    id_token: str | None = None
    refresh_token: str | None = None
    pending: dict[str, Any] | None = None
    proofs: dict[str, StepUpProof] = field(default_factory=dict)
    executed: bool = False
    csrf_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))


SESSIONS: dict[str, BrowserSession] = {}
STEP_UP_FLOWS: dict[str, StepUpRequest] = {}
OIDC_FLOWS: dict[str, tuple[str, str, str]] = {}


def client() -> SSOClient:
    return SSOClient(
        server_url=os.environ["SSO_URL"],
        client_id=os.environ["SSO_CLIENT_ID"],
        client_secret=os.environ["SSO_CLIENT_SECRET"],
        expected_issuer=os.environ.get("SSO_ISSUER"),
        transport_profile=os.environ.get("SSO_TRANSPORT_PROFILE", "strict"),
    )


def payload_hash() -> str:
    canonical = json.dumps(PAYLOAD, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def session_for(request: Request) -> BrowserSession:
    sid = request.cookies.get("rp_session")
    if not sid or sid not in SESSIONS:
        raise HTTPException(401, "Сначала войдите через SSO")
    return SESSIONS[sid]


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='ru'><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><body><main>"
        f"<h1>{html.escape(title)}</h1>{body}</main></body></html>"
    )


def cookie_secure() -> bool:
    return os.environ.get("RP_BASE_URL", "").startswith("https://")


def require_csrf(form, session: BrowserSession) -> None:
    supplied = form.get("csrf_token")
    if not isinstance(supplied, str) or not secrets.compare_digest(supplied, session.csrf_token):
        raise HTTPException(403, "CSRF token недействителен")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    session = request.cookies.get("rp_session")
    if not session or session not in SESSIONS:
        return page("Эталонный клиент", "<p><a href='/login'>Войти через SSO</a></p>")
    user = SESSIONS[session].user
    return page(
        "Эталонный клиент",
        f"<p>Пользователь: <strong>{html.escape(user.preferred_username or user.sub)}</strong></p>"
        "<p><a href='/sensitive'>Чувствительное действие</a> · "
        "<a href='/logout'>Выйти</a></p>",
    )


@app.get("/login")
async def login():
    flow = secrets.token_urlsafe(24)
    oidc = client()
    url, verifier, state, nonce = oidc.start_authorization(
        redirect_uri=os.environ["RP_REDIRECT_URI"],
        scope="openid profile email",
        prompt="login",
    )
    OIDC_FLOWS[flow] = (verifier, state, nonce)
    response = RedirectResponse(url, 302)
    response.set_cookie("oidc_flow", flow, httponly=True, samesite="lax", max_age=300)
    return response


@app.get("/callback")
async def callback(request: Request):
    flow = request.cookies.get("oidc_flow")
    state = request.query_params.get("state", "")
    code = request.query_params.get("code", "")
    if not flow or flow not in OIDC_FLOWS or not code:
        raise HTTPException(400, "Некорректный OIDC callback")
    verifier, expected_state, nonce = OIDC_FLOWS.pop(flow)
    oidc = client()
    try:
        info = await oidc.handle_web_callback(
            code=code,
            state=state,
            expected_state=expected_state,
            code_verifier=verifier,
            redirect_uri=os.environ["RP_REDIRECT_URI"],
            expected_nonce=nonce,
        )
    except SSOError as error:
        return page("Вход отклонён", f"<p>{html.escape(str(error))}</p>")
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = BrowserSession(
        user=info.user,
        access_token=info.access_token,
        id_token=info.id_token,
        refresh_token=info.refresh_token,
    )
    response = RedirectResponse("/", 302)
    response.set_cookie(
        "rp_session", sid, httponly=True, samesite="lax", max_age=3600, secure=cookie_secure()
    )
    response.delete_cookie("oidc_flow")
    return response


@app.get("/sensitive", response_class=HTMLResponse)
async def sensitive(request: Request):
    session = session_for(request)
    return page(
        "Чувствительное действие",
        f"<p>Действие: изменить <code>{html.escape(ACTION)}</code></p>"
        f"<p>Payload: <code>{html.escape(payload_hash())}</code></p>"
        f"<form method='post' action='/step-up'>"
        f"<input type='hidden' name='csrf_token' value='{html.escape(session.csrf_token)}'>"
        "<button type='submit'>Подтвердить в ALXPRGS SSO</button></form>",
    )


@app.post("/step-up")
async def start_step_up(request: Request):
    session = session_for(request)
    require_csrf(await request.form(), session)
    oidc = client()
    try:
        step_up = await oidc.create_step_up_request(
            action=ACTION,
            payload_hash=payload_hash(),
            subject=session.user.sub,
            assurance="reauth_password_mfa",
            redirect_uri=os.environ["RP_STEP_UP_REDIRECT_URI"],
            description="Изменить критическую настройку общего доступа",
            ttl_seconds=120,
        )
    except SSOError as error:
        return page("Step-up недоступен", f"<p>{html.escape(str(error))}</p>")
    STEP_UP_FLOWS[step_up.request_token] = step_up
    response = RedirectResponse(oidc.build_step_up_url(step_up), 302)
    response.set_cookie(
        "step_up_token",
        step_up.request_token,
        httponly=True,
        samesite="lax",
        max_age=300,
        secure=cookie_secure(),
    )
    return response


@app.get("/step-up/callback", response_class=HTMLResponse)
async def step_up_callback(request: Request):
    session = session_for(request)
    token = request.cookies.get("step_up_token", "")
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    step_up = STEP_UP_FLOWS.get(token)
    if not step_up or not code:
        return page("Подтверждение отклонено", "<p>Запрос не найден.</p>")
    try:
        proof = await client().consume_step_up_proof(
            code=code,
            request=step_up,
            state=state,
            expected_subject=session.user.sub,
            expected_action=ACTION,
            expected_payload_hash=payload_hash(),
        )
    except SSOError as error:
        return page("Подтверждение отклонено", f"<p>{html.escape(str(error))}</p>")
    STEP_UP_FLOWS.pop(token, None)
    session.proofs[proof.claims.transaction_id] = proof
    response = RedirectResponse("/sensitive/execute", 302)
    response.delete_cookie("step_up_token")
    return response


@app.get("/sensitive/execute", response_class=HTMLResponse)
async def execute_confirmation(request: Request):
    session = session_for(request)
    if not session.proofs:
        return page("Нет подтверждения", "<p>Сначала пройдите step-up.</p>")
    return page(
        "Подтверждение получено",
        f"<form method='post' action='/sensitive/execute'>"
        f"<input type='hidden' name='csrf_token' value='{html.escape(session.csrf_token)}'>"
        "<button type='submit'>Выполнить действие</button></form>",
    )


@app.post("/sensitive/execute", response_class=HTMLResponse)
async def execute(request: Request):
    session = session_for(request)
    require_csrf(await request.form(), session)
    if session.executed:
        return page("Повтор отклонён", "<p>Действие уже выполнено в этой сессии.</p>")
    proof = next(iter(session.proofs.values()), None)
    if proof is None:
        return page("Нет подтверждения", "<p>Сначала пройдите step-up.</p>")
    if (
        proof.claims.sub != session.user.sub
        or proof.claims.action != ACTION
        or proof.claims.payload_hash != payload_hash()
    ):
        return page("Подтверждение не совпадает", "<p>Операция изменена.</p>")
    # The proof was already atomically consumed by consume_step_up_proof.
    session.executed = True
    return page(
        "Действие выполнено",
        "<p>Настройка изменена только один раз.</p><p><a href='/'>На главную</a></p>",
    )


@app.get("/logout")
async def logout(request: Request):
    sid = request.cookies.get("rp_session")
    if sid:
        SESSIONS.pop(sid, None)
    response = RedirectResponse("/", 302)
    response.delete_cookie("rp_session")
    return response
