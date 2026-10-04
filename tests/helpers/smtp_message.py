"""Read verification links from actual local SMTP deliveries."""

from email import message_from_string, policy
from urllib.parse import parse_qs, urlsplit


def verification_token(message: str) -> str:
    delivered = message_from_string(message, policy=policy.default)
    plain = delivered.get_body(preferencelist=("plain",)).get_content()
    link = next(word for word in plain.split() if "/verify-email?" in word)
    return parse_qs(urlsplit(link).query)["token"][0]
