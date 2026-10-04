"""Fresh password + configured MFA, bound to one exact mutation and session."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import AuthenticationException
from app.core.security import async_verify_password, generate_random_token, hash_token
from app.models.authentication import SecurityAuthorization
from app.models.session import Session
from app.models.user import User
from app.services.privacy_service import RateLimit, consume_rate_limit, factor_methods
from app.services.security_state import lock_user, require_account_access, revision


def sensitive_action(method: str, path: str) -> bool:
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    if path.startswith("/api/v1/admin/"):
        return True
    return path in {
        "/api/v1/auth/change-password",
        "/api/v1/mfa/totp/setup",
        "/api/v1/mfa/totp/confirm",
        "/api/v1/mfa/totp",
        "/api/v1/mfa/recovery-codes/generate",
        "/api/v1/mfa/passkey/register/options",
        "/api/v1/mfa/passkey/register/verify",
        "/api/v1/mfa/email/request",
    } or (method == "DELETE" and path.startswith("/api/v1/mfa/passkey/"))


def payload_digest(body: bytes) -> str:
    if body:
        value = json.loads(body)
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    else:
        canonical = ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reject() -> AuthenticationException:
    return AuthenticationException(
        "Подтвердите пароль и действующий второй фактор для этой операции",
        error="reauthentication_required",
    )


async def scoped_row(db: AsyncSession, user: User, session: Session, raw: str, stage: str):
    current = await lock_user(db, user.id)
    row = await db.scalar(
        select(SecurityAuthorization)
        .where(
            SecurityAuthorization.token_hash == hash_token(raw),
            SecurityAuthorization.user_id == current.id,
            SecurityAuthorization.session_id == session.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = datetime.now(timezone.utc)
    if (
        row is None
        or row.stage != stage
        or row.expires_at <= now
        or row.failed_attempts >= 5
        or row.security_revision != revision(current)
    ):
        raise reject()
    if not await db.scalar(
        select(Session.id).where(
            Session.id == session.id,
            Session.user_id == current.id,
            Session.security_revision == revision(current),
            Session.expires_at > now,
        )
    ):
        raise reject()
    return row


async def start(
    db: AsyncSession,
    user: User,
    session: Session,
    cfg: Settings,
    password: str,
    action: str,
    digest: str,
) -> dict[str, Any]:
    parts = action.split(" ", 1)
    if (
        len(parts) != 2
        or not sensitive_action(*parts)
        or len(action) > 255
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        raise reject()
    await consume_rate_limit(db, cfg, RateLimit("security-reauth", str(user.id), 5))
    current = await lock_user(db, user.id)
    require_account_access(current, cfg, allow_temporary=session.purpose == "password_change")
    if session.purpose == "password_change" and action != "POST /api/v1/auth/change-password":
        raise reject()
    if not await db.scalar(
        select(Session.id).where(
            Session.id == session.id,
            Session.user_id == current.id,
            Session.security_revision == revision(current),
            Session.expires_at > datetime.now(timezone.utc),
        )
    ):
        raise reject()
    if not current.password_credential or not await async_verify_password(
        password, current.password_credential.password_hash
    ):
        raise reject()
    methods = factor_methods(current, cfg)
    raw = generate_random_token(32)
    row = SecurityAuthorization(
        user_id=current.id,
        session_id=session.id,
        security_revision=revision(current),
        token_hash=hash_token(raw),
        action=action,
        payload_hash=digest,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        stage="factor" if methods else "authorized",
        failed_attempts=0,
    )
    db.add(row)
    options = None
    if "passkey" in methods:
        from app.services.mfa_service import WebAuthnService

        options = await WebAuthnService.get_authentication_options(
            db, current, settings=cfg, purpose="security_reauth", commit=False
        )
        row.webauthn_challenge = options["challenge"]
    await db.commit()
    return {
        "authorization": raw,
        "factor_required": bool(methods),
        "methods": methods,
        "passkey_options": options,
        "expires_at": row.expires_at,
    }


async def confirm(
    db: AsyncSession,
    user: User,
    session: Session,
    cfg: Settings,
    raw: str,
    method: str,
    code: str | None,
    credential: dict | None,
) -> dict[str, Any]:
    await consume_rate_limit(db, cfg, RateLimit("security-factor", str(user.id), 5))
    current = await lock_user(db, user.id)
    row = await scoped_row(db, current, session, raw, "factor")
    methods = factor_methods(current, cfg)
    from app.services.mfa_service import RecoveryCodesService, TOTPService, WebAuthnService

    valid = False
    if method in methods:
        try:
            if method == "totp" and code:
                valid = await TOTPService.verify_totp(db, current, code, commit=False)
            elif method == "recovery_code" and code:
                valid = await RecoveryCodesService.consume_code(db, current, code, commit=False)
            elif method == "passkey" and credential:
                valid = await WebAuthnService.verify_authentication(
                    db,
                    current,
                    credential,
                    settings=cfg,
                    purpose="security_reauth",
                    expected_challenge=row.webauthn_challenge,
                    commit=False,
                )
        except AuthenticationException:
            valid = False
    if not valid:
        row.failed_attempts += 1
        await db.commit()
        raise reject()
    authorized = generate_random_token(32)
    row.token_hash = hash_token(authorized)
    row.stage = "authorized"
    await db.commit()
    return {"authorization": authorized, "factor_required": False, "expires_at": row.expires_at}


async def consume(db: AsyncSession, user: User, session: Session, request: Request) -> None:
    raw = request.headers.get("X-Reauthentication", "")
    if not raw or len(raw) > 256:
        raise reject()
    row = await scoped_row(db, user, session, raw, "authorized")
    if row.action != f"{request.method} {request.url.path}" or row.payload_hash != payload_digest(
        await request.body()
    ):
        raise reject()
    await db.execute(delete(SecurityAuthorization).where(SecurityAuthorization.id == row.id))
    # Deliberately no commit: proof consumption and the mutation share one transaction.
