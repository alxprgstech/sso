"""Native Resend submission, using the existing MIME message and safe error contract."""

from __future__ import annotations

import logging
import uuid
from email.message import EmailMessage

import httpx

from app.config import Settings
from app.services.ses_email import SESEmailDeliveryError

logger = logging.getLogger(__name__)
ENDPOINT = "https://api.resend.com/emails"


def _payload(message: EmailMessage) -> dict[str, object]:
    payload: dict[str, object] = {
        "from": str(message["From"]),
        "to": [str(message["To"])],
        "subject": str(message["Subject"]),
    }
    for subtype, field in (("plain", "text"), ("html", "html")):
        body = message.get_body(preferencelist=(subtype,))
        if body is not None:
            payload[field] = body.get_content()
    return payload


def _failure_reason(response: httpx.Response) -> str | None:
    if response.is_success:
        return None
    if response.status_code == 429:
        return "quota_exceeded"
    if response.status_code >= 500:
        return "temporary_unavailable"
    if response.status_code in {400, 422}:
        return "message_rejected"
    if response.status_code == 403:
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("name") == "validation_error":
            return "message_rejected"
    if response.status_code in {401, 403}:
        return "access_denied"
    return "failed"


def _accepted_id(response: httpx.Response) -> str | None:
    try:
        data = response.json()
        value = data.get("id") if isinstance(data, dict) else None
        # Only an actual UUID may enter the acceptance log, never arbitrary upstream text.
        if isinstance(value, str) and str(uuid.UUID(value)) == value:
            return value
    except (ValueError, AttributeError):
        pass
    return None


async def _submit(
    message: EmailMessage, settings: Settings, client: httpx.AsyncClient
) -> tuple[str | None, str | None]:
    try:
        response = await client.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY.get_secret_value()}",
                "User-Agent": "alxprgs-sso",
                "Accept": "application/json",
            },
            json=_payload(message),
            timeout=5,
            follow_redirects=False,
        )
        reason = _failure_reason(response)
        if reason:
            return None, reason
        message_id = _accepted_id(response)
        return message_id, None if message_id else "invalid_response"
    except httpx.RequestError:
        # Do not retain the request/response or chained exception containing secrets.
        return None, "temporary_unavailable"


async def send_resend_email(
    message: EmailMessage, settings: Settings, *, client: httpx.AsyncClient | None = None
) -> str:
    """Return an acceptance ID; no retry, fallback, or delivery confirmation."""
    if client is None:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as active_client:
            message_id, reason = await _submit(message, settings, active_client)
    else:
        message_id, reason = await _submit(message, settings, client)
    if reason or message_id is None:
        raise SESEmailDeliveryError(reason or "invalid_response")
    logger.info("resend_email_accepted message_id=%s", message_id)
    return message_id
