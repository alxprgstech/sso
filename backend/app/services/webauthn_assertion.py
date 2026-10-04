from __future__ import annotations

import json


import uuid

from dataclasses import dataclass

from datetime import datetime, timezone

from typing import Any


import webauthn

from sqlalchemy import select


from sqlalchemy.ext.asyncio import AsyncSession


from app.core.exceptions import (
    AuthenticationException,
)


from app.models.mfa import (
    WebAuthnChallenge,
    WebAuthnCredential,
)


def _cred_id_to_bytes(cred_id: str) -> bytes:
    try:
        return webauthn.helpers.base64url_to_bytes(cred_id)
    except Exception:
        return cred_id.encode("utf-8")


@dataclass(frozen=True)
class AssertionPolicy:
    rp_id: str
    origins: list[str]
    purpose: str
    expected_challenge: str | None


def assertion_dictionary(credential: str | dict[str, Any]) -> dict[str, Any]:
    return json.loads(credential) if isinstance(credential, str) else credential


async def locked_assertion_credential(
    db: AsyncSession, user_id: uuid.UUID, assertion: dict[str, Any]
) -> WebAuthnCredential:
    raw_id = assertion.get("id") or assertion.get("rawId")
    if not raw_id:
        raise AuthenticationException("Отсутствует идентификатор ключа Passkey (id)")
    credentials = (
        (
            await db.execute(
                select(WebAuthnCredential)
                .where(
                    WebAuthnCredential.user_id == user_id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if not credentials:
        raise AuthenticationException("У пользователя отсутствуют зарегистрированные ключи Passkey")
    for credential in credentials:
        if credential.credential_id == raw_id or _cred_id_to_bytes(
            credential.credential_id
        ) == _cred_id_to_bytes(raw_id):
            return credential
    raise AuthenticationException("Ключ доступа Passkey не найден или был удалён")


def signed_assertion_challenge(assertion: dict[str, Any], policy: AssertionPolicy) -> str | None:
    try:
        raw = assertion.get("response", {}).get("clientDataJSON")
        if not raw:
            return None
        client_data = json.loads(webauthn.helpers.base64url_to_bytes(raw).decode("utf-8"))
        challenge = client_data.get("challenge")
    except (ValueError, TypeError, AttributeError):
        return None
    if policy.expected_challenge is not None:
        if challenge != policy.expected_challenge:
            return None
    return challenge


async def locked_assertion_challenge(
    db: AsyncSession, user_id: uuid.UUID, assertion: dict[str, Any], policy: AssertionPolicy
) -> WebAuthnChallenge:
    signed = signed_assertion_challenge(assertion, policy)
    query = select(WebAuthnChallenge).where(
        WebAuthnChallenge.purpose == policy.purpose,
        WebAuthnChallenge.expires_at > datetime.now(timezone.utc),
    )
    row = None
    if signed:
        row = await db.scalar(query.where(WebAuthnChallenge.challenge == signed).with_for_update())
    if row is None:
        row = await authentication_fallback_challenge(db, user_id, policy)
    if row is None:
        raise AuthenticationException("Срок действия challenge истёк или challenge не найден")
    if row.user_id is not None:
        if row.user_id != user_id:
            raise AuthenticationException("Срок действия challenge истёк или challenge не найден")
    return row


async def authentication_fallback_challenge(
    db: AsyncSession, user_id: uuid.UUID, policy: AssertionPolicy
) -> WebAuthnChallenge | None:
    # Only ordinary authentication supports the legacy latest-challenge lookup.
    # Action-bound deletion proofs never enter this fallback.
    if policy.purpose != "authentication":
        return None
    if policy.expected_challenge is not None:
        return None
    return await db.scalar(
        select(WebAuthnChallenge)
        .where(
            WebAuthnChallenge.user_id == user_id,
            WebAuthnChallenge.purpose == policy.purpose,
            WebAuthnChallenge.expires_at > datetime.now(timezone.utc),
        )
        .order_by(WebAuthnChallenge.created_at.desc())
        .with_for_update()
    )


def verify_assertion_signature(
    credential: str | dict[str, Any],
    target: WebAuthnCredential,
    challenge: WebAuthnChallenge,
    policy: AssertionPolicy,
) -> int:
    try:
        verification = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=webauthn.helpers.base64url_to_bytes(challenge.challenge),
            expected_rp_id=policy.rp_id,
            expected_origin=policy.origins,
            credential_public_key=bytes.fromhex(target.public_key),
            credential_current_sign_count=target.sign_count,
            require_user_verification=True,
        )
    except Exception:
        raise AuthenticationException("Ошибка проверки аутентификации WebAuthn") from None
    return verification.new_sign_count
