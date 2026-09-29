from __future__ import annotations

import logging
import smtplib
import uuid
from email.message import EmailMessage
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.config import Settings
from app.core.exceptions import FeatureDisabledException
from app.models.user import User
from app.services import mfa_service, ses_email
from app.services.mfa_service import EmailVerificationService, sent_emails_sink
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
from pydantic import ValidationError


class FakeSESClient:
    def __init__(self, response: dict[str, str] | None = None) -> None:
        self.response = response or {"MessageId": "ses-message-123"}
        self.request: dict[str, object] | None = None

    def send_email(self, **kwargs: object) -> dict[str, str]:
        self.request = kwargs
        return self.response


def _settings(**kwargs: object) -> Settings:
    return Settings(
        _env_file=None,
        ENVIRONMENT="development",
        FEATURE_EMAIL_VERIFICATION_ENABLED=True,
        EMAIL_PROVIDER="ses",
        SMTP_HOST="",
        **kwargs,
    )


def test_ses_client_uses_sdk_credentials_and_region(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_client(service: str, **kwargs: object) -> FakeSESClient:
        calls.append((service, kwargs))
        return FakeSESClient()

    ses_email.get_ses_client.cache_clear()
    monkeypatch.setattr(ses_email.boto3, "client", fake_client)
    first = ses_email.get_ses_client("us-east-1")
    assert first is ses_email.get_ses_client("us-east-1")
    assert len(calls) == 1
    service, kwargs = calls[0]
    assert service == "sesv2"
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["config"].connect_timeout == 5
    assert kwargs["config"].read_timeout == 5
    assert "aws_access_key_id" not in kwargs
    assert "aws_secret_access_key" not in kwargs
    assert "aws_session_token" not in kwargs
    ses_email.get_ses_client.cache_clear()


def test_ses_v2_multipart_utf8_and_message_id(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeSESClient()
    with caplog.at_level(logging.INFO, logger=ses_email.__name__):
        message_id = ses_email.send_ses_email(
            region="us-east-1",
            from_email="sso@alxprgs.tech",
            from_name="Тест ALXPRGS",
            to_email="recipient@example.test",
            subject="Подтверждение",
            text_body="Здравствуйте, тестовый пользователь",
            html_body="<p>Здравствуйте</p>",
            client=fake,
        )
    assert message_id == "ses-message-123"
    assert fake.request is not None
    assert set(fake.request) == {"FromEmailAddress", "Destination", "Content"}
    assert "=?utf-8?" in str(fake.request["FromEmailAddress"]).lower()
    assert "sso@alxprgs.tech" in str(fake.request["FromEmailAddress"])
    assert fake.request["Destination"] == {"ToAddresses": ["recipient@example.test"]}
    simple = fake.request["Content"]["Simple"]
    assert simple["Subject"] == {"Data": "Подтверждение", "Charset": "UTF-8"}
    assert simple["Body"]["Text"]["Charset"] == "UTF-8"
    assert simple["Body"]["Html"]["Charset"] == "UTF-8"
    assert "ses-message-123" in caplog.text
    assert "recipient@example.test" not in caplog.text
    assert "Здравствуйте" not in caplog.text


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("AccessDeniedException", "access_denied"),
        ("MailFromDomainNotVerifiedException", "sender_not_verified"),
        ("MessageRejected", "ses_rejected"),
        ("TooManyRequestsException", "throttled"),
        ("SendingPausedException", "sending_disabled"),
    ],
)
def test_ses_service_errors_have_safe_reason(code: str, reason: str) -> None:
    class RejectingSESClient:
        def send_email(self, **kwargs: object) -> None:
            raise ClientError(
                {"Error": {"Code": code, "Message": "private-message-content"}}, "SendEmail"
            )

    with pytest.raises(ses_email.SESEmailDeliveryError) as caught:
        ses_email.send_ses_email(
            region="us-east-1",
            from_email="sso@alxprgs.tech",
            from_name="ALXPRGS",
            to_email="recipient@example.test",
            subject="subject",
            text_body="secret",
            html_body="secret",
            client=RejectingSESClient(),
        )
    assert str(caught.value) == reason
    assert "private-message-content" not in str(caught.value)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (NoCredentialsError(), "credentials_unavailable"),
        (
            EndpointConnectionError(endpoint_url="https://email.us-east-1.amazonaws.com"),
            "temporary_unavailable",
        ),
    ],
)
def test_ses_sdk_failures_are_classified(error: Exception, reason: str) -> None:
    class FailingSESClient:
        def send_email(self, **kwargs: object) -> None:
            raise error

    with pytest.raises(ses_email.SESEmailDeliveryError) as caught:
        ses_email.send_ses_email(
            region="us-east-1",
            from_email="sso@alxprgs.tech",
            from_name="ALXPRGS",
            to_email="recipient@example.test",
            subject="subject",
            text_body="secret",
            html_body="secret",
            client=FailingSESClient(),
        )
    assert caught.value.reason == reason


def test_unknown_provider_is_configuration_error() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, EMAIL_PROVIDER="other")


@pytest.mark.parametrize(
    "from_email", ["not-an-address", "bad\nheader@example.com", "тест@example.com"]
)
def test_invalid_ses_sender_is_configuration_error(from_email: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, SES_FROM_EMAIL=from_email)


def test_default_smtp_keeps_text_message_and_transport_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[EmailMessage] = []
    connections: list[tuple[str, int, int]] = []

    class LocalSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            connections.append((host, port, timeout))

        def __enter__(self) -> "LocalSMTP":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def send_message(self, message: EmailMessage) -> None:
            sent.append(message)

    monkeypatch.setattr(smtplib, "SMTP", LocalSMTP)
    settings = Settings(_env_file=None, SMTP_HOST="localhost", SMTP_PORT=1025)
    assert settings.EMAIL_PROVIDER == "smtp"
    ok = EmailVerificationService._send_smtp_email(
        "recipient@example.test", "Тема", "Текст письма", settings
    )
    assert ok is True
    assert connections == [("localhost", 1025, 5)]
    assert len(sent) == 1
    assert sent[0]["From"] == "no-reply@alxprgs.tech"
    assert sent[0]["To"] == "recipient@example.test"
    assert sent[0].get_content_type() == "text/plain"
    assert sent[0].get_content().strip() == "Текст письма"


@pytest.mark.asyncio
async def test_ses_flow_escapes_html_and_does_not_capture_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_emails_sink.clear()
    requests: list[dict[str, object]] = []

    def fake_send(**kwargs: object) -> str:
        requests.append(kwargs)
        return "ses-message-123"

    monkeypatch.setattr(mfa_service, "send_ses_email", fake_send)
    audit = AsyncMock()
    monkeypatch.setattr(mfa_service.AuditService, "log_event", audit)
    db = AsyncMock()
    db.add = MagicMock()
    user = User(id=uuid.uuid4(), username="<script>alert(1)</script>", email="user@example.test")
    token = await EmailVerificationService.send_verification(db, user, user.email, _settings())
    assert len(requests) == 1
    assert "<script>" not in str(requests[0]["html_body"])
    assert "&lt;script&gt;" in str(requests[0]["html_body"])
    assert token in str(requests[0]["text_body"])
    assert sent_emails_sink == []
    assert audit.await_args.kwargs["event_type"] == "email_verification_requested"


@pytest.mark.asyncio
async def test_ses_failure_audited_without_smtp_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(**kwargs: object) -> None:
        raise ses_email.SESEmailDeliveryError("credentials_unavailable")

    def forbidden_smtp(**kwargs: object) -> None:
        raise AssertionError("SMTP fallback is forbidden")

    monkeypatch.setattr(mfa_service, "send_ses_email", fake_send)
    monkeypatch.setattr(EmailVerificationService, "_send_smtp_email", forbidden_smtp)
    audit = AsyncMock()
    monkeypatch.setattr(mfa_service.AuditService, "log_event", audit)
    db = AsyncMock()
    db.add = MagicMock()
    user = User(id=uuid.uuid4(), username="user", email="user@example.test")
    await EmailVerificationService.send_verification(db, user, user.email, _settings())
    assert audit.await_args_list[0].kwargs["event_type"] == "email_delivery_failed"
    assert audit.await_args_list[0].kwargs["details"] == {
        "email": "user@example.test",
        "reason": "credentials_unavailable",
        "provider": "ses",
    }


@pytest.mark.asyncio
async def test_disabled_email_does_not_create_token_or_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_send(**kwargs: object) -> None:
        raise AssertionError("AWS must not be called")

    monkeypatch.setattr(mfa_service, "send_ses_email", forbidden_send)
    db = AsyncMock()
    db.add = MagicMock()
    user = User(id=uuid.uuid4(), username="user", email="user@example.test")
    settings = _settings()
    settings.FEATURE_EMAIL_VERIFICATION_ENABLED = False
    with pytest.raises(FeatureDisabledException):
        await EmailVerificationService.send_verification(db, user, user.email, settings)
    db.add.assert_not_called()
