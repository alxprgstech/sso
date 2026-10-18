"""Strict binary credential identifiers, with one canonical storage representation."""

import base64
import binascii
import re


def canonical_credential_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+/\-]{1,512}={0,2}", value):
        raise ValueError("Invalid credential identifier")
    raw = value.rstrip("=")
    try:
        decoded = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid credential identifier") from None
    if not decoded:
        raise ValueError("Invalid credential identifier")
    return base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
