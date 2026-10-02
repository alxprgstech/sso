from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import ipaddress
import json
import secrets
import smtplib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr
from urllib.parse import quote

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import Request

from app.config import Settings
from app.core.rate_limit import get_client_ip, is_trusted_proxy
from app.core.security import generate_random_token, hash_token
from app.services.ses_email import SESEmailDeliveryError, send_ses_email

CODE_TTL_SECONDS = 600
MAX_CODE_ATTEMPTS = 5
MAX_SENDS = 3


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_link() -> str:
    return generate_random_token(32)


def code_hash(settings: Settings, challenge_id: uuid.UUID, code: str) -> str:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"alxprgs-email-code-v1",
    ).derive(settings.SESSION_SECRET_KEY.encode("utf-8"))
    return hmac.new(key, f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def code_matches(settings: Settings, challenge_id: uuid.UUID, code: str, digest: str) -> bool:
    return hmac.compare_digest(code_hash(settings, challenge_id, code), digest)


def request_details(request: Request, settings: Settings) -> dict[str, str]:
    peer = request.client.host if request.client else ""
    agent = (request.headers.get("User-Agent") or "")[:512]
    lower_agent = agent.lower()
    os_name = next(
        (
            name
            for marker, name in (
                ("windows", "Windows"),
                ("android", "Android"),
                ("iphone", "iOS"),
                ("ipad", "iOS"),
                ("mac os", "macOS"),
                ("linux", "Linux"),
            )
            if marker in lower_agent
        ),
        "Неизвестно",
    )
    browser = next(
        (
            name
            for marker, name in (
                ("edg/", "Edge"),
                ("firefox/", "Firefox"),
                ("chrome/", "Chrome"),
                ("safari/", "Safari"),
            )
            if marker in lower_agent
        ),
        "Неизвестно",
    )
    device = (
        "Телефон"
        if "mobile" in lower_agent
        else "Планшет"
        if "tablet" in lower_agent
        else "Компьютер"
    )
    details = {
        "ip": get_client_ip(request, settings.TRUSTED_PROXIES),
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "os": os_name,
        "browser": browser,
        "device": device,
        "city": "Неизвестно",
        "country": "Неизвестно",
    }
    if is_trusted_proxy(peer, settings.TRUSTED_PROXIES):
        # The ingress must remove client-supplied X-ALX-Geo-* headers before forwarding.
        for field in ("city", "country"):
            value = request.headers.get(f"X-ALX-Geo-{field.title()}", "")
            if value and len(value) <= 80 and value.isprintable():
                details[field] = value
    try:
        ipaddress.ip_address(details["ip"])
    except ValueError:
        details["ip"] = "Неизвестно"
    return details


def _detail_lines(details: dict[str, str]) -> list[tuple[str, str]]:
    return [
        ("Время", details.get("time", "Неизвестно")),
        ("IP", details.get("ip", "Неизвестно")),
        ("Примерный город", details.get("city", "Неизвестно")),
        ("Страна", details.get("country", "Неизвестно")),
        ("Система", details.get("os", "Неизвестно")),
        ("Браузер", details.get("browser", "Неизвестно")),
        ("Устройство", details.get("device", "Неизвестно")),
    ]


def build_message(
    *,
    to_email: str,
    username: str,
    code: str,
    link: str,
    action_url: str | None,
    details: dict[str, str],
    settings: Settings,
) -> EmailMessage:
    subject = "Код подтверждения ALXPRGS"
    text_details = "\n".join(f"{label}: {value}" for label, value in _detail_lines(details))
    text_body = (
        f"Здравствуйте, {username}!\n\n"
        f"Ваш код подтверждения: {code}\n"
        f"Он действует 10 минут. Введите код на сайте или подтвердите адрес по ссылке:\n{link}\n\n"
        "Сведения о запросе (определены приблизительно):\n"
        f"{text_details}\n\n"
        "Если это были не вы, проигнорируйте письмо. Никому не сообщайте код.\n"
    )
    safe_username = html.escape(username)
    safe_link = html.escape(link, quote=True)
    safe_code = html.escape(code)
    rows = "".join(
        f"<tr><td style='padding:5px 16px;color:#64748b'>{html.escape(label)}</td>"
        f"<td style='padding:5px 16px;color:#0f172a'>{html.escape(value)}</td></tr>"
        for label, value in _detail_lines(details)
    )
    schema_data: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "EmailMessage",
        "description": "Подтверждение адреса электронной почты ALXPRGS",
    }
    if action_url:
        schema_data["potentialAction"] = {
            "@type": "ConfirmAction",
            "name": "Подтвердить адрес",
            "handler": {"@type": "HttpActionHandler", "url": action_url},
        }
    schema = (
        '<script type="application/ld+json">'
        + json.dumps(schema_data, ensure_ascii=False).replace("<", "\\u003c")
        + "</script>"
    )
    html_body = (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"{schema}</head><body style='margin:0;background:#f1f5f9;font-family:Arial,sans-serif'>"
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0'><tr><td align='center' style='padding:32px 12px'>"
        "<table role='presentation' width='100%' style='max-width:560px;background:#fff;border-radius:18px' cellpadding='0' cellspacing='0'>"
        "<tr><td style='padding:32px'>"
        "<div style='font-weight:bold;color:#2563eb;font-size:22px'>ALXPRGS</div>"
        "<h1 style='font-size:24px;color:#0f172a'>Подтвердите почту</h1>"
        f"<p style='color:#334155'>Здравствуйте, {safe_username}! Введите этот код на сайте:</p>"
        f"<p style='font-size:36px;letter-spacing:10px;font-weight:bold;color:#0f172a'>{safe_code}</p>"
        "<p style='color:#64748b'>Код и ссылка действуют 10 минут.</p>"
        f"<p><a href='{safe_link}' style='background:#2563eb;color:white;padding:13px 22px;border-radius:9px;text-decoration:none'>Подтвердить адрес</a></p>"
        "<h2 style='font-size:16px;color:#0f172a;margin-top:30px'>Сведения о запросе</h2>"
        f"<table role='presentation'>{rows}</table>"
        "<p style='color:#64748b;font-size:13px'>Данные об устройстве и расположении приблизительны. "
        "Если это были не вы, проигнорируйте письмо и никому не сообщайте код.</p>"
        "</td></tr></table></td></tr></table></body></html>"
    )
    amp_rows = "".join(
        f"<p><strong>{html.escape(label)}:</strong> {html.escape(value)}</p>"
        for label, value in _detail_lines(details)
    )
    amp_body = (
        '<!doctype html><html amp4email lang="ru"><head><meta charset="utf-8">'
        '<script async src="https://cdn.ampproject.org/v0.js"></script>'
        '<script async custom-element="amp-accordion" src="https://cdn.ampproject.org/v0/amp-accordion-0.1.js"></script>'
        "<style amp4email-boilerplate>body{visibility:hidden}</style>"
        "<style amp-custom>body{font-family:Arial,sans-serif;color:#0f172a;padding:24px}"
        ".code{font-size:36px;letter-spacing:9px;font-weight:bold}.card{max-width:560px;margin:auto}</style>"
        "</head><body><div class='card'><h1>ALXPRGS</h1>"
        f"<p>Здравствуйте, {safe_username}! Ваш код подтверждения:</p><p class='code'>{safe_code}</p>"
        f"<p><a href='{safe_link}'>Подтвердить адрес</a> — действует 10 минут.</p>"
        "<amp-accordion><section><h2>Сведения о запросе</h2>"
        f"<div>{amp_rows}<p>Данные приблизительны.</p></div></section></amp-accordion>"
        "<p>Если это были не вы, проигнорируйте письмо. Никому не сообщайте код.</p>"
        "</div></body></html>"
    )
    message = EmailMessage()
    message["Subject"] = subject
    from_email = (
        settings.SES_FROM_EMAIL if settings.EMAIL_PROVIDER == "ses" else settings.SMTP_FROM_EMAIL
    )
    from_name = settings.SES_FROM_NAME if settings.EMAIL_PROVIDER == "ses" else "ALXPRGS"
    message["From"] = formataddr((from_name, from_email), charset="utf-8")
    message["To"] = to_email
    message.set_content(text_body, charset="utf-8")
    message.add_alternative(amp_body, subtype="x-amp-html", charset="utf-8")
    message.add_alternative(html_body, subtype="html", charset="utf-8")
    return message


def _send_smtp(message: EmailMessage, settings: Settings) -> None:
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(message)


async def deliver_message(message: EmailMessage, settings: Settings) -> None:
    import sentry_sdk

    with sentry_sdk.start_span(op="email.send", name="email.send") as span:
        span.set_data("provider", settings.EMAIL_PROVIDER)
        span.set_data("operation", "send_email")
        span.set_data("template", "email_verification")
        try:
            await _deliver_message(message, settings)
        except Exception:
            span.set_data("result", "failure")
            raise
        else:
            span.set_data("result", "success")


async def _deliver_message(message: EmailMessage, settings: Settings) -> None:
    if settings.EMAIL_PROVIDER == "ses":
        await asyncio.to_thread(
            send_ses_email,
            region=settings.SES_REGION,
            from_email=settings.SES_FROM_EMAIL,
            from_name=settings.SES_FROM_NAME,
            to_email=str(message["To"]),
            subject=str(message["Subject"]),
            text_body="",
            html_body="",
            raw_message=message.as_bytes(policy=SMTP),
        )
    else:
        if not settings.SMTP_HOST or not settings.SMTP_PORT:
            raise SESEmailDeliveryError("smtp_unconfigured")
        try:
            await asyncio.to_thread(_send_smtp, message, settings)
        except (OSError, smtplib.SMTPException) as error:
            raise SESEmailDeliveryError("smtp_connection_failed") from error


def link_url(settings: Settings, token: str, purpose: str) -> str:
    return f"{settings.FRONTEND_URL}/verify-email?mode={quote(purpose)}&token={quote(token)}"


def action_url(settings: Settings, challenge_id: uuid.UUID) -> str:
    return f"{settings.BASE_URL}/api/v1/auth/register/confirm-gmail?challenge_id={challenge_id}"


def link_digest(token: str) -> str:
    return hash_token(token)
