from __future__ import annotations

import uuid
from email.message import EmailMessage

import pytest
from app.config import Settings
from app.services.registration_service import verify_gmail_bearer
from app.services.ses_email import send_ses_email
from app.services.verification_email import (
    build_message,
    code_hash,
    code_matches,
    new_code,
    request_details,
)
from fastapi import HTTPException, Request


def _settings() -> Settings:
    return Settings.model_construct(
        SESSION_SECRET_KEY="synthetic-unit-test-secret-with-sufficient-length-0123456789",
        EMAIL_PROVIDER="ses",
        SES_FROM_EMAIL="sso@alxprgs.tech",
        SES_FROM_NAME="ALXPRGS",
        TRUSTED_PROXIES=["127.0.0.1"],
    )


def _request(peer: str, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/register",
            "headers": headers,
            "client": (peer, 43210),
            "scheme": "https",
        }
    )


def test_code_keeps_leading_zero_and_uses_keyed_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.verification_email.secrets.randbelow", lambda _: 12345)
    code = new_code()
    assert code == "012345"
    challenge = uuid.uuid4()
    digest = code_hash(_settings(), challenge, code)
    assert code not in digest
    assert code_matches(_settings(), challenge, code, digest)
    assert not code_matches(_settings(), challenge, "012346", digest)
    assert not code_matches(_settings(), uuid.uuid4(), code, digest)


def test_forged_proxy_geo_headers_are_ignored() -> None:
    headers = [
        (b"user-agent", b"Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Mobile"),
        (b"x-forwarded-for", b"198.51.100.2"),
        (b"x-alx-geo-city", b"Fake City"),
    ]
    untrusted = request_details(_request("203.0.113.7", headers), _settings())
    assert untrusted["ip"] == "203.0.113.7"
    assert "city" not in untrusted and "country" not in untrusted
    assert untrusted["os"] == "Windows"
    trusted = request_details(_request("127.0.0.1", headers), _settings())
    assert trusted["ip"] == "198.51.100.2"
    assert "city" not in trusted and "country" not in trusted


def test_mime_contains_fallback_amp_schema_and_escaped_details() -> None:
    message = build_message(
        to_email="recipient@example.test",
        username="<Alex>",
        code="012345",
        link="https://auth.alxprgs.tech/verify-email?token=synthetic",
        action_url="https://auth.alxprgs.tech/api/v1/auth/register/confirm-gmail?challenge_id=abc",
        details={"city": "must-not-collect", "os": "<script>"},
        settings=_settings(),
    )
    assert isinstance(message, EmailMessage)
    parts = list(message.iter_parts())
    assert [part.get_content_type() for part in parts] == [
        "text/plain",
        "text/x-amp-html",
        "text/html",
    ]
    assert "012345" in parts[0].get_content()
    assert "amp-accordion" in parts[1].get_content()
    html = parts[2].get_content()
    assert '"@type": "ConfirmAction"' in html
    assert "&lt;Alex&gt;" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "must-not-collect" not in html

    class FakeSES:
        request: dict[str, object] | None = None

        def send_email(self, **kwargs: object) -> dict[str, str]:
            self.request = kwargs
            return {"MessageId": "synthetic-message-id"}

    fake = FakeSES()
    assert (
        send_ses_email(
            region="us-east-1",
            from_email="sso@alxprgs.tech",
            from_name="ALXPRGS",
            to_email="recipient@example.test",
            subject="Код",
            text_body="",
            html_body="",
            raw_message=message.as_bytes(),
            client=fake,
        )
        == "synthetic-message-id"
    )
    assert fake.request is not None
    assert fake.request["Content"] == {"Raw": {"Data": message.as_bytes()}}


@pytest.mark.asyncio
async def test_gmail_action_rejects_missing_bearer_without_network() -> None:
    with pytest.raises(HTTPException) as exc:
        await verify_gmail_bearer("", _settings())
    assert exc.value.status_code == 401
