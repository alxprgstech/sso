"""A corrupt/legacy pending row cannot fabricate the required legal acceptance date."""

from datetime import datetime, timedelta, timezone

import pytest
from app.config import get_settings
from app.core.security import hash_password
from app.legal import REQUIRED_DOCUMENTS
from app.models.registration import PendingRegistration
from app.models.user import User
from app.services.registration_service import RegistrationService
from app.services.verification_email import link_digest
from fastapi import HTTPException
from sqlalchemy import select

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]


async def test_pending_registration_without_consent_date_refuses_and_rolls_back(pg_session):
    raw = "synthetic-missing-consent-link"
    pending = PendingRegistration(
        username="missing_consent_date",
        email="consent@example.test",
        password_hash=hash_password("SyntheticConsentGuardPassword2026!"),
        code_hash="0" * 64,
        link_hash=link_digest(raw),
        failed_attempts=0,
        legal_versions=REQUIRED_DOCUMENTS,
        legal_accepted_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        request_details={},
    )
    pg_session.add(pending)
    await pg_session.commit()
    pending_id = pending.id
    with pytest.raises(HTTPException) as error:
        await RegistrationService.confirm(pg_session, settings=get_settings(), link=raw)
    assert error.value.status_code == 400
    assert error.value.detail["error"] == "legal_acceptance_required"
    await pg_session.rollback()
    assert (
        await pg_session.scalar(select(User.id).where(User.username == "missing_consent_date"))
        is None
    )
    assert await pg_session.get(PendingRegistration, pending_id) is not None
