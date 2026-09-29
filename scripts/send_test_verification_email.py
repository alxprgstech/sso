"""Редактируемое пробное письмо: python scripts/send_test_verification_email.py --to ADDRESS."""

from __future__ import annotations

import argparse
import html
import os
import re
import secrets
import string
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

# Вариант 4: код в самом начале обеих версий. Также можно редактировать.
CODE_FIRST_TEXT = """Your verification code is: {code}

Hi {name}!

For your ALXPRGS account {account}.
Don't share this code with anyone else.
If you didn't request this code, change your password as soon as possible at {site}.

This email was sent automatically, please don't reply to it.
"""
CODE_FIRST_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;font-size:14px;color:#222">
<p>Your verification code is: {code}</p>
<p>Hi <strong>{name}</strong>!</p>
<p>For your ALXPRGS account {account}.<br>
Don't share this code with anyone else.<br>
If you didn't request this code, change your password as soon as possible at
<a href="{site}">auth.alxprgs.tech</a>.</p>
<p>This email was sent automatically, please don't reply to it.</p>
</body></html>
"""
CODE_SUBJECT = "{code} is your ALXPRGS verification code"
VARIANTS = {
    1: "control: text + HTML",
    2: "quoted-printable: long lines, intact code",
    3: "code in subject",
    4: "code at start of body",
    5: "HTML only",
}


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


def build_test_message(
    to_email: str,
    settings: MailSettings,
    *,
    variant: int | None = None,
    code: str | None = None,
    batch_id: str = "",
) -> EmailMessage:
    if variant is not None and variant not in VARIANTS:
        raise ValueError("Unknown variant")
    local, domain = to_email.split("@", 1)
    values = {
        "code": code if code is not None else f"{secrets.randbelow(1_000_000):06d}",
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "name": DISPLAY_NAME,
        "account": f"{local[:2]}*****@{domain}",
        "site": SITE_URL,
    }
    # Увеличиваем только длину QP-строк варианта 2, остальные MIME-параметры одинаковые.
    policy = SMTP.clone(max_line_length=998) if variant == 2 else SMTP
    message = EmailMessage(policy=policy)
    subject = CODE_SUBJECT.format(**values) if variant == 3 else SUBJECT
    if variant is not None:
        # Общие метки нужны для сравнения; буквенный batch_id отделяет повторные прогоны.
        subject += f" [OTP test {variant} {batch_id}]"
    message["Subject"] = subject
    message["From"] = formataddr((settings.SES_FROM_NAME, settings.SES_FROM_EMAIL))
    message["To"] = to_email
    text_template = CODE_FIRST_TEXT if variant == 4 else TEXT_TEMPLATE
    html_template = CODE_FIRST_HTML if variant == 4 else HTML_TEMPLATE
    html_body = html_template.format(**{key: html.escape(value) for key, value in values.items()})
    if variant == 5:
        message.set_content(html_body, subtype="html", charset="utf-8", cte="quoted-printable")
    else:
        message.set_content(text_template.format(**values), charset="utf-8", cte="quoted-printable")
        message.add_alternative(html_body, subtype="html", charset="utf-8", cte="quoted-printable")
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="Адрес получателя (не сохраняется в БД)")
    parser.add_argument(
        "--all-variants", action="store_true", help="Отправить пять вариантов для сравнения Gmail"
    )
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
        variants = list(VARIANTS) if args.all_variants else [None]
        batch_id = "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))
        codes = secrets.SystemRandom().sample(range(1_000_000), len(variants))
        # Формируем весь набор до первой отправки, чтобы ошибка шаблона не дала частичный набор.
        messages = [
            (
                variant,
                build_test_message(
                    recipient, settings, variant=variant, code=f"{code:06d}", batch_id=batch_id
                ),
            )
            for variant, code in zip(variants, codes, strict=True)
        ]
        accepted = 0
        for variant, message in messages:
            raw_message = message.as_bytes()
            label = f"{variant}: {VARIANTS[variant]}" if variant is not None else "single"
            if args.dry_run:
                print(f"Сформирован вариант {label}. AWS не вызывался.")
                continue
            message_id = send_ses_email(
                region=settings.SES_REGION,
                from_email=settings.SES_FROM_EMAIL,
                from_name=settings.SES_FROM_NAME,
                to_email=recipient,
                subject=str(message["Subject"]),
                text_body="",
                html_body="",
                raw_message=raw_message,
            )
            accepted += 1
            print(f"SES принял вариант {label}. MessageId: {message_id}")
    except SESEmailDeliveryError as error:
        print(
            f"SES не принял вариант {label}: {error.reason}. Уже принято: {accepted}. "
            "Отправка остановлена; повторный запуск создаст новый набор.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, KeyError, IndexError):
        print("Проверьте адрес, настройки .env и подстановки в шаблонах.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
