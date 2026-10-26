"""Hosted, transaction-bound step-up authorization and one-use proof redemption."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import AuthenticationException, StepUpError
from app.core.security import (
    async_verify_password,
    create_jwt,
    generate_random_token,
    hash_token,
    verify_pkce,
)
from app.core.urls import validate_redirect
from app.models.oidc import OIDCClient
from app.models.session import Session
from app.models.step_up import ExternalStepUpRequest
from app.models.user import User
from app.schemas.step_up import StepUpRequestCreate
from app.services.audit_service import AuditService
from app.services.privacy_service import RateLimit, consume_rate_limit
from app.services.security_state import lock_user, require_account_access, revision
from app.services.step_up_policy import (
    ASSURANCE_LABELS,
    AssurancePlan,
    amr_for,
    available_factors,
    client_policy_allows,
    parse_client_actions,
    parse_client_levels,
    plan_for_id,
    plan_is_satisfied,
    plans_for,
    verified_methods,
)


def _forbidden(error: str, detail: str, status_code: int = 403) -> StepUpError:
    return StepUpError(error, detail, status_code)


def _request_hash(raw: str) -> str:
    return hash_token(raw)


def _authorization_url(settings: Settings, raw_request: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/step-up/{quote(raw_request, safe='')}"


def _plans_payload(plans: tuple[AssurancePlan, ...]) -> list[dict[str, Any]]:
    return [{"id": plan.id, "label": plan.label, "methods": list(plan.methods)} for plan in plans]


def _ensure_feature(settings: Settings) -> None:
    if not settings.FEATURE_EXTERNAL_STEP_UP_ENABLED:
        raise StepUpError(
            "feature_disabled",
            "Внешнее подтверждение действий отключено конфигурацией сервера",
            status.HTTP_404_NOT_FOUND,
        )


async def _require_live_session(
    db: AsyncSession, user: User, session_id: Any, settings: Settings, now: datetime
) -> None:
    idle_cutoff = now - timedelta(seconds=settings.SESSION_IDLE_TIMEOUT_SECONDS)
    found = await db.scalar(
        select(Session.id).where(
            Session.id == session_id,
            Session.user_id == user.id,
            Session.security_revision == revision(user),
            Session.expires_at > now,
            Session.last_activity_at > idle_cutoff,
        )
    )
    if found is None:
        raise _forbidden(
            "step_up_session_invalid",
            "Сессия SSO больше не действительна. Запросите подтверждение заново.",
            409,
        )


async def _validate_redirect(client: OIDCClient, redirect_uri: str, settings: Settings) -> None:
    try:
        validate_redirect(
            redirect_uri,
            local=settings.REDIRECT_TRANSPORT_PROFILE == "local"
            and settings.ENVIRONMENT != "production",
        )
    except ValueError:
        raise StepUpError("invalid_redirect_uri", "Недопустимый redirect_uri") from None
    if redirect_uri not in {entry.uri for entry in client.redirect_uris}:
        raise StepUpError(
            "invalid_redirect_uri", "redirect_uri не зарегистрирован для этого клиента"
        )


def _redirect_with_code(row: ExternalStepUpRequest, raw_code: str, settings: Settings) -> str:
    parsed = urlsplit(row.redirect_uri)
    parameters = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"code", "state", "iss", "error", "error_description"}
    ]
    parameters.extend([("code", raw_code), ("state", row.state), ("iss", settings.OIDC_ISSUER)])
    return urlunsplit(parsed._replace(query=urlencode(parameters)))


async def create_request(
    db: AsyncSession,
    client: OIDCClient,
    payload: StepUpRequestCreate,
    settings: Settings,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Create a browser challenge for one exact client action.

    Client authentication and redirect registration happened before this call.
    The caller's client is still re-checked against its server-owned policy here.
    """
    _ensure_feature(settings)
    if client.client_type != "confidential" or not client.step_up_enabled:
        raise _forbidden(
            "step_up_not_enabled",
            "Для этого клиента внешнее подтверждение действий не разрешено",
        )
    ttl = min(
        payload.ttl_seconds,
        int(settings.STEP_UP_REQUEST_TTL_SECONDS),
        int(client.step_up_max_ttl_seconds or 0),
    )
    if ttl < 30 or not client_policy_allows(client, payload.assurance, payload.action, ttl):
        raise _forbidden(
            "step_up_policy_denied",
            "Клиент не вправе запрашивать этот уровень или действие",
        )
    await _validate_redirect(client, payload.redirect_uri, settings)

    # Rate limits are persisted before password/MFA work and are shared across
    # workers.  A source that knows a client id cannot exhaust another source.
    await consume_rate_limit(
        db, settings, RateLimit("step-up-create-source", ip_address or "unknown", 60)
    )
    await consume_rate_limit(db, settings, RateLimit("step-up-create-client", str(client.id), 60))
    await consume_rate_limit(
        db, settings, RateLimit("step-up-create-subject", str(payload.subject), 10)
    )

    now = datetime.now(timezone.utc)
    try:
        current = await lock_user(db, payload.subject)
    except AuthenticationException:
        raise StepUpError("invalid_subject", "Указанный пользователь недоступен") from None
    if not current.is_active or current.deletion_scheduled_for:
        raise _forbidden("invalid_subject", "Указанный пользователь недоступен")
    try:
        require_account_access(current, settings)
    except AuthenticationException:
        raise _forbidden("invalid_subject", "Указанный пользователь недоступен") from None

    plans = plans_for(payload.assurance, current, settings)
    if not plans:
        raise _forbidden(
            "assurance_unavailable",
            "У пользователя нет подходящего настроенного способа подтверждения",
        )

    pending_for_user = await db.scalar(
        select(func.count(ExternalStepUpRequest.id)).where(
            ExternalStepUpRequest.user_id == current.id,
            ExternalStepUpRequest.status == "pending",
            ExternalStepUpRequest.expires_at > now,
        )
    )
    if int(pending_for_user or 0) >= settings.STEP_UP_MAX_PENDING_PER_USER:
        raise StepUpError(
            "step_up_pending_limit",
            "Слишком много незавершённых подтверждений. Завершите или отмените предыдущее.",
            429,
        )
    pending_for_client = await db.scalar(
        select(func.count(ExternalStepUpRequest.id)).where(
            ExternalStepUpRequest.client_id == client.id,
            ExternalStepUpRequest.status == "pending",
            ExternalStepUpRequest.expires_at > now,
        )
    )
    if int(pending_for_client or 0) >= settings.STEP_UP_MAX_PENDING_PER_CLIENT:
        raise StepUpError(
            "step_up_pending_limit",
            "Клиент временно исчерпал лимит незавершённых подтверждений",
            429,
        )

    raw_request = generate_random_token(32)
    row = ExternalStepUpRequest(
        client_id=client.id,
        user_id=current.id,
        security_revision=revision(current),
        request_token_hash=_request_hash(raw_request),
        redirect_uri=payload.redirect_uri,
        state=payload.state,
        code_challenge=payload.code_challenge,
        code_challenge_method=payload.code_challenge_method,
        nonce=payload.nonce,
        action=payload.action,
        description=payload.description,
        payload_hash=payload.payload_hash,
        assurance=payload.assurance,
        status="pending",
        failed_attempts=0,
        expires_at=now + timedelta(seconds=ttl),
    )
    db.add(row)
    await AuditService.log_event(
        db,
        event_type="external_step_up_requested",
        user_id=current.id,
        ip_address=ip_address,
        details={
            "client_id": str(client.id),
            "action": payload.action,
            "assurance": payload.assurance,
        },
        commit=False,
    )
    await db.commit()
    return {
        "request_token": raw_request,
        "authorization_url": _authorization_url(settings, raw_request),
        "client_name": client.client_name,
        "action": payload.action,
        "description": payload.description,
        "payload_hash": payload.payload_hash,
        "assurance": payload.assurance,
        "assurance_label": ASSURANCE_LABELS[payload.assurance],
        "plans": _plans_payload(plans),
        "expires_at": row.expires_at,
    }


async def _load_request(
    db: AsyncSession, raw_request: str, *, lock: bool = True
) -> ExternalStepUpRequest | None:
    statement = select(ExternalStepUpRequest).where(
        ExternalStepUpRequest.request_token_hash == _request_hash(raw_request)
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(statement)


async def _bound_request(
    db: AsyncSession,
    user: User,
    session: Session,
    raw_request: str,
    settings: Settings,
) -> tuple[User, ExternalStepUpRequest, bool]:
    """Lock and validate the account/browser/action binding."""
    current = await lock_user(db, user.id)
    row = await _load_request(db, raw_request)
    if row is None:
        raise StepUpError("step_up_not_found", "Запрос не найден", 404)
    now = datetime.now(timezone.utc)
    if row.user_id != current.id:
        await AuditService.log_event(
            db,
            event_type="external_step_up_subject_mismatch",
            user_id=current.id,
            details={"client_id": str(row.client_id)},
            commit=False,
        )
        await db.commit()
        raise _forbidden(
            "step_up_subject_mismatch",
            "Запрос относится к другой учётной записи. Войдите под нужным пользователем.",
        )
    if not current.is_active or current.deletion_scheduled_for:
        raise _forbidden(
            "step_up_invalidated", "Учётная запись больше не допускает подтверждение", 409
        )
    try:
        require_account_access(current, settings)
    except AuthenticationException:
        raise _forbidden(
            "step_up_invalidated", "Учётная запись больше не допускает подтверждение", 409
        ) from None
    if row.security_revision != revision(current):
        await AuditService.log_event(
            db,
            event_type="external_step_up_invalidated",
            user_id=current.id,
            details={"client_id": str(row.client_id)},
            commit=False,
        )
        await db.commit()
        raise _forbidden(
            "step_up_invalidated",
            "Настройки безопасности аккаунта изменились. Запросите подтверждение заново.",
            409,
        )
    client = await db.scalar(select(OIDCClient).where(OIDCClient.id == row.client_id))
    if (
        client is None
        or not client.is_active
        or not client.step_up_enabled
        or row.redirect_uri not in {entry.uri for entry in client.redirect_uris}
        or row.action not in parse_client_actions(client.step_up_actions or "")
        or row.assurance not in parse_client_levels(client.step_up_assurance_levels or "")
    ):
        await AuditService.log_event(
            db,
            event_type="external_step_up_client_policy_changed",
            user_id=current.id,
            details={"client_id": str(row.client_id)},
            commit=False,
        )
        await db.commit()
        raise _forbidden(
            "step_up_client_policy_changed",
            "Разрешение приложения изменено. Запросите подтверждение заново.",
            409,
        )
    if row.expires_at <= now:
        raise _forbidden(
            "step_up_expired",
            "Срок действия запроса истёк. Запросите подтверждение заново.",
            410,
        )
    if row.status != "pending":
        if row.status == "denied":
            raise _forbidden("step_up_denied", "Действие отменено", 410)
        if row.status == "approved":
            raise _forbidden("step_up_already_completed", "Подтверждение уже завершено", 409)
        raise _forbidden("step_up_consumed", "Подтверждение уже использовано", 409)
    await _require_live_session(db, current, session.id, settings, now)
    bound_now = False
    if row.session_id is None:
        row.session_id = session.id
        bound_now = True
    elif row.session_id != session.id:
        await AuditService.log_event(
            db,
            event_type="external_step_up_session_mismatch",
            user_id=current.id,
            details={"client_id": str(row.client_id)},
            commit=False,
        )
        await db.commit()
        raise _forbidden(
            "step_up_session_mismatch",
            "Подтверждение начато в другой сессии. Запросите его заново.",
            409,
        )
    return current, row, bound_now


def _plan_or_error(
    row: ExternalStepUpRequest, plan_id: str, user: User, settings: Settings
) -> AssurancePlan:
    plan = plan_for_id(row.assurance, plan_id, user, settings)
    if plan is None:
        raise StepUpError("step_up_plan_unavailable", "Выбранный способ подтверждения недоступен")
    if row.plan is not None and row.plan != plan.id:
        raise StepUpError(
            "step_up_plan_locked",
            "Способ подтверждения уже выбран. Запросите подтверждение заново.",
            409,
        )
    return plan


async def details(
    db: AsyncSession,
    user: User,
    session: Session,
    raw_request: str,
    settings: Settings,
) -> dict[str, Any]:
    current, row, bound_now = await _bound_request(db, user, session, raw_request, settings)
    client = await db.scalar(select(OIDCClient).where(OIDCClient.id == row.client_id))
    if client is None or not client.is_active:
        raise _forbidden("step_up_client_inactive", "Доверенное приложение больше недоступно", 409)
    plans = plans_for(row.assurance, current, settings)
    if bound_now:
        await AuditService.log_event(
            db,
            event_type="external_step_up_viewed",
            user_id=current.id,
            details={"client_id": str(client.id), "assurance": row.assurance},
            commit=False,
        )
        await db.commit()
    return {
        "client_name": client.client_name,
        "action": row.action,
        "description": row.description,
        "payload_hash": row.payload_hash,
        "assurance": row.assurance,
        "assurance_label": ASSURANCE_LABELS[row.assurance],
        "plans": _plans_payload(plans),
        "verified_methods": verified_methods(row),
        "plan": row.plan,
        "status": row.status,
        "passkey_enabled": bool(
            settings.FEATURE_PASSKEY_ENABLED and available_factors(current, settings).passkey
        ),
        "expires_at": row.expires_at,
    }


async def passkey_options(
    db: AsyncSession,
    user: User,
    session: Session,
    raw_request: str,
    plan_id: str,
    settings: Settings,
) -> dict[str, Any]:
    current, row, _ = await _bound_request(db, user, session, raw_request, settings)
    plan = _plan_or_error(row, plan_id, current, settings)
    if "passkey" not in plan.methods:
        raise StepUpError("step_up_plan_unavailable", "Passkey не входит в выбранный способ")
    if row.passkey_verified_at is not None:
        raise StepUpError("step_up_factor_already_verified", "Passkey уже подтверждён")
    if not settings.FEATURE_PASSKEY_ENABLED or not current.webauthn_credentials:
        raise StepUpError("step_up_factor_unavailable", "Passkey не настроен или отключён", 403)
    from app.services.mfa_service import PasskeyAuthentication, WebAuthnContext, WebAuthnService

    options = await WebAuthnService.get_authentication_options(
        db,
        current,
        operation=PasskeyAuthentication(
            trust=WebAuthnContext(settings=settings),
            purpose="external_step_up",
            commit=False,
        ),
    )
    row.plan = plan.id
    row.webauthn_challenge = options["challenge"]
    await db.commit()
    return options


async def _reject_factor(
    db: AsyncSession, row: ExternalStepUpRequest, user: User, settings: Settings
) -> None:
    row.failed_attempts += 1
    if row.failed_attempts >= settings.STEP_UP_MAX_FAILED_ATTEMPTS:
        row.status = "denied"
    await AuditService.log_event(
        db,
        event_type="external_step_up_factor_rejected",
        user_id=user.id,
        details={"client_id": str(row.client_id)},
        commit=False,
    )
    await db.commit()
    raise StepUpError("step_up_factor_rejected", "Не удалось подтвердить выбранный фактор", 401)


async def _verify_password(
    db: AsyncSession,
    current: User,
    row: ExternalStepUpRequest,
    password: str | None,
    settings: Settings,
) -> None:
    credential = current.password_credential
    if not password or credential is None:
        await _reject_factor(db, row, current, settings)
        return
    if not await async_verify_password(password, credential.password_hash):
        await _reject_factor(db, row, current, settings)


async def _verify_totp(
    db: AsyncSession,
    current: User,
    row: ExternalStepUpRequest,
    code: str | None,
    settings: Settings,
) -> None:
    from app.services.totp_service import TOTPService

    if not code or not settings.FEATURE_TOTP_ENABLED:
        await _reject_factor(db, row, current, settings)
        return
    try:
        valid = await TOTPService.verify_totp(db, current, code, commit=False)
    except AuthenticationException:
        valid = False
    if not valid:
        await _reject_factor(db, row, current, settings)


async def _verify_passkey(
    db: AsyncSession,
    current: User,
    row: ExternalStepUpRequest,
    credential: dict[str, Any] | None,
    settings: Settings,
) -> None:
    from app.services.mfa_service import PasskeyAuthentication, WebAuthnContext, WebAuthnService

    if not credential or not settings.FEATURE_PASSKEY_ENABLED or not row.webauthn_challenge:
        await _reject_factor(db, row, current, settings)
        return
    try:
        valid = await WebAuthnService.verify_authentication(
            db,
            current,
            credential,
            operation=PasskeyAuthentication(
                trust=WebAuthnContext(settings=settings),
                purpose="external_step_up",
                expected_challenge=row.webauthn_challenge,
                commit=False,
            ),
        )
    except AuthenticationException:
        valid = False
    if not valid:
        await _reject_factor(db, row, current, settings)


async def verify(
    db: AsyncSession,
    user: User,
    session: Session,
    raw_request: str,
    plan_id: str,
    method: str,
    settings: Settings,
    password: str | None = None,
    code: str | None = None,
    credential: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await consume_rate_limit(
        db,
        settings,
        RateLimit("step-up-verify", str(user.id), settings.STEP_UP_RATE_LIMIT_PER_MINUTE),
    )
    current, row, _ = await _bound_request(db, user, session, raw_request, settings)
    plan = _plan_or_error(row, plan_id, current, settings)
    if method not in plan.methods:
        raise StepUpError("step_up_method_not_allowed", "Этот способ не входит в подтверждение")
    if "password" in plan.methods and method != "password" and row.password_verified_at is None:
        raise StepUpError("step_up_factor_order", "Сначала подтвердите текущий пароль", 409)
    if getattr(row, f"{method}_verified_at") is not None:
        raise StepUpError("step_up_factor_already_verified", "Этот фактор уже подтверждён")
    if method == "password":
        await _verify_password(db, current, row, password, settings)
        row.password_verified_at = datetime.now(timezone.utc)
    elif method == "totp":
        await _verify_totp(db, current, row, code, settings)
        row.totp_verified_at = datetime.now(timezone.utc)
    elif method == "passkey":
        await _verify_passkey(db, current, row, credential, settings)
        row.passkey_verified_at = datetime.now(timezone.utc)
        row.webauthn_challenge = None
    else:
        raise StepUpError("step_up_method_not_allowed", "Неизвестный способ подтверждения")
    row.plan = plan.id

    if not plan_is_satisfied(row, plan):
        await db.commit()
        return {
            "completed": False,
            "status": "pending",
            "verified_methods": verified_methods(row),
            "remaining_methods": [
                item for item in plan.methods if item not in set(verified_methods(row))
            ],
            "redirect_to": None,
            "expires_at": row.expires_at,
        }

    now = datetime.now(timezone.utc)
    raw_code = generate_random_token(32)
    row.status = "approved"
    row.approved_at = now
    row.proof_token_hash = hash_token(raw_code)
    row.proof_expires_at = min(
        now + timedelta(seconds=settings.STEP_UP_PROOF_TTL_SECONDS), row.expires_at
    )
    await AuditService.log_event(
        db,
        event_type="external_step_up_approved",
        user_id=current.id,
        details={
            "client_id": str(row.client_id),
            "assurance": row.assurance,
            "methods": list(verified_methods(row)),
        },
        commit=False,
    )
    await db.commit()
    return {
        "completed": True,
        "status": "approved",
        "verified_methods": verified_methods(row),
        "remaining_methods": [],
        "redirect_to": _redirect_with_code(row, raw_code, settings),
        "expires_at": row.expires_at,
    }


async def deny(
    db: AsyncSession,
    user: User,
    session: Session,
    raw_request: str,
    settings: Settings,
) -> dict[str, str]:
    current, row, _ = await _bound_request(db, user, session, raw_request, settings)
    if row.status != "pending":
        raise StepUpError("step_up_not_pending", "Запрос уже завершён", 409)
    row.status = "denied"
    await AuditService.log_event(
        db,
        event_type="external_step_up_denied",
        user_id=current.id,
        details={"client_id": str(row.client_id)},
        commit=False,
    )
    await db.commit()
    return {"status": "denied"}


async def redeem(
    db: AsyncSession,
    client: OIDCClient,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    settings: Settings,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Atomically consume one proof; the returned JWT is evidence, not a grant."""
    _ensure_feature(settings)
    if client.client_type != "confidential" or not client.step_up_enabled:
        raise _forbidden(
            "step_up_not_enabled",
            "Для этого клиента внешнее подтверждение действий не разрешено",
        )
    await consume_rate_limit(
        db, settings, RateLimit("step-up-redeem-source", ip_address or "unknown", 60)
    )
    await consume_rate_limit(db, settings, RateLimit("step-up-redeem-client", str(client.id), 60))
    now = datetime.now(timezone.utc)
    proof_hash = hash_token(code)
    candidate = await db.scalar(
        select(ExternalStepUpRequest.user_id).where(
            ExternalStepUpRequest.proof_token_hash == proof_hash
        )
    )
    if candidate is None:
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400)
    try:
        current = await lock_user(db, candidate)
    except AuthenticationException:
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400) from None
    row = await db.scalar(
        select(ExternalStepUpRequest)
        .where(ExternalStepUpRequest.proof_token_hash == proof_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400)
    if row.consumed_at is not None:
        await AuditService.log_event(
            db,
            event_type="external_step_up_replay_detected",
            user_id=current.id,
            details={"client_id": str(row.client_id)},
            commit=False,
        )
        await db.commit()
        raise StepUpError("proof_replayed", "Подтверждение уже использовано", 409)
    if (
        row.status != "approved"
        or row.proof_expires_at is None
        or row.proof_expires_at <= now
        or row.expires_at <= now
    ):
        raise StepUpError("proof_expired", "Срок подтверждения истёк", 410)
    if row.client_id != client.id:
        await AuditService.log_event(
            db,
            event_type="external_step_up_client_mismatch",
            user_id=current.id,
            details={"client_id": str(row.client_id)},
            commit=False,
        )
        await db.commit()
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400)
    if row.redirect_uri != redirect_uri or row.redirect_uri not in {
        entry.uri for entry in client.redirect_uris
    }:
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400)
    if not verify_pkce(code_verifier, row.code_challenge, row.code_challenge_method):
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400)
    if row.action not in parse_client_actions(
        client.step_up_actions or ""
    ) or row.assurance not in parse_client_levels(client.step_up_assurance_levels or ""):
        raise _forbidden("step_up_policy_denied", "Политика клиента больше не допускает действие")
    if not current.is_active or current.deletion_scheduled_for:
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400)
    try:
        require_account_access(current, settings)
    except AuthenticationException:
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400) from None
    if row.security_revision != revision(current):
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400)
    if row.session_id is None:
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400)
    await _require_live_session(db, current, row.session_id, settings, now)

    plan = plan_for_id(row.assurance, row.plan or "", current, settings)
    if plan is None or not plan_is_satisfied(row, plan):
        raise StepUpError("invalid_grant", "Подтверждение недействительно", 400)
    row.consumed_at = now
    row.status = "consumed"
    ttl_seconds = max(1, int((row.proof_expires_at - now).total_seconds()))
    claims = {
        "sub": str(current.id),
        "aud": client.client_id,
        "token_use": "external_step_up_proof",
        "jti": str(uuid.uuid4()),
        "transaction_id": str(row.id),
        "action": row.action,
        "payload_hash": row.payload_hash,
        "acr": row.assurance,
        "amr": amr_for(row, plan),
        "auth_time": int((row.approved_at or now).timestamp()),
        "nonce": row.nonce,
        "security_revision": revision(current),
    }
    proof = create_jwt(claims, expires_in_seconds=ttl_seconds)
    await AuditService.log_event(
        db,
        event_type="external_step_up_proof_redeemed",
        user_id=current.id,
        ip_address=ip_address,
        details={"client_id": str(client.id), "assurance": row.assurance},
        commit=False,
    )
    await db.commit()
    return {"proof": proof, "claims": claims}
