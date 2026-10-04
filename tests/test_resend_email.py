"""Offline native HTTP contract checks: synthetic key, no external delivery."""

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from app.config import Settings
from app.services import resend_email, verification_email
from app.services.ses_email import SESEmailDeliveryError
from pydantic import ValidationError

KEY = "re_" + "synthetic-resend-unit-key"
MESSAGE_ID = "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"


def settings(**overrides):
    values = dict(
        _env_file=None,
        ENVIRONMENT="testing",
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY=KEY,
        SMTP_HOST="",
        SMTP_FROM_EMAIL="sender@example.test",
    )
    return Settings(**(values | overrides))


def message(cfg):
    return verification_email.build_message(
        to_email="recipient@example.test",
        username="<Тест>",
        code="012345",
        link="https://example.test/verify-email?token=synthetic-link",
        action_url="https://example.test/confirm",
        details={},
        settings=cfg,
    )


@pytest.mark.parametrize(
    "key", ["", " ", "re_test\n", "re_\tvalue", "re_\x00key", "re_\x7fkey", "é"]
)
def test_resend_key_rejected_without_value_in_validation_error(key):
    with pytest.raises(ValidationError) as caught:
        settings(RESEND_API_KEY=key)
    assert "RESEND_API_KEY" in str(caught.value)
    assert "input_value" not in str(caught.value)


def test_missing_resend_key(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, EMAIL_PROVIDER="resend")


@pytest.mark.parametrize(
    "sender",
    [
        "invalid",
        "<x@example.test>",
        "x\n@example.test",
        "é@example.test",
        "x@.test",
        "x..y@example.test",
        "x@example..test",
        "x\x7f@example.test",
    ],
)
def test_resend_sender_validation_is_conditional(sender):
    with pytest.raises(ValidationError):
        settings(SMTP_FROM_EMAIL=sender)
    for provider in ("smtp", "ses"):
        assert (
            settings(
                EMAIL_PROVIDER=provider, SMTP_FROM_EMAIL=sender, RESEND_API_KEY=""
            ).EMAIL_PROVIDER
            == provider
        )


def test_environment_loading_and_secret_projection(monkeypatch, tmp_path: Path):
    for name in ("EMAIL_PROVIDER", "RESEND_API_KEY", "SMTP_FROM_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    dotenv = tmp_path / "synthetic.env"
    dotenv.write_text(
        f"EMAIL_PROVIDER=resend\nRESEND_API_KEY={KEY}\nSMTP_FROM_EMAIL=sender@example.test\n",
        encoding="utf-8",
    )
    cfg = Settings(_env_file=dotenv)
    assert cfg.EMAIL_PROVIDER == "resend"
    assert cfg.RESEND_API_KEY.get_secret_value() == KEY
    assert KEY not in repr(cfg)
    assert "RESEND_API_KEY" not in cfg.model_dump()
    assert KEY not in cfg.model_dump_json()
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    assert Settings(_env_file=dotenv).EMAIL_PROVIDER == "smtp"


@pytest.mark.asyncio
async def test_native_request_maps_original_bodies_and_safe_acceptance_log(caplog):
    cfg = settings()
    original = message(cfg)
    requests = []

    def accept(request):
        requests.append(request)
        return httpx.Response(200, json={"id": MESSAGE_ID})

    async with httpx.AsyncClient(transport=httpx.MockTransport(accept)) as client:
        with caplog.at_level(logging.INFO):
            assert await resend_email.send_resend_email(original, cfg, client=client) == MESSAGE_ID
        assert not client.is_closed  # Caller-owned client remains caller-owned.
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == resend_email.ENDPOINT
    assert request.method == "POST"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.headers["User-Agent"] == "alxprgs-sso"
    assert request.headers["Content-Type"] == "application/json"
    assert set(request.extensions["timeout"].values()) == {5}
    assert "Idempotency-Key" not in request.headers
    payload = json.loads(request.content)
    assert set(payload) == {"from", "to", "subject", "text", "html"}
    assert payload["from"] == "ALXPRGS <sender@example.test>"
    assert payload["to"] == ["recipient@example.test"]
    assert payload["subject"] == str(original["Subject"])
    for subtype, field in (("plain", "text"), ("html", "html")):
        assert payload[field] == original.get_body(preferencelist=(subtype,)).get_content()
    assert "&lt;Тест&gt;" in payload["html"]
    assert "ConfirmAction" in payload["html"]
    assert "amp-accordion" not in payload["html"]
    assert "012345" in payload["text"]
    assert MESSAGE_ID in caplog.text
    for secret in (KEY, "recipient@example.test", "012345", "synthetic-link", "Тест"):
        assert secret not in caplog.text


@pytest.mark.parametrize(
    "status,name,reason",
    [
        (401, "missing_api_key", "access_denied"),
        (403, "restricted_api_key", "access_denied"),
        (403, "suspended_api_key", "access_denied"),
        (403, "validation_error", "message_rejected"),
        (400, "validation_error", "message_rejected"),
        (422, "missing_required_field", "message_rejected"),
        (429, "rate_limit_exceeded", "quota_exceeded"),
        (429, "daily_quota_exceeded", "quota_exceeded"),
        (429, "monthly_quota_exceeded", "quota_exceeded"),
        (500, "application_error", "temporary_unavailable"),
        (503, "service_unavailable", "temporary_unavailable"),
        (404, "not_found", "failed"),
        (307, "redirect", "failed"),
    ],
)
@pytest.mark.asyncio
async def test_api_failure_is_safe_single_attempt(status, name, reason, caplog):
    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={"name": name, "message": KEY + " 012345"},
            headers={"Location": "https://example.test", "Retry-After": "10"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(reject), follow_redirects=True
    ) as client:
        with pytest.raises(SESEmailDeliveryError) as caught:
            await resend_email.send_resend_email(message(settings()), settings(), client=client)
    assert len(requests) == 1
    assert caught.value.reason == reason
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert KEY not in str(caught.value) + caplog.text


@pytest.mark.parametrize(
    "content",
    [b"not-json", b"[]", b"{}", b'{"id":null}', b'{"id":123}', b'{"id":"unsafe-provider-text"}'],
)
@pytest.mark.asyncio
async def test_malformed_success_is_not_acceptance(content, caplog):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content))
    ) as client:
        with pytest.raises(SESEmailDeliveryError, match="invalid_response"):
            await resend_email.send_resend_email(message(settings()), settings(), client=client)
    assert "resend_email_accepted" not in caplog.text


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        httpx.RemoteProtocolError,
    ],
)
@pytest.mark.asyncio
async def test_network_error_does_not_retain_request_or_exception(error_type):
    def fail(request):
        raise error_type(KEY, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(SESEmailDeliveryError) as caught:
            await resend_email.send_resend_email(message(settings()), settings(), client=client)
    assert str(caught.value) == "temporary_unavailable"
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_async_cancellation_closes_owned_client(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def wait(request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"id": MESSAGE_ID})

    client = httpx.AsyncClient(transport=httpx.MockTransport(wait))
    monkeypatch.setattr(resend_email.httpx, "AsyncClient", lambda **_: client)
    task = asyncio.create_task(resend_email.send_resend_email(message(settings()), settings()))
    await asyncio.wait_for(started.wait(), timeout=2)
    assert not task.done()  # Other coroutines executed while send was waiting.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.is_closed


@pytest.mark.asyncio
async def test_dispatch_selects_resend_and_never_falls_back(monkeypatch):
    adapter = AsyncMock(side_effect=SESEmailDeliveryError("access_denied"))
    monkeypatch.setattr(verification_email, "send_resend_email", adapter)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected SES/SMTP fallback")

    monkeypatch.setattr(verification_email, "send_ses_email", forbidden)
    monkeypatch.setattr(verification_email, "_send_smtp", forbidden)
    cfg = settings()
    original = message(cfg)
    with pytest.raises(SESEmailDeliveryError, match="access_denied"):
        await verification_email.deliver_message(original, cfg)
    adapter.assert_awaited_once_with(original, cfg)
