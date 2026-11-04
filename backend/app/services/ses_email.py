from __future__ import annotations

import logging
from email.utils import formataddr
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# boto3/botocore cost ~35 MiB RSS and a noticeable amount of import CPU. SES is
# one of three selectable providers, so the SDK is imported on first real use.
_BOTOCORE_EXCEPTIONS: Any = None


def _botocore_exceptions() -> Any:
    global _BOTOCORE_EXCEPTIONS
    if _BOTOCORE_EXCEPTIONS is None:
        from botocore import exceptions as botocore_exceptions

        _BOTOCORE_EXCEPTIONS = botocore_exceptions
    return _BOTOCORE_EXCEPTIONS


def __getattr__(name: str) -> Any:
    """Expose ``ses_email.boto3`` lazily for callers and tests that patch it."""
    if name == "boto3":
        import boto3

        return boto3
    raise AttributeError(name)


class SESEmailDeliveryError(Exception):
    """Safe, non-sensitive reason for a failed SES submission."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@lru_cache(maxsize=8)
def get_ses_client(region: str) -> Any:
    # Boto3 resolves credentials through its normal providers, including IAM roles.
    # Only the application-specific region and the existing five-second network
    # timeout are set here; retry policy remains under the SDK/AWS configuration.
    import boto3
    from botocore.config import Config

    return boto3.client(
        "sesv2",
        region_name=region,
        config=Config(connect_timeout=5, read_timeout=5),
    )


def _failure_reason(error: Any) -> str:
    code = error.response.get("Error", {}).get("Code", "")
    if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
        return "access_denied"
    if code == "MailFromDomainNotVerifiedException":
        return "sender_not_verified"
    if code in {"TooManyRequestsException", "LimitExceededException"}:
        return "throttled"
    if code in {"AccountSuspendedException", "SendingPausedException"}:
        return "sending_disabled"
    if code in {"MessageRejected", "BadRequestException"}:
        return "ses_rejected"
    return "ses_api_error"


def send_ses_email(
    *,
    region: str,
    from_email: str,
    from_name: str,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str,
    raw_message: bytes | None = None,
    client: Any | None = None,
) -> str:
    """Submit a multipart message and return the SES acceptance MessageId."""
    exceptions = _botocore_exceptions()
    try:
        active_client = client if client is not None else get_ses_client(region)
        content = (
            {"Raw": {"Data": raw_message}}
            if raw_message is not None
            else {
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                }
            }
        )
        response = active_client.send_email(
            FromEmailAddress=formataddr((from_name, from_email), charset="utf-8"),
            Destination={"ToAddresses": [to_email]},
            Content=content,
        )
    except (exceptions.NoCredentialsError, exceptions.PartialCredentialsError) as error:
        raise SESEmailDeliveryError("credentials_unavailable") from error
    except exceptions.ClientError as error:
        raise SESEmailDeliveryError(_failure_reason(error)) from error
    except (
        exceptions.EndpointConnectionError,
        exceptions.ConnectTimeoutError,
        exceptions.ReadTimeoutError,
        exceptions.ConnectionClosedError,
    ) as error:
        raise SESEmailDeliveryError("temporary_unavailable") from error
    except exceptions.BotoCoreError as error:
        raise SESEmailDeliveryError("sdk_error") from error

    message_id = response.get("MessageId")
    if not isinstance(message_id, str) or not message_id:
        raise SESEmailDeliveryError("invalid_response")
    logger.info("ses_email_accepted message_id=%s", message_id)
    return message_id
