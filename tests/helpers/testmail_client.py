"""Bounded GraphQL polling and verification-message assertions, outside runtime."""

from __future__ import annotations

import hashlib
import math
import os
import random
import re
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from tests.helpers.email_test_settings import EmailTestSettings

ENDPOINT = "https://api.testmail.app/api/graphql"
SUBJECT = "Код подтверждения ALXPRGS"
QUERY = """query EmailTest($namespace: String!, $tag: String!, $since: Float!) {
  inbox(namespace: $namespace, tag: $tag, timestamp_from: $since,
        livequery: false, limit: 100) {
    result count emails {
      id tag timestamp from to subject text html
      headers { key line }
      attachments { filename contentType size related }
    }
  }
}"""


class EmailTestError(RuntimeError):
    """Only fixed categories and non-sensitive diagnostics belong in this error."""


class TransientEmailAPIError(EmailTestError):
    def __init__(self, category: str, delay: float = 0):
        super().__init__(category)
        self.delay = delay


@dataclass(frozen=True)
class Mailbox:
    namespace: str
    tag: str

    @property
    def address(self) -> str:
        return f"{self.namespace}.{self.tag}@inbox.testmail.app"


@dataclass(frozen=True)
class Checkpoint:
    timestamp_ms: int
    seen_ids: frozenset[str] = frozenset()
    seen_content: frozenset[str] = frozenset()


def generate_mailbox(settings: EmailTestSettings, context: str) -> Mailbox:
    settings.require_credentials()
    run = "|".join(
        os.getenv(k, "local")
        for k in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "PYTEST_XDIST_WORKER")
    )
    digest = hashlib.sha256(f"{run}|{context}".encode()).hexdigest()[:10]
    return Mailbox(settings.TESTMAIL_NAMESPACE, f"e{digest}{uuid.uuid4().hex}")


def checkpoint(messages: Iterable[ReceivedEmail] = ()) -> Checkpoint:
    messages = tuple(messages)
    return Checkpoint(
        int(time.time() * 1000),
        frozenset(m.id for m in messages),
        frozenset(m.content_fingerprint() for m in messages),
    )


@dataclass(frozen=True, repr=False)
class ReceivedEmail:
    id: str
    timestamp_ms: float
    tag: str
    sender: str = field(repr=False)
    recipients: str = field(repr=False)
    subject: str = field(repr=False)
    text: str = field(repr=False)
    html: str = field(repr=False)
    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    attachments: tuple[dict[str, Any], ...] = field(default=(), repr=False)

    def __repr__(self) -> str:
        return "ReceivedEmail(<redacted>)"

    def content_fingerprint(self) -> str:
        # Suppress late duplicate SES deliveries after a resend checkpoint.
        return hashlib.sha256(
            (self.subject + "\0" + self.text + "\0" + self.html).encode()
        ).hexdigest()


class TestmailClient:
    __test__ = False

    def __init__(
        self,
        settings: EmailTestSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        settings.require_credentials()
        self.settings = settings
        self.clock, self.sleep = clock, sleep
        self.http = httpx.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            headers={"Authorization": f"Bearer {settings.TESTMAIL_API_KEY.get_secret_value()}"},
        )

    def __enter__(self) -> TestmailClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.http.close()

    def query_messages(
        self, mailbox: Mailbox, start: Checkpoint, *, remaining: float = 15
    ) -> list[ReceivedEmail]:
        if mailbox.namespace != self.settings.TESTMAIL_NAMESPACE or not re.fullmatch(
            r"e[a-f0-9]{42}", mailbox.tag
        ):
            raise EmailTestError("Invalid mailbox context")
        try:
            response = self.http.post(
                ENDPOINT,
                json={
                    "query": QUERY,
                    "variables": {
                        "namespace": mailbox.namespace,
                        "tag": mailbox.tag,
                        "since": max(0, start.timestamp_ms - 5000),
                    },
                },
                timeout=httpx.Timeout(min(10, remaining), connect=min(5, remaining)),
            )
        except httpx.TransportError:
            raise TransientEmailAPIError("network") from None
        if response.status_code == 429:
            retry = response.headers.get("Retry-After", "")
            try:
                delay = float(retry)
            except ValueError:
                try:
                    delay = parsedate_to_datetime(retry).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError):
                    delay = 2
            raise TransientEmailAPIError("rate_limit", max(0, delay) if math.isfinite(delay) else 2)
        if response.status_code >= 500:
            raise TransientEmailAPIError("provider_5xx")
        if response.status_code in (401, 403):
            raise EmailTestError("Testmail authentication/namespace access rejected")
        if response.status_code != 200:
            raise EmailTestError(f"Testmail unexpected HTTP status {response.status_code}")
        try:
            body = response.json()
            if body.get("errors"):
                raise EmailTestError("Testmail GraphQL contract/authentication error")
            inbox = body["data"]["inbox"]
            if inbox["result"] != "success":
                raise EmailTestError("Testmail inbox query rejected")
            count = inbox["count"]
            rows = inbox["emails"]
            if (
                not isinstance(rows, list)
                or not isinstance(count, int)
                or count > 100
                or count < len(rows)
            ):
                raise EmailTestError("Testmail unexpected inbox count/pagination")
            messages = []
            for row in rows:
                for name in ("id", "tag", "from", "to", "subject", "text", "html"):
                    if not isinstance(row[name], str):
                        raise EmailTestError("Testmail malformed email field")
                timestamp = float(row["timestamp"])
                if not math.isfinite(timestamp):
                    raise EmailTestError("Testmail malformed timestamp")
                headers = tuple(
                    (h["key"].lower(), h["line"].split(":", 1)[1].strip()) for h in row["headers"]
                )
                attachments = tuple(row["attachments"])
                messages.append(
                    ReceivedEmail(
                        row["id"],
                        timestamp,
                        row["tag"],
                        row["from"],
                        row["to"],
                        row["subject"],
                        row["text"],
                        row["html"],
                        headers,
                        attachments,
                    )
                )
            return messages
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            raise EmailTestError("Testmail malformed response (body withheld)") from None

    def wait_for_message(self, mailbox: Mailbox, start: Checkpoint) -> ReceivedEmail:
        timeout = self.settings.TESTMAIL_TIMEOUT_SECONDS
        deadline = self.clock() + timeout
        attempts, found, failures = 0, 0, 0
        category = "none"
        while self.clock() < deadline:
            attempts += 1
            delay = self.settings.TESTMAIL_POLL_INTERVAL_SECONDS
            try:
                messages = self.query_messages(mailbox, start, remaining=deadline - self.clock())
                found = len(messages)
                if self.clock() >= deadline:
                    break
                candidates = [
                    m
                    for m in messages
                    if m.id not in start.seen_ids
                    and m.timestamp_ms >= start.timestamp_ms - 5000
                    and m.content_fingerprint() not in start.seen_content
                ]
                candidates.sort(key=lambda m: m.timestamp_ms)
                for message in candidates:
                    addresses = [a.lower() for _, a in getaddresses([message.recipients])]
                    if message.tag != mailbox.tag or mailbox.address not in addresses:
                        raise EmailTestError("Testmail fresh message recipient/tag mismatch")
                    return message
                failures = 0
            except TransientEmailAPIError as exc:
                category = str(exc)
                failures += 1
                delay = max(delay, exc.delay, min(10, 2 ** min(failures, 4)))
            self.sleep(min(max(0, deadline - self.clock()), delay + random.uniform(0, 0.2)))
        raise EmailTestError(
            f"Timed out after {timeout:g}s waiting for verification email. "
            f"Recipient: {mailbox.address}; expected subject: {SUBJECT}; "
            f"messages found: {found}; API attempts: {attempts}; last failure: {category}"
        )


class VisibleHTML(HTMLParser):
    def __init__(self, value: str):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self.hidden_depth = 0
        self.feed(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.hidden_depth += 1
        if tag == "a" and not self.hidden_depth:
            self.links.extend(v for k, v in attrs if k == "href" and v)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.hidden_depth = max(0, self.hidden_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def extract_verification_code(message: ReceivedEmail) -> str:
    matches = re.findall(r"Ваш код подтверждения:\s*([0-9]{6})(?![0-9])", message.text)
    if len(matches) != 1:
        raise EmailTestError("Verification email received, but OTP is missing or ambiguous")
    visible = VisibleHTML(message.html)
    codes = [p.strip() for p in visible.parts if re.fullmatch(r"[0-9]{6}", p.strip())]
    if codes != matches:
        raise EmailTestError("Verification OTP differs between text and visible HTML")
    return matches[0]


def extract_verification_link(message: ReceivedEmail, *, mode: str, origin: str) -> str:
    html_links = [v for v in VisibleHTML(message.html).links if urlsplit(v).path == "/verify-email"]
    text_links = [
        v for v in re.findall(r"https?://\S+", message.text) if urlsplit(v).path == "/verify-email"
    ]
    if len(html_links) != 1 or html_links != text_links:
        raise EmailTestError("Verification URL missing, ambiguous or different between text/HTML")
    link = html_links[0]
    try:
        parsed, expected = urlsplit(link), urlsplit(origin)
        params = parse_qs(parsed.query, keep_blank_values=True)
        valid = (
            parsed.scheme in ("http", "https")
            and parsed.scheme == expected.scheme
            and parsed.hostname == expected.hostname
            and parsed.port == expected.port
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and params.keys() == {"mode", "token"}
            and params["mode"] == [mode]
            and len(params["token"]) == 1
            and bool(re.fullmatch(r"[A-Za-z0-9_-]{20,200}", params["token"][0]))
        )
    except ValueError:
        valid = False
    if not valid:
        raise EmailTestError("Verification URL does not match expected origin/mode/token")
    return link


def assert_verification_message(
    message: ReceivedEmail,
    mailbox: Mailbox,
    settings: EmailTestSettings,
    *,
    username: str,
    mode: str,
) -> tuple[str, str]:
    sender_name, sender_address = parseaddr(str(make_header(decode_header(message.sender))))
    if (
        sender_address.lower() != settings.SES_FROM_EMAIL.lower()
        or sender_name != settings.SES_FROM_NAME
    ):
        raise EmailTestError("Verification From address/name mismatch")
    if [a.lower() for _, a in getaddresses([message.recipients])] != [mailbox.address]:
        raise EmailTestError("Verification To mismatch")
    if message.subject != SUBJECT:
        raise EmailTestError("Verification subject mismatch")
    visible = " ".join(VisibleHTML(message.html).parts)
    if not message.html or not message.text:
        raise EmailTestError("Verification text/HTML body missing")
    for value in (username, "10 минут", "Сведения о запросе"):
        if value not in message.text or value not in visible:
            raise EmailTestError("Verification body content mismatch")
    if message.attachments:
        raise EmailTestError("Verification email contains unexpected attachments")
    return (
        extract_verification_code(message),
        extract_verification_link(
            message,
            mode=mode,
            origin=settings.FRONTEND_URL,
        ),
    )
