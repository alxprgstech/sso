"""Редактируемое пробное письмо: python scripts/send_test_verification_email.py --to ADDRESS."""

from __future__ import annotations

import argparse
import html
import os
import re
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.ses_email import SESEmailDeliveryError, send_ses_email  # noqa: E402

# РЕДАКТИРУЙТЕ ПИСЬМО ЗДЕСЬ. Подстановки: {code}, {time}, {name}, {account}, {site}.
# CSS-скобки при использовании format нужно удваивать: {{ и }}.
DISPLAY_NAME = "ALXPRGS user"
SITE_URL = "https://auth.alxprgs.tech/"
SUBJECT = "Your ALXPRGS verification code"
TEXT_TEMPLATE = """Hi {name}!

For your ALXPRGS account {account}, your verification code is: {code}
Don't share this code with anyone else.
If you didn't request this code, change your password as soon as possible at {site}.

This email was sent automatically, please don't reply to it.
"""
HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;font-size:14px;color:#222">
<p>Hi <strong>{name}</strong>!</p>
<p>For your ALXPRGS account {account}, your verification code is: {code}<br>
Don't share this code with anyone else.<br>
If you didn't request this code, change your password as soon as possible at
<a href="{site}">auth.alxprgs.tech</a>.</p>
<p>This email was sent automatically, please don't reply to it.</p>
</body></html>
"""


@dataclass(frozen=True)
class MailSettings:
    SES_REGION: str
    SES_FROM_EMAIL: str
    SES_FROM_NAME: str


def validate_address(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value
    ):
        raise ValueError("Invalid single ASCII email address")
    return value


def build_test_message(to_email: str, settings: MailSettings) -> EmailMessage:
    local, domain = to_email.split("@", 1)
    values = {
        "code": f"{secrets.randbelow(1_000_000):06d}",
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "name": DISPLAY_NAME,
        "account": f"{local[:2]}*****@{domain}",
        "site": SITE_URL,
    }
    message = EmailMessage()
    message["Subject"] = SUBJECT
    message["From"] = formataddr((settings.SES_FROM_NAME, settings.SES_FROM_EMAIL))
    message["To"] = to_email
    message.set_content(TEXT_TEMPLATE.format(**values), charset="utf-8")
    message.add_alternative(
        HTML_TEMPLATE.format(**{key: html.escape(value) for key, value in values.items()}),
        subtype="html",
        charset="utf-8",
    )
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="Адрес получателя (не сохраняется в БД)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Проверить письмо без обращения к AWS"
    )
    args = parser.parse_args(argv)
    # Включая AWS credentials для локального запуска; существующее окружение приоритетно.
    load_dotenv(ROOT / ".env", override=False)
    try:
        settings = MailSettings(
            SES_REGION=os.environ.get("SES_REGION", "us-east-1"),
            SES_FROM_EMAIL=validate_address(os.environ.get("SES_FROM_EMAIL", "sso@alxprgs.tech")),
            SES_FROM_NAME=os.environ.get("SES_FROM_NAME", "ALXPRGS"),
        )
        if any(
            not value.strip() or "\r" in value or "\n" in value
            for value in (settings.SES_REGION, settings.SES_FROM_NAME)
        ):
            raise ValueError("Invalid SES configuration")
        recipient = validate_address(args.to)
        message = build_test_message(recipient, settings)
        raw_message = message.as_bytes(policy=SMTP)
        if args.dry_run:
            print("Письмо сформировано (text/plain + text/html). AWS не вызывался.")
            return 0
        message_id = send_ses_email(
            region=settings.SES_REGION,
            from_email=settings.SES_FROM_EMAIL,
            from_name=settings.SES_FROM_NAME,
            to_email=recipient,
            subject=SUBJECT,
            text_body="",
            html_body="",
            raw_message=raw_message,
        )
    except SESEmailDeliveryError as error:
        print(f"SES не принял письмо: {error.reason}", file=sys.stderr)
        return 1
    except (ValueError, KeyError, IndexError):
        print("Проверьте адрес, настройки .env и подстановки в шаблонах.", file=sys.stderr)
        return 1
    print(f"SES принял письмо. MessageId: {message_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
