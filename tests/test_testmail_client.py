"""Offline contract, isolation, deadline and redaction regression tests."""

import json
from dataclasses import replace

import httpx
import pytest

from tests.helpers.email_test_settings import EmailTestConfigurationError, EmailTestSettings
from tests.helpers.testmail_client import (
    Checkpoint,
    EmailTestError,
    ReceivedEmail,
    TestmailClient,
    assert_verification_message,
    checkpoint,
    extract_verification_code,
    extract_verification_link,
    generate_mailbox,
)


@pytest.fixture
def settings():
    return EmailTestSettings(
        _env_file=None,
        TESTMAIL_API_KEY="synthetic-key-for-redaction",
        TESTMAIL_NAMESPACE="example",
        FRONTEND_URL="http://localhost:5173",
        TESTMAIL_TIMEOUT_SECONDS=3,
        TESTMAIL_POLL_INTERVAL_SECONDS=0.5,
    )


def email(box, **changes):
    token = "synthetic_verification_token_123456"
    link = f"http://localhost:5173/verify-email?mode=registration&token={token}"
    message = ReceivedEmail(
        "message-1",
        10000,
        box.tag,
        "ALXPRGS <sso@alxprgs.tech>",
        box.address,
        "Код подтверждения ALXPRGS",
        f"Здравствуйте, alex! Ваш код подтверждения: 000123\n10 минут\nСведения о запросе\n{link}",
        f"<p>alex</p><p>000123</p><p>10 минут</p><h2>Сведения о запросе</h2><a href='{link.replace('&', '&amp;')}'>Confirm</a>",
    )
    return replace(message, **changes)


def response(message=None, **extra):
    rows = (
        []
        if message is None
        else [
            {
                "id": message.id,
                "tag": message.tag,
                "timestamp": message.timestamp_ms,
                "from": message.sender,
                "to": message.recipients,
                "subject": message.subject,
                "text": message.text,
                "html": message.html,
                "headers": [],
                "attachments": [],
            }
        ]
    )
    return {"data": {"inbox": {"result": "success", "count": len(rows), "emails": rows}}, **extra}


def test_unique_mailboxes_and_safe_repr(settings):
    boxes = [generate_mailbox(settings, "same-test-retry") for _ in range(200)]
    assert len({box.address for box in boxes}) == 200
    assert all(len(box.address.split("@")[0]) <= 64 for box in boxes)
    assert "synthetic-key-for-redaction" not in repr(settings)
    assert "000123" not in repr(email(boxes[0]))
    assert "token" not in repr(email(boxes[0]))


def test_poll_exact_filter_auth_and_stale_ids(settings):
    box = generate_mailbox(settings, "poll")
    calls, now = [], [0.0]
    stale = email(box)
    fresh = email(box, id="message-2", timestamp_ms=11000)
    sequence = iter([response(stale), response(fresh)])

    def handler(request):
        calls.append(json.loads(request.content))
        assert str(request.url) == "https://api.testmail.app/api/graphql"
        assert request.headers["Authorization"] == "Bearer synthetic-key-for-redaction"
        return httpx.Response(200, json=next(sequence))

    with TestmailClient(
        settings,
        transport=httpx.MockTransport(handler),
        clock=lambda: now[0],
        sleep=lambda delay: now.__setitem__(0, now[0] + delay),
    ) as client:
        received = client.wait_for_message(box, Checkpoint(10000, frozenset({stale.id})))
    assert received.id == fresh.id
    assert calls[0]["variables"] == {"namespace": box.namespace, "tag": box.tag, "since": 5000}
    assert "livequery: false" in calls[0]["query"]


@pytest.mark.parametrize("status", [429, 503])
def test_retry_preserves_deadline_and_redaction(settings, status):
    box, now = generate_mailbox(settings, "timeout"), [0.0]

    def handler(request):
        return httpx.Response(
            status, headers={"Retry-After": "1000"}, text="synthetic-key-for-redaction 000123"
        )

    with TestmailClient(
        settings,
        transport=httpx.MockTransport(handler),
        clock=lambda: now[0],
        sleep=lambda delay: now.__setitem__(0, now[0] + delay),
    ) as client:
        with pytest.raises(EmailTestError) as caught:
            client.wait_for_message(box, Checkpoint(10000))
    assert now[0] == 3
    assert "Timed out" in str(caught.value)
    assert "synthetic-key-for-redaction" not in str(caught.value)
    assert "000123" not in str(caught.value)


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"errors": [{"message": "synthetic-key-for-redaction"}]}, 200),
        ({}, 401),
        ({"data": {"inbox": {"result": "fail"}}}, 200),
        ({}, 307),
        ({"data": []}, 200),
    ],
)
def test_contract_fail_fast(settings, payload, status):
    box = generate_mailbox(settings, "contract")
    with TestmailClient(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)),
    ) as client:
        with pytest.raises(EmailTestError) as caught:
            client.wait_for_message(box, Checkpoint(10000))
    assert "synthetic-key-for-redaction" not in str(caught.value)


def test_wrong_recipient_rejected(settings):
    box = generate_mailbox(settings, "recipient")
    value = email(box, recipients="other@example.test")
    with TestmailClient(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response(value))),
    ) as client:
        with pytest.raises(EmailTestError, match="recipient/tag mismatch"):
            client.wait_for_message(box, Checkpoint(10000))


def test_code_context_and_link_html_entities(settings):
    box = generate_mailbox(settings, "parse")
    value = email(box)
    code, link = assert_verification_message(
        value, box, settings, username="alex", mode="registration"
    )
    assert code == "000123"
    assert "&token=" in link
    assert (
        extract_verification_code(replace(value, text=value.text + "\nIP 123456; date 202610"))
        == "000123"
    )
    with pytest.raises(EmailTestError, match="ambiguous"):
        extract_verification_code(
            replace(value, text=value.text + "\nВаш код подтверждения: 654321")
        )


@pytest.mark.parametrize(
    "replacement",
    ["http://localhost:9999", "http://localhost:5173.evil.test", "https://localhost:5173"],
)
def test_link_origin_exact(settings, replacement):
    box = generate_mailbox(settings, "url")
    value = email(box)
    value = replace(
        value,
        text=value.text.replace("http://localhost:5173", replacement),
        html=value.html.replace("http://localhost:5173", replacement),
    )
    with pytest.raises(EmailTestError, match="origin/mode/token"):
        extract_verification_link(value, mode="registration", origin=settings.FRONTEND_URL)


def test_missing_credentials_and_process_filtering(settings, monkeypatch):
    with pytest.raises(EmailTestConfigurationError):
        EmailTestSettings(
            _env_file=None, TESTMAIL_API_KEY="", TESTMAIL_NAMESPACE=""
        ).require_credentials()
    monkeypatch.setenv("TESTMAIL_API_KEY", "synthetic-key-for-redaction")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-aws")
    assert "TESTMAIL_API_KEY" not in settings.process_environment(recipient="backend")
    assert "AWS_SECRET_ACCESS_KEY" not in settings.process_environment(recipient="frontend")
    assert settings.application_settings().REQUIRE_VERIFIED_EMAIL is True


def test_late_duplicate_delivery_excluded(settings):
    box = generate_mailbox(settings, "duplicate")
    old = email(box)
    point = checkpoint([old])
    point = replace(point, timestamp_ms=10000)
    duplicate = replace(old, id="late-copy", timestamp_ms=11000)
    fresh = replace(old, id="resend", timestamp_ms=12000, text=old.text + "new request")
    replies = iter([response(duplicate), response(fresh)])
    now = [0.0]
    with TestmailClient(
        settings,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=next(replies))),
        clock=lambda: now[0],
        sleep=lambda delay: now.__setitem__(0, now[0] + delay),
    ) as client:
        assert client.wait_for_message(box, point).id == "resend"


def test_network_retry_then_receive_and_header_schema(settings):
    box = generate_mailbox(settings, "network")
    calls, now = [0], [0.0]
    value = response(email(box))
    value["data"]["inbox"]["emails"][0]["headers"] = [
        {"key": "mime-version", "line": "MIME-Version: 1.0"}
    ]

    def handler(request):
        calls[0] += 1
        if calls[0] == 1:
            raise httpx.ConnectError("synthetic-key-for-redaction", request=request)
        return httpx.Response(200, json=value)

    with TestmailClient(
        settings,
        transport=httpx.MockTransport(handler),
        clock=lambda: now[0],
        sleep=lambda delay: now.__setitem__(0, now[0] + delay),
    ) as client:
        assert client.wait_for_message(box, Checkpoint(10000)).headers == (("mime-version", "1.0"),)


def test_cli_errors_do_not_include_secret_chain(settings, monkeypatch, capsys):
    from tests.helpers import testmail_cli

    monkeypatch.setattr(testmail_cli, "load_email_settings", lambda: settings)
    monkeypatch.setattr("sys.argv", ["testmail_cli", "preflight"])

    def failure(*args):
        raise RuntimeError("synthetic-key-for-redaction OTP 000123")

    monkeypatch.setattr(testmail_cli, "preflight", failure)
    import logging

    previous = logging.root.manager.disable
    try:
        assert testmail_cli.main() == 1
    finally:
        logging.disable(previous)
    output = capsys.readouterr()
    assert output.out == ""
    assert "synthetic-key-for-redaction" not in output.err
    assert "000123" not in output.err
    assert "withheld" in output.err


def test_default_deselection_and_explicit_credentials_error(monkeypatch):
    from types import SimpleNamespace

    from tests import conftest
    from tests.helpers import email_test_settings

    item = SimpleNamespace(get_closest_marker=lambda marker: marker == "email_external")
    deselected = []
    config = SimpleNamespace(
        getoption=lambda name: False,
        hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)),
    )
    items = [item]
    conftest.pytest_collection_modifyitems(config, items)
    assert items == [] and deselected == [item]

    def missing():
        raise EmailTestConfigurationError("TESTMAIL credentials are required")

    monkeypatch.setattr(email_test_settings, "load_email_settings", missing)
    config.getoption = lambda name: name == "--run-email-tests"
    config.option = SimpleNamespace(numprocesses=None)
    with pytest.raises(pytest.UsageError, match="credentials are required"):
        conftest.pytest_collection_modifyitems(config, [item])


def test_ses_sandbox_preflight_never_sends(settings, monkeypatch):
    from types import SimpleNamespace

    import boto3

    from tests.helpers.testmail_cli import ses_preflight

    client = SimpleNamespace(
        get_account=lambda: {"ProductionAccessEnabled": False, "SendingEnabled": True},
        close=lambda: None,
    )
    monkeypatch.setattr(boto3.session.Session, "client", lambda *args, **kwargs: client)
    # Empty synthetic credentials avoid exporting real local values.
    monkeypatch.setattr(EmailTestSettings, "process_environment", lambda self: {})
    with pytest.raises(EmailTestError, match="sandbox"):
        ses_preflight(settings)


def test_message_received_after_deadline_is_not_accepted(settings):
    box, now = generate_mailbox(settings, "deadline"), [0.0]

    def handler(request):
        now[0] = 4
        return httpx.Response(200, json=response(email(box)))

    with TestmailClient(
        settings,
        transport=httpx.MockTransport(handler),
        clock=lambda: now[0],
        sleep=lambda delay: None,
    ) as client:
        with pytest.raises(EmailTestError, match="Timed out"):
            client.wait_for_message(box, Checkpoint(10000))


@pytest.mark.parametrize(
    "field,value",
    [
        ("sender", "Other <sso@alxprgs.tech>"),
        ("subject", "Wrong"),
        ("text", "No verification code"),
        ("attachments", ({"filename": "unexpected.pdf"},)),
    ],
)
def test_fresh_content_failures_are_safe(settings, field, value):
    box = generate_mailbox(settings, "content")
    with pytest.raises(EmailTestError) as caught:
        assert_verification_message(
            replace(email(box), **{field: value}),
            box,
            settings,
            username="alex",
            mode="registration",
        )
    assert "000123" not in str(caught.value) and "token_123456" not in str(caught.value)


def test_configuration_env_precedence_and_validation_redaction(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "TESTMAIL_API_KEY=synthetic-dotenv\nTESTMAIL_NAMESPACE=example\nTESTMAIL_TIMEOUT_SECONDS=10\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TESTMAIL_TIMEOUT_SECONDS", "15")
    value = EmailTestSettings(_env_file=dotenv)
    assert value.TESTMAIL_TIMEOUT_SECONDS == 15
    assert value.TESTMAIL_API_KEY.get_secret_value() == "synthetic-dotenv"
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as caught:
        EmailTestSettings(_env_file=dotenv, FEATURE_EMAIL_VERIFICATION_ENABLED=False)
    assert "synthetic-dotenv" not in str(caught.value)
