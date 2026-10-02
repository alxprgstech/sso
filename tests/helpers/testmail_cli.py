"""Private JSON stdin/stdout bridge; errors never include payloads or secrets."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tests.helpers.email_test_settings import (  # noqa: E402
    EmailTestConfigurationError,
    EmailTestSettings,
    load_email_settings,
)
from tests.helpers.testmail_client import (  # noqa: E402
    Checkpoint,
    EmailTestError,
    Mailbox,
    TestmailClient,
    assert_verification_message,
    checkpoint,
    generate_mailbox,
)


def ses_preflight(settings: EmailTestSettings) -> None:
    """Read-only prerequisite checks using the ordinary SDK credential chain."""
    import boto3
    from botocore.config import Config

    os.environ.update(settings.process_environment())
    client = boto3.session.Session().client(
        "sesv2",
        region_name=settings.SES_REGION,
        config=Config(
            connect_timeout=5, read_timeout=5, retries={"mode": "standard", "total_max_attempts": 2}
        ),
    )
    try:
        account = client.get_account()
        if not account.get("ProductionAccessEnabled") or not account.get("SendingEnabled"):
            raise EmailTestError(
                "SES production access and enabled sending are required (sandbox cannot deliver unique recipients)"
            )
        identity = settings.SES_FROM_EMAIL.split("@", 1)[1]
        status = client.get_email_identity(EmailIdentity=identity)
        if not status.get("VerifiedForSendingStatus"):
            raise EmailTestError("SES sender domain identity is not verified")
        configuration = status.get("ConfigurationSetName")
        if configuration:
            result = client.get_configuration_set(ConfigurationSetName=configuration)
            if result.get("SendingOptions", {}).get("SendingEnabled") is False:
                raise EmailTestError("SES identity configuration set disables sending")
    finally:
        client.close()


def preflight(settings: EmailTestSettings) -> None:
    from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

    with TestmailClient(settings) as client:
        client.query_messages(generate_mailbox(settings, "preflight"), checkpoint())
    try:
        ses_preflight(settings)
    except (NoCredentialsError, PartialCredentialsError):
        raise EmailTestError("SES credentials unavailable or incomplete") from None
    except ClientError as exc:
        category = {
            "AccessDeniedException": "access denied",
            "AccessDenied": "access denied",
            "NotFoundException": "identity/configuration set missing",
        }.get(exc.response.get("Error", {}).get("Code"), "provider rejected preflight")
        raise EmailTestError(f"SES {category}") from None


def execute(command: str, settings: EmailTestSettings, payload: dict) -> dict:
    if command == "preflight":
        preflight(settings)
        return {"result": "ready"}
    if command == "address":
        box = generate_mailbox(settings, str(payload.get("context", "browser")))
        return {
            "mailbox": asdict(box),
            "address": box.address,
            "checkpoint": {"timestamp_ms": checkpoint().timestamp_ms, "seen_ids": []},
        }
    box = Mailbox(**payload["mailbox"])
    start = Checkpoint(
        payload["checkpoint"]["timestamp_ms"],
        frozenset(payload["checkpoint"]["seen_ids"]),
        frozenset(payload["checkpoint"].get("seen_content", [])),
    )
    with TestmailClient(settings) as client:
        if command == "checkpoint":
            messages = client.query_messages(box, start)
            point = checkpoint(messages)
            return {
                "timestamp_ms": point.timestamp_ms,
                "seen_ids": sorted(point.seen_ids),
                "seen_content": sorted(point.seen_content),
            }
        message = client.wait_for_message(box, start)
        code, link = assert_verification_message(
            message, box, settings, username=payload["username"], mode=payload["mode"]
        )
        # Returned only over a private pipe. Never persist/log this JSON.
        return {"code": code, "link": link, "message_id": message.id}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Opt-in email infrastructure (no credentials in arguments)"
    )
    parser.add_argument("command", choices=("preflight", "address", "checkpoint", "wait"))
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        settings = load_email_settings()
        payload = {} if args.command == "preflight" else json.load(sys.stdin)
        result = execute(args.command, settings, payload)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (EmailTestError, EmailTestConfigurationError) as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print("Email test infrastructure failed (sensitive details withheld)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
