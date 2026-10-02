"""Fixtures for explicitly selected external email tests."""

import logging

import pytest_asyncio
from app.config import get_settings
from app.main import app
from app.services.mfa_service import sent_emails_sink
from app.services.ses_email import get_ses_client
from sqlalchemy import text

from tests.db_guard import safe_truncate_test_tables
from tests.helpers.email_test_settings import load_email_settings
from tests.helpers.testmail_client import TestmailClient, generate_mailbox


@pytest_asyncio.fixture
async def external_email(pg_session, monkeypatch, request):
    settings = load_email_settings()
    application = settings.application_settings()
    for key, value in settings.process_environment(recipient="backend").items():
        if key.startswith("AWS_"):
            monkeypatch.setenv(key, value)
    for key in (
        "EMAIL_PROVIDER",
        "ENVIRONMENT",
        "REQUIRE_VERIFIED_EMAIL",
        "BASE_URL",
        "FRONTEND_URL",
    ):
        monkeypatch.setenv(key, str(getattr(application, key)))
    get_settings.cache_clear()
    get_ses_client.cache_clear()
    app.dependency_overrides[get_settings] = lambda: application
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    await pg_session.execute(
        text(
            "UPDATE system_configuration SET bootstrap_completed=true, registration_mode='open' WHERE id=1"
        )
    )
    await pg_session.commit()
    box = generate_mailbox(settings, request.node.nodeid)
    try:
        with TestmailClient(settings) as client:
            yield settings, box, client
    finally:
        app.dependency_overrides.pop(get_settings, None)
        sent_emails_sink.clear()  # Hygiene only; never read codes/tokens from this sink.
        get_settings.cache_clear()
        get_ses_client.cache_clear()
        logging.disable(previous_logging)
        await pg_session.rollback()
        await safe_truncate_test_tables(pg_session)
        await pg_session.commit()
