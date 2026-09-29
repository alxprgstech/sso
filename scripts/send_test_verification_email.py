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
# Второй набор: темы без номера/идентификатора. Номера и синтетические коды — в консоли.
CLEAN_SUBJECT = "ALXPRGS Account verification"
MINIMAL_TEXT = """Your ALXPRGS verification code is: {code}
Don't share this code with anyone.
"""
# По структуре предоставленного Xiaomi HTML; без трекера и чужих данных.
FRAGMENT_HTML = """<div>Hi <b>{name}</b>!</div><br>
For your ALXPRGS account {account}, your verification code is: {code}<br>
Don't share this code with anyone else.<br>
If you didn't request this code, change your password as soon as possible at
<a href="{site}">auth.alxprgs.tech</a>.<br><br>
This email was sent automatically, please don't reply to it.<br>
"""
CLEAN_VARIANTS = {
    6: "control: clean subject, text + HTML",
    7: "minimal text only",
    8: "minimal text only + code in subject",
    9: "HTML fragment in multipart/mixed",
    10: "same HTML fragment without MIME container",
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
    if variant is not None and variant not in VARIANTS and variant not in CLEAN_VARIANTS:
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
    subject = CLEAN_SUBJECT if variant in CLEAN_VARIANTS else SUBJECT
    if variant in (3, 8):
        subject = CODE_SUBJECT.format(**values)
    if variant in VARIANTS:
        # Общие метки нужны для сравнения; буквенный batch_id отделяет повторные прогоны.
        subject += f" [OTP test {variant} {batch_id}]"
    message["Subject"] = subject
    message["From"] = formataddr((settings.SES_FROM_NAME, settings.SES_FROM_EMAIL))
    message["To"] = to_email
    text_template = CODE_FIRST_TEXT if variant == 4 else TEXT_TEMPLATE
    html_template = CODE_FIRST_HTML if variant == 4 else HTML_TEMPLATE
    if variant in (7, 8):
        text_template = MINIMAL_TEXT
    if variant in (9, 10):
        html_template = FRAGMENT_HTML
    html_body = html_template.format(**{key: html.escape(value) for key, value in values.items()})
    if variant in (5, 9, 10):
        message.set_content(html_body, subtype="html", charset="utf-8", cte="quoted-printable")
        if variant == 9:
            message.make_mixed()
    elif variant in (7, 8):
        message.set_content(text_template.format(**values), charset="utf-8", cte="7bit")
    else:
        message.set_content(text_template.format(**values), charset="utf-8", cte="quoted-printable")
        message.add_alternative(html_body, subtype="html", charset="utf-8", cte="quoted-printable")
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="Адрес получателя (не сохраняется в БД)")
    batch_modes = parser.add_mutually_exclusive_group()
    batch_modes.add_argument(
        "--all-variants", action="store_true", help="Отправить пять вариантов для сравнения Gmail"
    )
    batch_modes.add_argument(
        "--clean-variants", action="store_true", help="Отправить второй набор 6–10 без меток в теме"
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
        selected = CLEAN_VARIANTS if args.clean_variants else VARIANTS
        variants = list(selected) if args.all_variants or args.clean_variants else [None]
        batch_id = "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))
        codes = secrets.SystemRandom().sample(range(1_000_000), len(variants))
        # Формируем весь набор до первой отправки, чтобы ошибка шаблона не дала частичный набор.
        messages = [
            (
                variant,
                f"{code:06d}",
                build_test_message(
                    recipient, settings, variant=variant, code=f"{code:06d}", batch_id=batch_id
                ),
            )
            for variant, code in zip(variants, codes, strict=True)
        ]
        accepted = 0
        for variant, code, message in messages:
            raw_message = message.as_bytes()
            label = f"{variant}: {selected[variant]}" if variant is not None else "single"
            if args.clean_variants:
                # Эти коды не зарегистрированы в БД и не являются секретами аккаунта.
                print(f"Вариант {variant}: непривязанный тестовый код {code}")
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
